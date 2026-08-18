#!/usr/bin/env python3
"""Post Apify YC dataset records to the Void Radar backend."""

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
        "dataset_path",
        type=Path,
        help="Apify dataset directory or a single exported JSON file.",
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

    records = read_dataset(args.dataset_path)
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


def read_dataset(dataset_path: Path) -> list[dict]:
    if dataset_path.is_dir():
        return read_dataset_dir(dataset_path)

    if dataset_path.is_file():
        return read_dataset_file(dataset_path)

    raise FileNotFoundError(f"Dataset path not found: {dataset_path}")


def read_dataset_dir(dataset_dir: Path) -> list[dict]:
    records: list[dict] = []
    for path in sorted(dataset_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        records.extend(normalize_export_payload(payload, source_path=path))
    return records


def read_dataset_file(dataset_file: Path) -> list[dict]:
    with dataset_file.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return normalize_export_payload(payload, source_path=dataset_file)


def normalize_export_payload(payload: object, source_path: Path) -> list[dict]:
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        records = payload["items"]
    elif isinstance(payload, dict):
        records = [payload]
    else:
        raise ValueError(f"Unsupported dataset payload in {source_path}")

    invalid_items = [
        index for index, record in enumerate(records) if not isinstance(record, dict)
    ]
    if invalid_items:
        raise ValueError(
            f"Dataset payload in {source_path} contains non-object records "
            f"at indexes {invalid_items[:5]}"
        )

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
