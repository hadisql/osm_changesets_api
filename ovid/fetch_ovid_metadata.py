"""Fetch OSM changeset metadata for the Ovid labelled dataset.

Reads ovid_labels.tsv (changeset id + vandalism label), fetches metadata for
every changeset from the OSM API in batches of 100, and writes one JSON object
per line to ovid_changesets.jsonl (the label is merged in as "vandalism").

The script is resumable: already-fetched changeset ids are skipped on restart.

Usage:
    python ovid/fetch_ovid_metadata.py
"""

import json
import sys
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
LABELS_PATH = BASE_DIR / "labels" / "ovid_labels.tsv"
OUTPUT_PATH = BASE_DIR / "ovid_changesets.jsonl"
MISSING_PATH = BASE_DIR / "ovid_missing_ids.txt"

API_URL = "https://api.openstreetmap.org/api/0.6/changesets.json"
BATCH_SIZE = 100
SLEEP_BETWEEN_CALLS = 1.0
MAX_RETRIES = 3
TIMEOUT = 60
USER_AGENT = "osm-django-api-eval/1.0 (portfolio anomaly-detection benchmark)"


def load_labels():
    labels = {}
    with open(LABELS_PATH) as f:
        header = f.readline().strip().split("\t")
        assert header == ["changeset", "label"], f"Unexpected header: {header}"
        for line in f:
            changeset_id, label = line.strip().split("\t")
            labels[int(changeset_id)] = label.lower() == "true"
    return labels


def already_fetched():
    done = set()
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    continue
    if MISSING_PATH.exists():
        with open(MISSING_PATH) as f:
            done.update(int(line.strip()) for line in f if line.strip())
    return done


def fetch_batch(session, ids):
    params = {"changesets": ",".join(str(i) for i in ids)}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(API_URL, params=params, timeout=TIMEOUT)
            if resp.status_code == 200:
                return resp.json().get("changesets", [])
            print(f"  HTTP {resp.status_code} (attempt {attempt}): {resp.text[:200]}")
        except requests.RequestException as exc:
            print(f"  request failed (attempt {attempt}): {exc}")
        time.sleep(5 * attempt)
    return None


def main():
    labels = load_labels()
    done = already_fetched()
    todo = sorted(i for i in labels if i not in done)
    print(f"{len(labels)} labelled changesets, {len(done)} already fetched, {len(todo)} to go")
    if not todo:
        print("Nothing to do.")
        return

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    with open(OUTPUT_PATH, "a") as out, open(MISSING_PATH, "a") as missing:
        for start in range(0, len(todo), BATCH_SIZE):
            batch = todo[start:start + BATCH_SIZE]
            results = fetch_batch(session, batch)
            if results is None:
                print(f"Giving up on batch starting at {batch[0]} after {MAX_RETRIES} retries")
                sys.exit(1)

            returned_ids = set()
            for cs in results:
                cs["vandalism"] = labels[cs["id"]]
                out.write(json.dumps(cs) + "\n")
                returned_ids.add(cs["id"])

            # Changesets the API did not return (redacted/deleted): record so
            # we do not re-request them forever.
            for i in batch:
                if i not in returned_ids:
                    missing.write(f"{i}\n")

            out.flush()
            missing.flush()

            fetched_total = start + len(batch)
            print(f"[{fetched_total}/{len(todo)}] batch ok: {len(returned_ids)} returned, "
                  f"{len(batch) - len(returned_ids)} missing")
            time.sleep(SLEEP_BETWEEN_CALLS)

    print("Done.")


if __name__ == "__main__":
    main()
