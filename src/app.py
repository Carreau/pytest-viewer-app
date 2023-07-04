import gc
import json
import logging
import os
import shelve
import time
from base64 import b64decode
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha512
from io import BytesIO
from os import environ, environb
from pathlib import Path
from random import choice, randint
from typing import List, NewType
from zipfile import ZipFile

import httpx
import jwt
import requests
import requests_cache
from dateutil.parser import isoparse
from dotenv import load_dotenv
from psycopg2.errors import UniqueViolation
from quart import Response, make_response, render_template, send_file
from quart_trio import QuartTrio

from .auth import Auth
from .github_types import CommitSha, PullRequest, RunId, WorkflowRun
from .postgres import db_get_cursor

load_dotenv()

session = requests_cache.CachedSession("../erase_cache")



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
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

APP_ID = environ.get("APP_ID")
pem_b = environb.get(b"PEM64")
pem_data = b64decode(pem_b)  # type:ignore
log.info("APP_ID %s PEM DIGEST %s", APP_ID, sha512(pem_data).hexdigest())


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


AUTH = Auth(access_token_url, bt)


response = requests.post(access_token_url, data=b"", headers=headers)

idata = response.json()


h2 = {
    "Authorization": f"token {idata['token']}",
    "Accept": "application/vnd.github.v3+json",
}


@app.route("/api/pulls")
async def pulls():
    with db_get_cursor() as cursor:
        try:
            cursor.execute(
                #  here we want only T UNIQUE organization, repo, pull_number  FROM action_run LIMIT 50 ORDER BY id DESC
                """
                SELECT DISTINCT ON (organization, repo, pull_number)
                    organization, repo, pull_number
                FROM action_run
                ORDER BY organization, repo, pull_number DESC
                LIMIT 50
            """
            )
            results = cursor.fetchall()
            data = [
                {
                    "value": f"{org}/{repo}/{pull_number}",
                    "name": f"{org}/{repo}/{pull_number}",
                }
                for org, repo, pull_number in results
            ]
            return json.dumps(data)
        except Exception as e:
            log.exception(e)
            raise

    # dat_ = {
    #    "{}/{}".format(choice(["ipython/ipython", "napari/napari"]), randint(1, 100))
    #    for _ in range(10)
    # }
    # data = [{"value": x, "name": x} for x in dat_]
    # return json.dumps(data)


@app.route("/gh/<org>/<repo>")
async def other(org, repo):
    all_data = session.get(
        f"https://api.github.com/repos/{org}/{repo}/pulls", headers=AUTH.header
    ).json()
    return json.dumps([x["number"] for x in all_data])


@app.route("/")
async def index():
    return await render_template("index.html", org=None, repo=None, number=None)


@app.route("/collect_artifact_metadata/<org>/<repo>/<int:pull_number>/<run_id>")
async def collect_artifact_metadata(org: str, repo: str, pull_number: int, run_id: str):
    assert isinstance(org, str)
    assert isinstance(repo, str)
    assert isinstance(pull_number, int)
    assert isinstance(run_id, str)
    with db_get_cursor() as cursor:
        try:
            # Should we have a ON CONFLICT (organization, repo, run_id, pull_number) DO NOTHING;
            res = cursor.execute(
                """
                INSERT INTO action_run (organization, repo, run_id, pull_number)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (organization, repo, run_id, pull_number) DO NOTHING
            """,
                (org, repo, run_id, pull_number),
            )
            return "ok"
        except UniqueViolation:
            return "duplicate"


@app.route("/action_run")
async def list_action_runs():
    with db_get_cursor() as cursor:
        cursor.execute(
            """
            SELECT organization, repo, pull_number, run_id FROM action_run
        """,
            (),
        )
        return cursor.fetchall()


@app.route("/gh/<org>/<repo>/pull/<number>")
async def pull(org, repo, number):
    log.warning("Normal handler PR")
    print("P Normal handler PR")
    assert org.isalnum()
    assert repo.isalnum()
    assert number.isnumeric()
    path = os.path.dirname(os.path.realpath(__file__))
    return await send_file(os.path.join(path, "templates", "index.html"))


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
    org: str, repo: str, ref: str, sha: CommitSha
) -> List[WorkflowRun]:
    """
    Return a list of workflow run for the most recent workflow runs

    This is a workaround from GitHub not allowing us to get all runs for a given
    PR.
    """
    w_runs: List[WorkflowRun] = []
    async with httpx.AsyncClient() as client:
        log.warning(
            "Looking for runs artifacts on for %s/%s, ref=%s sha=%s",
            org,
            repo,
            ref,
            sha,
        )
        for i in range(50):
            log.warning("Looking for runs artifacts on page %s", i)

            d = (
                await client.get(
                    f"https://api.github.com/repos/{org}/{repo}/actions/runs",
                    params={
                        "per_pages": 100,
                        "page": i,
                        "event": "pull_request",
                        # "branch": ref,
                        "head_sha": sha,
                        # it might be interested to also ast for hte head_sha
                        # parameter if we knkow the pr numbe
                    },
                    headers=AUTH.header,
                )
            ).json()
            wrs = [WorkflowRun.from_json(x) for x in d["workflow_runs"]]
            w_runs.extend(wrs)
            if len(d["workflow_runs"]) == 0:
                # we do get a `total_count` so we might be able to do better
                log.info("No more run after page %s", i)
                break
    return w_runs


async def list_artifacts_urls_to_download(
    data: List[WorkflowRun], head_sha: CommitSha, number: int
) -> List[str]:
    """
    Filter worflow runs that both:
        - have the same head_sha as the one we want
        - have pytest in the name of the artifact
    """
    acc = []
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for i, d in enumerate(data):
            log.debug("analysing workflow run", d.id)
            log.debug("    head_sha", d.head_sha)
            log.debug("    id:", d.id)
            log.debug("    artifact_url", d.artifacts_url)
            log.debug("    artifact contains id:", str(d.id) in d.artifacts_url)
            if d.head_sha != head_sha:
                log.warning("Skipping workflow %s, head sha does not match", d.id)
                continue
            response = await client.get(
                d.artifacts_url,
                headers=AUTH.header,
            )
            data2 = response.json()
            log.info(
                "x-ratelimit-remaining:", response.headers["X-RateLimit-Remaining"]
            )
            log.debug(
                "Found Artifacts %s on page %s (pr %s)",
                str(len(data2["artifacts"])),
                str(i),
                str(number),
            )

            for artifact in data2["artifacts"]:
                log.info("Artifact: %s", artifact["name"])
                if "pytest" in artifact["name"]:
                    log.warning(
                        "Found pytest in name for %s in workflow %s, workflod id: %s",
                        artifact["name"],
                        d.artifacts_url,
                        d.id,
                    )
                    acc.append(artifact["archive_download_url"])

        log.info("Found %s artifacts for PR %s with pytest in name", len(acc), number)

    return list(set(acc))


pkl = Path("./.cache.pkl.db")
if pkl.exists():
    log.warning("USING SHELVE")
    CACHE = shelve.open(".cache.pkl")  # type: ignore
    SYNC = True
else:
    log.debug("NOT USING SHELVE", pkl, "does not extis")
    CACHE = {}  # type: ignore
    SYNC = False


@app.route("/api/gh/<org>/<repo>/pull/<number>")
async def api_pull(org: str, repo: str, number: str):
    """
    Server sent event that should finally yield the json data for the data of
    the relevant PR


    """
    assert org.isalnum()
    assert repo.isalnum()
    assert number.isnumeric()

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
        pr = PullRequest.from_json(pr_data)
        head = pr.head

        wrs: List[WorkflowRun] = await collect_most_recent_workflow_runs(
            org, repo, head.ref, head.sha
        )

        log.warning("Looking for Artifacts...")
        yield ServerSentEvent(
            json.dumps({"info": "Looking for GH artifacts..."})
        ).encode()
        log.debug("Workflow runs id: %r", [(w.id, w.head_sha) for w in wrs])

        for w in wrs:
            await collect_artifact_metadata(org, repo, int(number), RunId(str(w.id)))
        acc = await list_artifacts_urls_to_download(wrs, head.sha, number)
        log.debug("artefacts to download: %s", acc)

        yield ServerSentEvent(
            json.dumps({"info": f"Requesting list of artifact from GH..."})
        ).encode()

        async with httpx.AsyncClient(follow_redirects=True) as client:
            data = {}
            la = len(acc)
            for i, archive in enumerate(acc):
                log.warning(f"Requesting Content... %s ({number})", i)
                log.debug("archive %s", archive)
                if archive in CACHE:
                    log.debug("CACHE HIT")
                    content = CACHE[archive]
                else:
                    log.debug("Sending SSE")
                    yield ServerSentEvent(
                        json.dumps({"info": f"Downloading artifacts {i+1}/{la}..."})
                    ).encode()
                    log.info("Downloading artifact...")
                    zp = await client.get(archive, headers=AUTH.header)
                    log.debug("Downloaded...")
                    yield ServerSentEvent(
                        json.dumps({"info": f"Got artifacts {i+1}/{la}..."})
                    ).encode()
                    log.warning(f"Unzipping in memory... %s ({number})", i)
                    zp.raise_for_status()
                    content = zp.content
                    log.debug("PUT IN CACHE %s", archive)
                    CACHE[archive] = content
                    if SYNC:
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
                            log.warning("unhandled item %r", item)

                    del xs
                    ## keep only what's necessary
                    data[fx.filename] = {"comp": comp_test}

        yield ServerSentEvent(json.dumps({"info": "Data ready, sending..."})).encode()
        yield ServerSentEvent(json.dumps({"test_data": data, "info": "done"})).encode()
        yield ServerSentEvent(
            json.dumps({"close": True, "info": "closing connection"})
        ).encode()
        # log.warning("json serialise")
        # rz = json.dumps(data)
        # log.warning("sending... %s Mb", len(rz) / 1024 / 1024)
        # return rz

    resp = await make_response(
        gen_api_pull(org, repo, number),
        {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Transfer-Encoding": "chunked",
        },
    )
    return resp


def main():
    port = int(os.environ.get("PORT", 1357))
    log.info("Seen config port %s", port)
    prod = os.environ.get("PROD", None)
    log.info("Prod= %s", prod)
    try:
        if prod or True:
            app.run(port=port, host="0.0.0.0")
        else:
            app.run(port=port)
    except KeyboardInterrupt:
        log.info("CLOSING CACHE")
        CACHE.close()
        raise


if __name__ == "__main__":
    main()
