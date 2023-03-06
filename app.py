import json
import pytz
import httpx
from quart import render_template, send_from_directory, send_file
import logging
from os import environ
from base64 import b64decode
from hashlib import sha512
from collections import defaultdict
from typing import List

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
from dateutil.parser import isoparse
from datetime import datetime, timedelta

session = requests_cache.CachedSession("../erase_cache")


from quart_trio import QuartTrio

app = QuartTrio(__name__)

log = logging.getLogger(__name__)

APP_ID = environ.get("APP_ID")
pem_data = b64decode(environ.get("PEM64"))
print(APP_ID, sha512(pem_data).hexdigest())


instance = jwt.JWT()
pem_file = jwt.jwk_from_pem(pem_data)


MINUTE = 60
VALIDITY = 1 * MINUTE


def bt():
    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + VALIDITY,
        "iss": APP_ID,
    }
    return instance.encode(payload, pem_file, alg="RS256")



PAT = bt()
headers = {"Authorization": f"Bearer {PAT}", "Accept": "application/vnd.github.v3+json"}

inst = session.get(f"https://api.github.com/app/installations", headers=headers).json()

print(inst)

installation_id = inst[0]["id"]
access_token_url = (
    f"https://api.github.com/app/installations/{installation_id}/access_tokens"
)


class Auth:

    def __init__(self, access_token_url, bt):
        self._access_token_url = access_token_url
        self._bt = bt
        self._idata = None
        self._regen()

    def _regen(self):
        headers = {
            "Authorization": f"Bearer {self._bt()}",
            "Accept": "application/vnd.github.v3+json",
        }
        response = requests.post(self._access_token_url, data=b"", headers=headers)
        self._idata = response.json()
        print("new expires_at idata:", repr(self._idata))
        self._expires = isoparse(self._idata["expires_at"]) - timedelta(seconds=10)

    @property
    def header(self):
        now = datetime.now(pytz.UTC)
        if self._expires < now:
            print("Expired header, regenerate, (expires, now)", self._expires, now)
            self._regen()
        print(f"tk: token {self._idata['token']}")
        return {
            "Authorization": f"token {self._idata['token']}",
            "Accept": "application/vnd.github.v3+json",
        }



AUTH = Auth(access_token_url, bt)


response = requests.post(access_token_url, data=b"", headers=headers)

idata = response.json()
print(idata)


h2 = {
    "Authorization": f"token {idata['token']}",
    "Accept": "application/vnd.github.v3+json",
}


@app.route("/gh/<org>/<repo>")
async def other(org, repo):
    all_data = session.get(
        f"https://api.github.com/repos/{org}/{repo}/pulls", headers=AUTH.header
    ).json()
    return json.dumps([x["number"] for x in all_data])


@app.route("/")
async def index():
    return await render_template("index.html", org=None, repo=None, number=None)


@app.route("/gh/<org>/<repo>/pull/<number>")
async def pull(org, repo, number):
    log.warning("Normal handler PR")
    print("P Normal handler PR")
    assert org.isalnum()
    assert repo.isalnum()
    assert number.isnumeric()
    return await render_template("index.html", org=org, repo=repo, number=number)


@app.route("/index.js")
async def index_js():
    print("IJS")
    return await send_file("./templates/index.js")


def clean_item(d):
    del d['created']
    del d['duration']
    del d['exitcode']
    del d['environment']
    del d['root']
    del d['collectors']
    del d['summary']
    del d['warnings']
    for t in d['tests']:
        del t['keywords']
        del t['lineno']
        del t['outcome']


async def collect_most_recent_workflow_runs(org: str, repo: str, ref: str) -> List[str]:
    data = []
    async with httpx.AsyncClient() as client:
        for i in range(50):
            log.warning("Looking for runs artifacts %s", i)

            d = (
                await client.get(
                    f"https://api.github.com/repos/{org}/{repo}/actions/runs",
                    params={
                        "per_pages": 100,
                        "page": i,
                        "event": "pull_request",
                        "branch": ref,
                    },
                    headers=AUTH.header,
                )
            ).json()
            data.extend(d["workflow_runs"])
            if len(d["workflow_runs"]) == 0:
                log.warning("No more run after page %s", i)
                break

    return data


async def list_artifacts_urls_to_download(data, head_sha)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for i, art in enumerate(
            {d["artifacts_url"] for d in data if d["head_sha"] == head["sha"]}
        ):
            data = (await client.get(
                art,
                headers=AUTH.header,
            )).json()
            log.warning("Found Artifacts %s on page %s (pr %s)", len(data["artifacts"]), i, number)

            for artifact in data["artifacts"]:
                log.info('Artifact:', artifact['name'])
                if "pytest" in artifact["name"]:
                    log.warning("Found pytest in name for %s", artifact["name"])
                    acc.append(artifact["archive_download_url"])

        log.info('Found %s artifacts for PR %s with pytest in name', len(acc), number)


@app.route("/api/gh/<org>/<repo>/pull/<number>")
async def api_pull(org, repo, number):
    log.warning("API Pull")
    assert org.isalnum()
    assert repo.isalnum()
    assert number.isnumeric()
    url = f"https://api.github.com/repos/{org}/{repo}/pulls/{number}"
    pr_data = requests.get(
        url, headers=AUTH.header
    ).json()
    if "head" not in pr_data:
        log.warning("NO Head : %s", pr_data.keys())
        log.warning(f"URL: {url} ont work", json.dumps(pr_data))
        return json.dumps(pr_data)
    head = pr_data["head"]
    head["sha"]

    data = await collect_most_recent_workflow_runs(org, repo, head["ref"])

    acc = []
    log.warning("Looking for Artifacts...")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for i, art in enumerate(
            {d["artifacts_url"] for d in data if d["head_sha"] == head["sha"]}
        ):
            data = (await client.get(
                art,
                headers=AUTH.header,
            )).json()
            log.warning("Found Artifacts %s on page %s (pr %s)", len(data["artifacts"]), i, number)

            for artifact in data["artifacts"]:
                log.info('Artifact:', artifact['name'])
                if "pytest" in artifact["name"]:
                    log.warning("Found pytest in name for %s", artifact["name"])
                    acc.append(artifact["archive_download_url"])

        log.info('Found %s artifacts for PR %s with pytest in name', len(acc), number)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        data = {}
        for i, arch in enumerate(acc):
            log.warning(f"Requesting Content... %s ({number})", i)
            zp = await client.get(arch, headers=AUTH.header)
            log.warning(f"Unzipping in memory... %s ({number})", i)
            zp.raise_for_status()
            z = ZipFile(BytesIO(zp.content))
            for j, fx in enumerate(z.filelist):
                log.warning(f"rezip... %s/%s ({number})", j, len(z.filelist))
                xs = json.loads(z.read(fx))
                ## keep only what's necessary
                data[fx.filename] = {"tests": xs["tests"]}
                for t in data[fx.filename]['tests']:
                    del t['keywords']
                    del t['lineno']
                    del t['outcome']

    log.warning("json serialise")
    rz = json.dumps(data)
    log.warning("sending... %s Mb", len(rz) / 1024 / 1024)
    return rz

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 1234))
    print("Seen config port ", port)
    prod = os.environ.get("PROD", None)
    if prod:
        app.run(port=port, host="0.0.0.0")
    else:
        app.run(port=port)
