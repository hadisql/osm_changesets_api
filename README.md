# OSM Changesets API

A Django REST Framework API over the [OpenStreetMap changeset replication stream](https://planet.osm.org/replication/changesets/).

A background worker continuously ingests changeset metadata (author, editor, hashtags, bounding box, edit counts…) into a database; the API then lets you **query and aggregate** those contributions: who is mapping, where, with which editor, under which campaign hashtag.

Originally based on the parsing work from [osm-monitor](https://github.com/johanmorganti/osm-monitor/tree/main).

## Architecture

```
planet.osm.org/replication/changesets          (one new sequence ≈ every minute)
        │
        ▼
manage.py ingest_changesets --follow           (ingestion worker: fetch, parse, upsert + history)
        │
        ▼
   PostgreSQL / SQLite                          (Changeset model, indexed for querying)
        │
        ▼
   /api/changesets/ + /api/stats/*              (filterable REST API, OpenAPI-documented)
        │
        ▼
   /map/                                        (live world map of contributions)
```

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate

# ingest some data (a range of replication sequences, ~1 min of OSM activity each)
python manage.py ingest_changesets --start 6201000 --end 6201010

# or follow the live stream (Ctrl+C to stop)
python manage.py ingest_changesets --follow

python manage.py runserver
```

Interactive API documentation (Swagger UI): **http://127.0.0.1:8000/api/docs/**

Live contributions map: **http://127.0.0.1:8000/map/** — every ingested changeset drawn as its bounding box (colored by editor, popup with author/comment, link to the changeset on osm.org), refreshed by polling the API. Run the `--follow` worker in parallel to see the world light up in near real time.

## Endpoints

### Query

| Endpoint | Description |
|---|---|
| `GET /api/changesets/` | Paginated list of ingested changesets |
| `GET /api/changesets/<changeset_id>/` | Full record for one changeset (incl. edit history and raw tags) |

`/api/changesets/` accepts (combinable) filters:

| Parameter | Example | Meaning |
|---|---|---|
| `user` / `uid` | `?user=jeanmapper` | By username (case-insensitive) or user id |
| `editor` | `?editor=StreetComplete` | By editing software |
| `hashtag` | `?hashtag=missingmaps` | Changesets tagged with a hashtag (leading `#` optional) |
| `bbox` | `?bbox=2.2,48.8,2.5,48.9` | Intersecting a bounding box (`min_lon,min_lat,max_lon,max_lat`) |
| `created_after` / `created_before` | `?created_after=2026-07-01T00:00:00Z` | Creation date range |
| `min_changes` / `max_changes` | `?min_changes=100` | By number of edits |
| `open` | `?open=true` | Still-open changesets |
| `comment_contains` | `?comment_contains=building` | Full-text on the changeset comment |
| `ordering` | `?ordering=-changes_count` | Sort by `created_at`, `closed_at`, `changes_count`, `comments_count` |

### Stats

All stats endpoints accept the **same filters** as `/api/changesets/`, so you can ask e.g. for the top hashtags of a single user, or the timeline inside a bounding box.

| Endpoint | Description |
|---|---|
| `GET /api/stats/summary/` | Totals: changesets, edits, unique users, date & sequence range |
| `GET /api/stats/contributors/?limit=10` | Top users by changeset count |
| `GET /api/stats/editors/?limit=10` | Top editing software (versions stripped) |
| `GET /api/stats/hashtags/?limit=10` | Top hashtags |
| `GET /api/stats/timeline/?interval=hour\|day` | Changesets & edits per time bucket |

### Legacy

| Endpoint | Description |
|---|---|
| `GET /api/sequence/<start>/<end>/` | Synchronously fetches a sequence range from planet.osm.org (max 10) and returns it |

Since this endpoint triggers downloads and database writes, it is rate-limited (30 requests/hour per client); anonymous access to the read-only endpoints is capped at 1000 requests/hour.

## Ingestion worker

```
python manage.py ingest_changesets                        # latest sequence, once
python manage.py ingest_changesets --start A --end B      # backfill a range
python manage.py ingest_changesets --follow               # run forever
    --interval 60          polling interval (seconds)
    --max-catchup 120      max sequences to catch up after a downtime
    --retention-days 7     purge changesets older than N days (keeps the DB bounded)
```

A changeset can appear in several consecutive sequences while it is open; the ingestion upserts it and keeps the previous states in the `history` field.

The OSM stream produces roughly 40–90k changesets per day, so a long-running deployment should always set `--retention-days` (the provided `Procfile` uses 7 days).

## Anomaly detection

Every ingested changeset gets a **rule-based suspicion score** (0-100) from metadata heuristics inspired by [OSMCha](https://github.com/OSMCha/osmcha): continental bounding box, very high edit count, missing comment, brand-new mapper, `review_requested` tag. Flags are stored per changeset.

A second, unsupervised layer ranks changesets by how *atypical* their metadata is, using an **Isolation Forest** (scikit-learn) retrained on the current database content:

```bash
python manage.py score_anomalies            # score changesets without a score
python manage.py score_anomalies --rescore-all
```

Both scores are queryable:

```
/api/changesets/?min_suspicion=50                  rule-based threshold
/api/changesets/?flag=huge_bbox                    a specific rule
/api/changesets/?ordering=-ml_score                most atypical first
/api/stats/suspicion/                              flag distribution overview
```

The two layers are complementary: rules are interpretable and instant; the Isolation Forest also surfaces changesets that break no rule but deviate from the population.

## Tests

```bash
python manage.py test
```

## Deployment

The `Procfile` defines a `web` process (gunicorn) and a `worker` process (`ingest_changesets --follow`). Configuration goes through environment variables (`.env` locally): `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, and `DATABASE_URL` (PostgreSQL) when `DEBUG` is off.
