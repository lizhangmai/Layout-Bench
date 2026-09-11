"""Optional pinned upstream checkouts match their declared source bytes."""

import hashlib
import subprocess

import pytest
from helpers.catalog import CATALOGS, ROOT, assert_asset_allowed, read_catalog

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("path", CATALOGS, ids=lambda path: path.parent.name)
def test_catalog_digests_match_the_pinned_submodule(path):
    catalog, configs = read_catalog(path)
    checkout = ROOT / catalog["source_checkout"]
    if not (checkout / ".git").exists():
        pytest.skip(f"{checkout.name} submodule is not initialized")
    commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    assert catalog["source_commit"] == commit
    records = catalog["artifacts"] + [item for _, data in configs
                                      for item in data["sources"] + data.get("upstream_assets", [])]
    exclusions = {item["path"] for item in catalog.get("excluded", [])}
    # Validate every path before reading any upstream asset; hash shared records once.
    digests = {}
    for record in records:
        relative = record["path"]
        assert_asset_allowed(checkout, relative, exclusions)
        asset = checkout / relative
        assert asset.resolve() == asset.absolute(), f"Symlinked upstream asset: {relative}"
        if relative in digests:
            assert digests[relative] == record["sha256"], relative
        digests[relative] = record["sha256"]
    for relative, expected in digests.items():
        assert hashlib.sha256((checkout / relative).read_bytes()).hexdigest() == expected, relative
