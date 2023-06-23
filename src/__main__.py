import typer
import requests
import os
from pathlib import Path

app = typer.Typer()


BASE_URL = "https://..."

path_tpl = "/collect_artifact_metadata/{slug}/{pull_number}/{run_id}"


@app.command()
def info():
    print("This is debug informations the pytest-viewer-cli in gh action")
    print(f"{os.environ.get('GITHUB_REPOSITORY')=}")
    print(f"{os.environ.get('GITHUB_RUN_ID')=}")
    print(f"{os.environ.get('GITHUB_REF')=}")
    print(f"{os.environ.get('GITHUB_EVENT_PATH')=}")

    slug = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    ref = os.environ.get("GITHUB_REF")
    evp = os.environ.get("GITHUB_EVENT_PATH")
    if evp is not None:
        print(Path(evp).read_text())
    if slug is not None and run_id is not None and ref.startswith("refs/pull/"):
        # ref= 'refs/pull/{pr_number}/merge
        assert run_id.isdigit()
        _ref, _pull, number, _merge = ref.split("/")
        assert number.isdigit()
        print(
            "Should ping:",
            BASE_URL + path_tpl.format(slug=slug, pull_number=number, run_id=run_id),
        )
    else:
        print("it does not seem we are in a github pull_request run...")


@app.command()
def ping(name: str, formal: bool = False):
    print(f"Bye {name}!")


@app.command()
def serve():
    from .app import main

    main()


if __name__ == "__main__":
    app()
