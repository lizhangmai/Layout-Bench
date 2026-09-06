"""Frozen tool support files, prepared from an explicit reviewed source list."""

import json
from dataclasses import dataclass
from pathlib import Path

from .files import Asset, keys, read_file, relative


@dataclass(frozen=True)
class Bundle:
    files: tuple[tuple[str, Asset], ...]
    manifest: Asset

    def mounted_files(self) -> dict[str, Asset]:
        return {f"support/{name}": asset for name, asset in self.files}

    def evidence(self) -> dict[str, Asset]:
        return {"support_manifest": self.manifest,
                **{f"support:{name}": asset for name, asset in self.files}}


def load_bundle(root: Path) -> Bundle:
    root = root.absolute()
    manifest = Asset(read_file(root, "manifest.json"), "json")
    data = json.loads(manifest.content)
    keys(data, {"schema_version", "files", "provenance"}, set(), "support bundle")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported support bundle schema_version")
    if not isinstance(data["files"], dict) or not data["files"]:
        raise ValueError("Support bundle needs a nonempty file list")
    files = []
    for name, identity in data["files"].items():
        relative(name, "support path")
        if name == "manifest.json":
            raise ValueError("manifest.json is reserved")
        keys(identity, {"sha256", "format", "bytes"}, set(), "support identity")
        asset = Asset(read_file(root, name), identity["format"])
        if asset.identity() != identity:
            raise ValueError(f"Support checksum mismatch: {name}")
        files.append((name, asset))
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symlink in support bundle: {path}")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != set(data["files"]) | {"manifest.json"}:
        raise ValueError("Support bundle contains undeclared files")
    return Bundle(tuple(files), manifest)


def publish_bundle(files: dict[str, Asset], provenance: dict, destination: Path) -> Bundle:
    """Publish new preparation output, never overwrite an existing bundle."""
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Bundle destination exists: {destination}")
    for name in files:
        relative(name, "support path")
        if name == "manifest.json":
            raise ValueError("manifest.json is reserved")
    manifest = {"schema_version": 1, "files": {k: a.identity() for k, a in sorted(files.items())},
                "provenance": provenance}
    raw = json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    destination.mkdir(parents=True)
    for name, asset in {**files, "manifest.json": Asset(raw, "json")}.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(asset.content)
        path.chmod(0o444)
    return load_bundle(destination)
