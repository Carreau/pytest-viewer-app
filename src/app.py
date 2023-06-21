import json
import logging
import os
import shelve
import sys
import time
from base64 import b64decode
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha512
from io import BytesIO
from os import environ, environb
from pathlib import Path
from typing import List, NewType
from zipfile import ZipFile

import httpx
import jwt
import pytz
import requests
import requests_cache
from dateutil.parser import isoparse
from dotenv import load_dotenv
from psycopg2.errors import UniqueViolation
from quart import Response, make_response, render_template, send_file
from trio import sleep

from .postgres import db_get_cursor

CommitSha = NewType("CommitSha", str)


@dataclass
class WorkflowRun:
    id: int
    name: str
    head_branch: str
    head_sha: str
    status: str
    conclusion: str
    url: str
    html_url: str
    created_at: str
    updated_at: str
    artifacts_url: CommitSha

    @classmethod
    def from_json(cls, data):
        return cls(
            id=data["id"],
            name=data["name"],
            head_branch=data["head_branch"],
            head_sha=CommitSha(data["head_sha"]),
            status=data["status"],
            conclusion=data["conclusion"],
            url=data["url"],
            html_url=data["html_url"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            artifacts_url=data["artifacts_url"],
        )


load_dotenv()

session = requests_cache.CachedSession("../erase_cache")


from dataclasses import dataclass

from quart_trio import QuartTrio


@dataclass
class ServerSentEvent:
    data: str
    event: str | None = None
    id: int | None = None
    retry: int | None = None

    def encode(self) -> bytes:
        message = f"data: {self.data}"
        if self.event is not None:
            message += f"\nevent: {self.event}"
        if self.id is not None:
            message += f"\nid: {self.id}"
        if self.retry is not None:
            message += f"\nretry: {self.retry}"
        message = f"{message}\n\n"
        return message.encode("utf-8")


app = QuartTrio(__name__)
log = logging.getLogger(__name__)

APP_ID = environ.get("APP_ID")
pem_data = b64decode(environb.get("PEM64"))
print("APP_ID", APP_ID, "PEM DIGEST", sha512(pem_data).hexdigest())


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

inst = session.get("https://api.github.com/app/installations", headers=headers).json()


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
        print("new expires_at idata:", repr(self._idata["expires_at"]))
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


@app.route("/collect_artifact_metadata/<org>/<repo>/<int:pull_number>/<int:run_id>")
async def collect_artifact_metadata(org: str, repo: str, pull_number: int, run_id: str):
    with db_get_cursor() as cursor:
        try:
            # Should we have a ON CONFLICT (organization, repo, run_id, pull_number) DO NOTHING;
            res = cursor.execute(
                """
                INSERT INTO action_run (organization, repo, run_id, pull_number)
                VALUES (%s, %s, %s, %s)
            """,
                (org, repo, pull_number, run_id),
            )
            return "ok"
        except UniqueViolation:
            return "duplicate"


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
    path = os.path.dirname(os.path.realpath(__file__))
    return await send_file(os.path.join(path, "templates", "index.js"))


def clean_item(d):
    del d["created"]
    del d["duration"]
    del d["exitcode"]
    del d["environment"]
    del d["root"]
    del d["collectors"]
    del d["summary"]
    del d["warnings"]
    for t in d["tests"]:
        del t["keywords"]
        del t["lineno"]
        del t["outcome"]


async def collect_most_recent_workflow_runs(
    org: str, repo: str, ref: str
) -> List[WorkflowRun]:
    """
    Return a list of workflow run for the most recent workflow runs


    """
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
            wrs = [WorkflowRun.from_json(x) for x in d["workflow_runs"]]
            data.extend(wrs)
            if len(d["workflow_runs"]) == 0:
                log.warning("No more run after page %s", i)
                break
    return data


async def list_artifacts_urls_to_download(data, head_sha, number):
    acc = []
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for i, art in enumerate(
            {d.artifacts_url for d in data if d.head_sha == head_sha}
        ):
            data = (
                await client.get(
                    art,
                    headers=AUTH.header,
                )
            ).json()
            log.warning(
                "Found Artifacts %s on page %s (pr %s)",
                len(data["artifacts"]),
                i,
                number,
            )

            for artifact in data["artifacts"]:
                log.info("Artifact:", artifact["name"])
                if "pytest" in artifact["name"]:
                    log.warning("Found pytest in name for %s", artifact["name"])
                    acc.append(artifact["archive_download_url"])

        log.info("Found %s artifacts for PR %s with pytest in name", len(acc), number)

    return acc


pkl = Path("./.cache.pkl.db")
if pkl.exists():
    print("USING SHELVE")
    CACHE = shelve.open(".cache.pkl")
else:
    print("NOT USING SHELVE", pkl, "does not extis")
    CACHE = {}  # type : ignore[assignment]


@app.route("/sse-endpoint")
async def sse():
    async def send_events():
        for i, m in zip(
            range(10), ["frobulate", "nobulate", "refine", "extrapole", "fetch"]
        ):
            data = json.dumps({"i": i, "info": m})
            event = ServerSentEvent(data)
            ee = event.encode()
            print("yied ee", ee)
            await sleep(1)
            yield ee

    response = await make_response(
        send_events(),
        {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Transfer-Encoding": "chunked",
        },
    )
    response.timeout = None
    return response


@app.route("/api/gh/<org>/<repo>/pull/<number>")
async def api_pull(org, repo, number):
    async def gen_api_pull(org, repo, number):
        log.warning("API Pull")
        assert org.isalnum()
        assert repo.isalnum()
        assert number.isnumeric()
        url = f"https://api.github.com/repos/{org}/{repo}/pulls/{number}"
        pr_data = requests.get(url, headers=AUTH.header).json()
        if "head" not in pr_data:
            log.warning("NO Head : %s", pr_data.keys())
            log.warning(f"URL: {url} wont work", json.dumps(pr_data))
            yield ServerSentEvent(json.dumps({"info": "no head"})).encode()
            raise StopIteration
            # return json.dumps(pr_data)
        head = pr_data["head"]

        wrs: List[WorkflowRun] = await collect_most_recent_workflow_runs(
            org, repo, head["ref"]
        )

        log.warning("Looking for Artifacts...")
        yield ServerSentEvent(
            json.dumps({"info": "Looking for GH artifacts..."})
        ).encode()
        acc = await list_artifacts_urls_to_download(wrs, head["sha"], number)

        yield ServerSentEvent(
            json.dumps({"info": f"Requesting list of artifact from GH..."})
        ).encode()

        async with httpx.AsyncClient(follow_redirects=True) as client:
            data = {}
            la = len(acc)
            for i, archive in enumerate(acc):
                log.warning(f"Requesting Content... %s ({number})", i)
                print("archive", archive)
                if archive in CACHE:
                    print("CACHE HIT")
                    content = CACHE[archive]
                else:
                    yield ServerSentEvent(
                        json.dumps({"info": f"Downloading artifacts {i+1}/{la}..."})
                    ).encode()
                    zp = await client.get(archive, headers=AUTH.header)
                    yield ServerSentEvent(
                        json.dumps({"info": f"Got artifacts {i+1}/{la}..."})
                    ).encode()
                    log.warning(f"Unzipping in memory... %s ({number})", i)
                    zp.raise_for_status()
                    content = zp.content
                    print("PUT IN CACHE", archive)
                    CACHE[archive] = content
                    CACHE.sync()
                yield ServerSentEvent(
                    json.dumps({"info": f"Extracting artifact {i+1}..."})
                ).encode()
                z = ZipFile(BytesIO(content))
                lll = len(z.filelist)
                for j, fx in enumerate(z.filelist):
                    yield ServerSentEvent(
                        json.dumps({"info": f"Processing file {i+1}-{j+1}/{lll}..."})
                    ).encode()
                    import gc

                    gc.collect()

                    log.warning(f"rezip... %s/%s %s ({number})", j, len(z.filelist), fx)
                    z_read = z.read(fx)
                    xs = json.loads(z_read)
                    del z_read
                    xs_tests = xs["tests"]
                    comp_test = []

                    for item in xs_tests:
                        if "outcome" in item and item["outcome"] == "skipped":
                            continue
                        if "call" in item:
                            comp_test.append(
                                (
                                    item["nodeid"],
                                    item["call"]["duration"],
                                    item["setup"]["duration"],
                                    item["teardown"]["duration"],
                                )
                            )
                        else:
                            print(item)

                    del xs
                    ## keep only what's necessary
                    data[fx.filename] = {"comp": comp_test}

        yield ServerSentEvent(json.dumps({"info": f"Data ready, sending..."})).encode()
        yield ServerSentEvent(json.dumps({"test_data": data, "info": "done"})).encode()
        yield ServerSentEvent(
            json.dumps({"close": True, "info": "closing connection"})
        ).encode()
        # log.warning("json serialise")
        # rz = json.dumps(data)
        # log.warning("sending... %s Mb", len(rz) / 1024 / 1024)
        # return rz

    print("make response")
    response = await make_response(
        gen_api_pull(org, repo, number),
        {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Transfer-Encoding": "chunked",
        },
    )
    response.timeout = None
    return response


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 1234))
    print("Seen config port ", port)
    prod = os.environ.get("PROD", None)
    print("Prod= ", prod)
    try:
        if prod or True:
            app.run(port=port, host="0.0.0.0")
        else:
            app.run(port=port)
    except KeyboardInterrupt:
        print("CLOSING CACHE")
        CACHE.close()
        raise
