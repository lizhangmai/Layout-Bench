"""Catalogs agree with case declarations without freezing today's inventory."""

import pytest
from helpers.catalog import CATALOGS, assert_asset_allowed, read_catalog

from benchmarking.tasks import _validate_case, load_task

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("path", CATALOGS, ids=lambda path: path.parent.name)
def test_catalog_and_case_declarations_are_consistent(path):
    catalog, configs = read_catalog(path)
    assert catalog["schema_version"] == 3
    assert catalog["cases"], "A published catalog must contain cases"
    assert len({item["id"] for item in catalog["cases"]}) == len(configs)
    assert len({config for config, _ in configs}) == len(configs)
    # One circuit per directory is the public organization convention.
    assert all(config.name == "case.toml" and config.parent.parent == path.parent / "cases"
               for config, _ in configs)
    assert set((path.parent / "cases").glob("*/case.toml")) == {config for config, _ in configs}
    for entry, (config, data) in zip(catalog["cases"], configs, strict=True):
        _validate_case(data)
        assert entry["id"] == data["id"]
        assert data["origin"]["commit"] == catalog["source_commit"]
        assert data["origin"]["checkout"] == catalog["source_checkout"]
        assert data["screening"]["decision"] == "include"
        assert data["upstream_evaluation"]["basis"]
        if "task" in data:
            load_task(config)  # Checks declared input digests and plan references.

    sources = [source for _, data in configs for source in data["sources"]]
    assets = [asset for _, data in configs for asset in data.get("upstream_assets", [])]
    assert len({item["path"] for item in catalog["artifacts"]}) == len(catalog["artifacts"])
    for entries in (sources, assets):
        assert len({item["id"] for item in entries}) == len(entries)
    # Compare independent records, including digests, rather than a set to itself.
    assert {(item["path"], item["sha256"]) for item in catalog["artifacts"]} == {
        (item["path"], item["sha256"]) for item in assets
    }
    exclusions = {item["path"] for item in catalog.get("excluded", [])}
    for item in sources + assets + catalog["artifacts"]:
        assert_asset_allowed(catalog["source_checkout"], item["path"], exclusions)
