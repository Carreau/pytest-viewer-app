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
