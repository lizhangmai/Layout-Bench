"""Prepare the reviewed PDK view, optionally packaged as generic Agent resources."""

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from .bundles import publish_bundle
from .files import Asset

VIEW_MANIFEST = Path(__file__).with_name("sg13g2_view.json")


def prepare_pdk(source: Path, destination: Path) -> str:
    """Copy only reviewed, hash-matching files; publish the view after validation."""
    source = source.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Destination already exists: {destination}")
    manifest_bytes = VIEW_MANIFEST.read_bytes()
    manifest = json.loads(manifest_bytes)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary) / "view"
        stage.mkdir()
        for relative, expected in manifest["files"].items():
            path = source / relative
            if path.resolve(strict=True) != path or not path.is_file():
                raise ValueError(f"PDK input must be a regular, non-symlink file: {relative}")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError(f"PDK content differs from the reviewed file: {relative}")
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(0o444)
        (stage / "manifest.json").write_bytes(manifest_bytes)
        (stage / "manifest.json").chmod(0o444)
        stage.rename(destination)
    return hashlib.sha256(manifest_bytes).hexdigest()


def verify_pdk(view: Path) -> str:
    """Reject modified, missing or additional files before starting a check."""
    expected_bytes = VIEW_MANIFEST.read_bytes()
    if (view / "manifest.json").read_bytes() != expected_bytes:
        raise ValueError("PDK view does not use the reviewed manifest")
    manifest = json.loads(expected_bytes)
    actual_files = set()
    for path in view.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symlink in PDK view: {path}")
        if path.is_file():
            relative = path.relative_to(view).as_posix()
            actual_files.add(relative)
            if relative == "manifest.json":
                continue
            expected = manifest["files"].get(relative)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Unreviewed PDK view content: {relative}")
    if actual_files != set(manifest["files"]) | {"manifest.json"}:
        raise ValueError("PDK view file list is incomplete")
    return hashlib.sha256(expected_bytes).hexdigest()


def prepare_pdk_bundle(source: Path, destination: Path):
    """Keep process-specific preparation here; session execution consumes a generic bundle."""
    with tempfile.TemporaryDirectory(prefix="lb-pdk-resources-") as temporary:
        view = Path(temporary)/"view"
        digest = prepare_pdk(source, view)
        files = {p.relative_to(view).as_posix(): Asset(p.read_bytes(), "binary")
                 for p in view.rglob("*") if p.is_file()}
        files["view-manifest.json"] = files.pop("manifest.json")
        return publish_bundle(files, {"kind": "reviewed-pdk-view", "view_sha256": digest}, destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Recorded IHP-Open-PDK checkout")
    parser.add_argument("destination", type=Path, help="New directory for the PDK view")
    parser.add_argument("--bundle", action="store_true", help="Publish generic resources for main.py run")
    args = parser.parse_args()
    if args.bundle:
        print(prepare_pdk_bundle(args.source, args.destination).manifest.sha256)
    else:
        print(prepare_pdk(args.source, args.destination))
