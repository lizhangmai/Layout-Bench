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


def test_catalog_records_named_circuit_configs():
    catalog = _catalog()
    assert catalog["schema_version"] == 2
    assert catalog["circuit_source_count"] == len(catalog["circuits"]) == 3
    assert catalog["artifact_count"] == len(catalog["artifacts"]) == 32
    configs = [tomllib.loads((CATALOG.parent / item["config_path"]).read_text())
               for item in catalog["circuits"]]
    assert {data["id"] for data in configs} == {
        "TO_Apr2025.Mixer5GHz", "TO_Apr2025.40_GHZ_LOW_NOISE_TIA",
        "TO_Apr2025.DC_to_130_GHz_TIA.design_1",
    }
    assert {data["status"] for data in configs} == {"candidate", "source-only"}
    for circuit, data in zip(catalog["circuits"], configs):
        config = CATALOG.parent / circuit["config_path"]
        assert config.is_file()
        assert config.stem == data["source_path"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
    assert not list(CATALOG.parent.rglob("intake.toml"))


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
        config = CATALOG.parent / circuit["config_path"]
        data = tomllib.loads(config.read_text())
        source = to_apr2025 / data["source_path"]
        assert source.stat().st_size == data["source_bytes"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == data["source_sha256"]
    for artifact in catalog["artifacts"]:
        path = to_apr2025 / artifact["path"]
        assert path.stat().st_size == artifact["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
