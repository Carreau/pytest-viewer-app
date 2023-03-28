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
