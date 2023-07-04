# Pytest-viewer-app

This repository is the code behind http://pytest-viewer.org/, it provide a way
to aggregate pytest-json-report file across multiple runs of GitHub action for a
given PRs and analyse/visualise the slowests test. 

You can generate those report and store then as artifact with


```
pytest ... --json-report-file=./report-${{ matrix.python-version }}-${{runner.os}}.json
...
- uses: actions/upload-artifact@v3
  with:
      name: upload pytest timing reports as json
      path: |
        ./report-*.json
```

Pytest-viewer.org will search for artifact with pytest in the name, download
them, and visualize them. 

# example

![](example.png)



# Requirements

- `docker` and `docker-compose`
- python 3.10

# Setup

## Install dependencies

```bash
pip install -r requirements.txt
```

## Initialize environment

```bash
cp .env.template .env
```

And fill in APP_ID and the key

## Connecting to the local database

```bash
docker-compose up -d

psql postgres://postgres:postgres@localhost:5438/viewer_app
```

# Migrations

For now just run `psql postgres://postgres:postgres@localhost:5438/viewer_app -f migrations/20230310_init/up.sql`

On the long run, planning to use https://ollycope.com/software/yoyo/latest/
