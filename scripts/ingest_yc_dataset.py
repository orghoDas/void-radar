#!/usr/bin/env python3
"""Post local Apify YC dataset records to the Void Radar backend."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_ENDPOINT = "http://localhost:8000/ingestion/y-combinator/source-records"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dataset_dir",
        type=Path,
        help="Directory containing Apify dataset JSON files.",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"Backend ingestion endpoint. Default: {DEFAULT_ENDPOINT}",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Records per POST request.",
    )
    args = parser.parse_args()

    records = read_dataset(args.dataset_dir)
    if not records:
        print("No records found.", file=sys.stderr)
        return 1

    totals = {"received": 0, "inserted": 0, "duplicates": 0}
    for batch in chunked(records, args.batch_size):
        result = post_batch(args.endpoint, batch)
        for key in totals:
            totals[key] += int(result.get(key, 0))

    print(json.dumps(totals, indent=2, sort_keys=True))
    return 0


def read_dataset(dataset_dir: Path) -> list[dict]:
    records: list[dict] = []
    for path in sorted(dataset_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as file:
            records.append(json.load(file))
    return records


def post_batch(endpoint: str, records: list[dict]) -> dict:
    body = json.dumps({"records": records}).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8")
        raise RuntimeError(f"Ingestion failed with {error.code}: {detail}") from error


def chunked(records: list[dict], size: int) -> list[list[dict]]:
    return [records[index : index + size] for index in range(0, len(records), size)]


if __name__ == "__main__":
    raise SystemExit(main())

