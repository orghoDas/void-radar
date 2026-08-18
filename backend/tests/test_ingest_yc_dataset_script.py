import json

import pytest

from scripts.ingest_yc_dataset import read_dataset


def test_read_dataset_from_local_apify_directory(tmp_path) -> None:
    first = tmp_path / "000000001.json"
    second = tmp_path / "000000002.json"
    first.write_text(json.dumps({"company_name": "First"}), encoding="utf-8")
    second.write_text(json.dumps({"company_name": "Second"}), encoding="utf-8")

    records = read_dataset(tmp_path)

    assert records == [
        {"company_name": "First"},
        {"company_name": "Second"},
    ]


def test_read_dataset_from_apify_json_array_export(tmp_path) -> None:
    export = tmp_path / "dataset.json"
    export.write_text(
        json.dumps([{"company_name": "First"}, {"company_name": "Second"}]),
        encoding="utf-8",
    )

    records = read_dataset(export)

    assert records == [
        {"company_name": "First"},
        {"company_name": "Second"},
    ]


def test_read_dataset_from_wrapped_items_export(tmp_path) -> None:
    export = tmp_path / "dataset.json"
    export.write_text(
        json.dumps({"items": [{"company_name": "First"}]}),
        encoding="utf-8",
    )

    records = read_dataset(export)

    assert records == [{"company_name": "First"}]


def test_read_dataset_rejects_non_object_records(tmp_path) -> None:
    export = tmp_path / "dataset.json"
    export.write_text(json.dumps(["bad"]), encoding="utf-8")

    with pytest.raises(ValueError, match="non-object records"):
        read_dataset(export)

