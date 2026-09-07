import hashlib
import subprocess
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "tasks/TO_Apr2025/catalog.toml"


def _catalog():
    return tomllib.loads(CATALOG.read_text())


def test_catalog_records_the_incremental_intake():
    catalog = _catalog()
    assert catalog["circuit_source_count"] == len(catalog["circuits"]) == 2
    assert catalog["artifact_count"] == len(catalog["artifacts"]) == 20
    assert {item["id"] for item in catalog["circuits"]} == {
        "TO_Apr2025.Mixer5GHz", "TO_Apr2025.40_GHZ_LOW_NOISE_TIA",
    }
    assert {item["status"] for item in catalog["circuits"]} == {"candidate", "source-only"}
    for circuit in catalog["circuits"]:
        intake = CATALOG.parent / circuit["intake_path"]
        assert intake.is_file()
        assert intake.read_text().startswith("schema_version = 1")


def test_catalog_digests_match_the_pinned_submodule():
    to_apr2025 = ROOT / "third_party/TO_Apr2025"
    if not (to_apr2025 / ".git").exists():
        pytest.skip("TO_Apr2025 submodule is not initialized")
    catalog = _catalog()
    commit = subprocess.check_output(
        ["git", "-C", str(to_apr2025), "rev-parse", "HEAD"], text=True,
    ).strip()
    assert catalog["source_commit"] == commit
    for circuit in catalog["circuits"]:
        source = to_apr2025 / circuit["source_path"]
        assert source.stat().st_size == circuit["source_bytes"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == circuit["source_sha256"]
    for artifact in catalog["artifacts"]:
        path = to_apr2025 / artifact["path"]
        assert path.stat().st_size == artifact["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
