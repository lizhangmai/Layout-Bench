"""Snapshot the framework implementation without collecting tasks or local secrets."""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from .files import Asset, read_file

ROOT = Path(__file__).resolve().parents[1]


def json_asset(value):
    return Asset((json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode(), "json")


def framework_files(root=ROOT):
    names = {name for name in ("main.py", "Dockerfile", "pyproject.toml", "uv.lock") if (root / name).exists()}
    names.update(p.relative_to(root).as_posix() for p in (root / "benchmarking").rglob("*")
                 if p.is_file() and p.suffix in {".py", ".json", ".yaml"})
    return {name: Asset(read_file(root, name), "binary") for name in sorted(names)}


def snapshot_framework(archive, root=ROOT):
    files = framework_files(root)
    identity = json_asset({name: asset.identity() for name, asset in files.items()}).sha256
    git = {"commit": None, "status": None}
    try:
        checkout = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=root,
                                           text=True, stderr=subprocess.DEVNULL, timeout=10).strip()
        if Path(checkout).resolve() != root.resolve():
            raise ValueError("Installed package is not the enclosing checkout")
        git["commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=10).strip()
        git["status"] = subprocess.check_output(
            ["git", "status", "--porcelain=v1", "--untracked-files=all", "--", ".", ":(exclude)third_party"],
            cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass  # Installed source distributions still have a complete content identity.
    return {"sha256": identity, "git": git,
            "files": {name: archive(asset) for name, asset in files.items()}}


def verify_framework(snapshot, root=ROOT):
    actual = json_asset({name: asset.identity() for name, asset in framework_files(root).items()}).sha256
    if actual != snapshot["sha256"]:
        raise ValueError("Framework source changed after execution conditions were frozen")


def host_identity(*, concurrency=1):
    return {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
            "python": sys.version, "cpu_count": os.cpu_count(), "uid": os.getuid(), "gid": os.getgid(),
            "concurrency": concurrency, "working_directory": str(Path.cwd())}
