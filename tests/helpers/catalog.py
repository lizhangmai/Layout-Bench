"""Read declared public catalog metadata without walking upstream assets."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOGS = sorted((ROOT / "tasks").glob("*/*/catalog.toml"))


def read_catalog(path):
    catalog = tomllib.loads(path.read_text())
    configs = [(path.parent / item["config_path"],
                tomllib.loads((path.parent / item["config_path"]).read_text()))
               for item in catalog["cases"]]
    return catalog, configs


def assert_asset_allowed(checkout, path, exclusions):
    relative = Path(path)
    assert not relative.is_absolute() and ".." not in relative.parts, path
    # These exclusions are an access policy, independent of catalog contents.
    protected = {"modules/module_0_foundations/PEX_Demo", "utils/PEX_Demo"}
    excluded = set(exclusions)
    if Path(checkout).name == "IHP-AnalogAcademy":
        excluded |= protected
    assert not any(relative.is_relative_to(prefix) for prefix in excluded), path
