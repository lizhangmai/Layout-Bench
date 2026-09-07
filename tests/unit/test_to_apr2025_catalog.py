import hashlib
import subprocess
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "tasks/TO_Apr2025/catalog.toml"


def _configs(catalog):
    return {
        item["id"]: tomllib.loads((CATALOG.parent / item["config_path"]).read_text())
        for item in catalog["cases"]
    }


def test_catalog_has_one_unified_config_per_case():
    catalog = tomllib.loads(CATALOG.read_text())
    assert catalog["schema_version"] == 3
    assert catalog["source_count"] == 4
    assert catalog["case_count"] == len(catalog["cases"]) == 4
    assert catalog["artifact_count"] == len(catalog["artifacts"]) == 53

    config_paths = [item["config_path"] for item in catalog["cases"]]
    assert len(config_paths) == len(set(config_paths))
    assert all(Path(path).parent == Path("cases") for path in config_paths)
    assert all(Path(path).stem == item["id"].removeprefix("TO_Apr2025.")
               for path, item in zip(config_paths, catalog["cases"], strict=True))
    assert {path.name for path in (CATALOG.parent / "cases").glob("*.toml")} == {
        Path(path).name for path in config_paths
    }
    expected_tomls = {Path("catalog.toml")} | {Path(path) for path in config_paths}
    assert {path.relative_to(CATALOG.parent) for path in CATALOG.parent.rglob("*.toml")} == expected_tomls

    configs = _configs(catalog)
    assert set(configs) == {item["id"] for item in catalog["cases"]}
    assert set(configs) == {
        "TO_Apr2025.40_GHZ_LOW_NOISE_TIA",
        "TO_Apr2025.DC_to_130_GHz_TIA.design_1",
        "TO_Apr2025.160GHz_LNA",
        "TO_Apr2025.97_GHZ_LINEAR_TIA",
    }
    assert all(data["kind"] == "layout_case" and data["schema_version"] == 2
               for data in configs.values())
    assert all(data["status"] == "candidate" for data in configs.values())
    assert all(data.get("screening", {}).get("decision") == "include"
               for data in configs.values())
    assert all(not Path(path).name in {"intake.toml", "task.toml", "source.toml"}
               for path in config_paths)

    sources = [source for data in configs.values() for source in data["sources"]]
    assert len(sources) == catalog["source_count"]
    assert len({source["id"] for source in sources}) == len(sources)
    assert len({source["path"] for source in sources}) == len(sources)
    assert all(source["path"].endswith(".sch") for source in sources)

    upstream_assets = [asset for data in configs.values()
                       for asset in data.get("upstream_assets", [])]
    assert len({asset["id"] for asset in upstream_assets}) == len(upstream_assets)
    assert all("bytes" not in source for source in sources)
    assert all("bytes" not in asset for asset in upstream_assets)
    assert all("bytes" not in artifact for artifact in catalog["artifacts"])
    assert not list(CATALOG.parent.glob("**/intake.toml"))
    assert not list(CATALOG.parent.glob("**/task.toml"))
    assert not list(CATALOG.parent.glob("**/source.toml"))
    assert not (CATALOG.parent / "qualified").exists()


def test_catalog_digests_match_the_pinned_submodule():
    to_apr2025 = ROOT / "third_party/TO_Apr2025"
    if not (to_apr2025 / ".git").exists():
        pytest.skip("TO_Apr2025 submodule is not initialized")
    catalog = tomllib.loads(CATALOG.read_text())
    commit = subprocess.check_output(
        ["git", "-C", str(to_apr2025), "rev-parse", "HEAD"], text=True,
    ).strip()
    assert catalog["source_commit"] == commit
    configs = _configs(catalog)
    sources = [source for data in configs.values() for source in data["sources"]]
    expected_sources = {source["path"] for source in sources}
    expected_artifacts = {
        asset["path"] for data in configs.values() for asset in data.get("upstream_assets", [])
    }
    assert {source["path"] for source in sources} == expected_sources
    assert {item["path"] for item in catalog["artifacts"]} == expected_artifacts

    for source in sources:
        path = to_apr2025 / source["path"]
        assert path.is_file(), source["path"]
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == source["sha256"]

    for item in catalog["artifacts"]:
        path = to_apr2025 / item["path"]
        assert path.is_file(), item["path"]
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == item["sha256"]

    for data in configs.values():
        checkout = ROOT / data["origin"]["checkout"]
        for asset in data.get("upstream_assets", []):
            path = checkout / asset["path"]
            assert path.is_file(), asset["path"]
            content = path.read_bytes()
            assert hashlib.sha256(content).hexdigest() == asset["sha256"]
