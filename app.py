import json
from flask import Flask, render_template, send_from_directory, send_file
import logging
from os import environ
from base64 import b64decode
from hashlib import sha512

import jwt
import os
import time
from base64 import b64encode
from pathlib import Path
from base64 import b64encode
from hashlib import sha512
import requests
from zipfile import ZipFile
from io import StringIO, BytesIO
import requests_cache

session = requests_cache.CachedSession("../erase_cache")


app = Flask(__name__)

log = logging.getLogger(__name__)

APP_ID = environ.get("APP_ID")
pem_data = b64decode(environ.get("PEM64"))
print(APP_ID, sha512(pem_data).hexdigest())


instance = jwt.JWT()
pem_file = jwt.jwk_from_pem(pem_data)

payload = {
    "iat": int(time.time()),
    "exp": int(time.time()) + (10 * 60),
    "iss": APP_ID,
}
bearer_token = instance.encode(payload, pem_file, alg="RS256")



PAT = bearer_token
headers = {"Authorization": f"Bearer {PAT}", "Accept": "application/vnd.github.v3+json"}

inst = session.get(f"https://api.github.com/app/installations", headers=headers).json()

installation_id = inst[0]["id"]
access_token_url = (
    f"https://api.github.com/app/installations/{installation_id}/access_tokens"
)
response = requests.post(access_token_url, data=b"", headers=headers)

idata = response.json()
idata["token"]

h2 = {
    "Authorization": f"token {idata['token']}",
    "Accept": "application/vnd.github.v3+json",
}


@app.route("/gh/<org>/<repo>")
def other(org, repo):
    all_data = session.get(
        f"https://api.github.com/repos/{org}/{repo}/pulls", headers=h2
    ).json()
    return json.dumps([x["number"] for x in all_data])


@app.route("/gh/<org>/<repo>/pull/<number>")
def pull(org, repo, number):
    log.warning("Normal handler PR")
    print("P Normal handler PR")
    assert org.isalnum()
    assert repo.isalnum()
    assert number.isnumeric()
    return render_template("index.html", org=org, repo=repo, number=number)


@app.route("/index.js")
def index_js():
    print("IJS")
    return send_file("./templates/index.js")


@app.route("/api/gh/<org>/<repo>/pull/<number>")
def api_pull(org, repo, number):
    log.warning("API Pull")
    assert org.isalnum()
    assert repo.isalnum()
    assert number.isnumeric()

    pr_data = requests.get(
        f"https://api.github.com/repos/{org}/{repo}/pulls/{number}", headers=h2
    ).json()
    if "head" not in pr_data:
        log.warning("NO Head : %s", pr_data.keys())
        log.warning("Wont work")
        return json.dumps(pr_data)
    head = pr_data["head"]
    head["sha"]

    data = []
    for i in range(50):
        log.warning("Looking for runs artifacts %s", i)

        d = session.get(
            f"https://api.github.com/repos/{org}/{repo}/actions/runs",
            params={
                "per_pages": 100,
                "page": i,
                "event": "pull_request",
                "branch": head["ref"],
            },
            headers=h2,
        ).json()
        data.extend(d["workflow_runs"])
        if len(d["workflow_runs"]) == 0:
            log.warning("No more run after page %s", i)
            break

    acc = []
    log.warning("Downloading Artifacts...")
    for i, art in enumerate(
        {d["artifacts_url"] for d in data if d["head_sha"] == head["sha"]}
    ):
        data = session.get(
            art,
            headers=h2,
        ).json()
        log.warning("Downloading Artifacts... %s", i)

        for x in data["artifacts"]:
            if "pytest" in x["name"]:
                log.warning("Found pytest in name for %s", x["name"])
                acc.append(x["archive_download_url"])

    data = {}
    for i, arch in enumerate(acc):
        log.warning("rezip... %s", i)
        zp = session.get(arch, headers=h2)
        z = ZipFile(BytesIO(zp.content))
        for fx in z.filelist:
            xs = json.loads(z.read(fx))
            ## keep only what's necessary
            data[fx.filename] = {"tests": xs["tests"]}
        log.warning("reziped... %s", i)

    log.warning("json serialise")
    rz = json.dumps(data)
    log.warning("sending... %s Mb", len(rz) / 1024 / 1024)
    return rz
