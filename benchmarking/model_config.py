"""Frozen offline CLI configuration; model-provider settings are adapter-owned."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .evaluation import number
from .files import Asset, keys, read_file, relative, text


@dataclass(frozen=True)
class RunConfig:
    id: str
    image: str
    command: tuple[str, ...]
    wall_seconds: float
    memory_mb: int
    cpus: float
    pids: int
    workspace_mb: int
    files: dict[str, Asset]
    environment: dict[str, str]
    source: Asset


def load_run_config(path: Path) -> RunConfig:
    path = path.absolute()
    source = Asset(read_file(path.parent, path.name), "toml")
    data = tomllib.loads(source.content.decode())
    keys(data, {"schema_version", "id", "image", "wall_seconds", "memory_mb",
                "cpus", "pids", "workspace_mb"}, {"files", "environment", "command", "adapter"}, "run configuration")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported run configuration version")
    for field in ("id", "image"):
        text(data[field], field)
    files = {}
    if "adapter" in data:
        if data["adapter"] != "codex" or "command" in data:
            raise ValueError("Use adapter=codex or an explicit command")
        files["codex_cli.py"] = Asset(Path(__file__).with_name("codex_cli.py").read_bytes(), "python")
        data["command"] = ["python", "/agent/codex_cli.py"]
    if not isinstance(data.get("command"), list) or not data["command"]:
        raise ValueError("command must be a nonempty argument list")
    for argument in data["command"]:
        text(argument, "command argument")
    for field in ("wall_seconds", "cpus"):
        if number(data[field]) <= 0:
            raise ValueError(f"{field} must be positive")
    for field in ("memory_mb", "pids", "workspace_mb"):
        if type(data[field]) is not int or data[field] <= 0:
            raise ValueError(f"{field} must be a positive integer")
    for entry in data.get("files", []):
        keys(entry, {"path", "target", "sha256"}, set(), "CLI file")
        target = relative(entry["target"], "CLI file target")
        if any(target == p or target.startswith(p + "/") or p.startswith(target + "/") for p in files):
            raise ValueError("Overlapping CLI file targets")
        asset = Asset(read_file(path.parent, entry["path"]), "binary")
        if asset.sha256 != entry["sha256"]:
            raise ValueError("CLI file checksum mismatch")
        files[target] = asset
    environment = data.get("environment", {})
    if not isinstance(environment, dict):
        raise TypeError("environment must be a table of public, non-secret settings")
    for key, value in environment.items():
        if not key.isidentifier():
            raise ValueError("Invalid environment variable name")
        text(value, "public environment setting")
    return RunConfig(data["id"], data["image"], tuple(data["command"]), number(data["wall_seconds"]),
                     data["memory_mb"], number(data["cpus"]), data["pids"], data["workspace_mb"],
                     files, environment, source)
