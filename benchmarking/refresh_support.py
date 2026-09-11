"""Refresh support manifest or circuit case digests from a clean pinned upstream checkout."""

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import tomli_w

from .files import Asset, keys, read_file


def _git(source: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def refresh(source: Path, manifest: Path, profile: str | None = None) -> dict:
    """Rewrite the manifest's commit and file digests from the checkout; return the changes."""
    source = source.absolute()
    manifest = manifest.absolute()
    data = tomllib.loads(manifest.read_bytes().decode())
    if data.get("kind") == "layout_case":
        if profile is not None:
            raise ValueError("Case configurations do not declare support profiles")
        return _refresh_case(source, manifest, data)
    keys(data, {"schema_version", "source", "profiles"}, set(), "support manifest")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported support manifest schema_version")
    if profile is not None and profile not in data["profiles"]:
        raise ValueError(f"Unknown support profile: {profile}")
    commit = _git(source, "rev-parse", "HEAD")
    dirty = _git(source, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise ValueError(f"Upstream checkout has uncommitted changes:\n{dirty}")
    previous = data["source"].get("commit")
    data["source"]["commit"] = commit
    updated = []
    names = [profile] if profile else list(data["profiles"])
    for name in names:
        for file, spec in data["profiles"][name]["files"].items():
            keys(spec, {"path", "sha256", "format"}, set(), "support source")
            asset = Asset(read_file(source, spec["path"]), spec["format"])
            if asset.sha256 != spec["sha256"]:
                spec["sha256"] = asset.sha256
                updated.append(f"{name}:{file}")
    manifest.write_text(tomli_w.dumps(data))
    return {"commit": (previous, commit), "digests": updated}


def _replace_entry_digest(text: str, path: str, old: str, new: str) -> str:
    """Rewrite one entry's digest in place, keeping the case file's comments.

    The same upstream path may appear in more than one section, so anchor on
    the entry whose stored digest still matches the stale value.
    """
    for anchor in (m.end() for m in re.finditer(re.escape(f'path = "{path}"'), text)):
        block_end = text.find("\n[", anchor)
        block = text[anchor:block_end if block_end > 0 else len(text)]
        match = re.search(r'sha256 = "([0-9a-f]{64})"', block)
        if match is not None and match.group(1) == old:
            start = anchor + match.start()
            return text[:start] + f'sha256 = "{new}"' + text[anchor + match.end():]
    raise ValueError(f"Cannot locate digest for case entry: {path}")


def _refresh_case(source: Path, manifest: Path, data: dict) -> dict:
    """Refresh a circuit case's commit and source digests, preserving its formatting."""
    commit = _git(source, "rev-parse", "HEAD")
    dirty = _git(source, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise ValueError(f"Upstream checkout has uncommitted changes:\n{dirty}")
    text = manifest.read_text()
    previous = data["origin"]["commit"]
    if previous != commit:
        anchor = text.find("[origin]")
        if anchor < 0:
            raise ValueError("Cannot locate case origin")
        match = re.search(r'commit = "([0-9a-f]{40})"', text[anchor:])
        if match is None or match.group(1) != previous:
            raise ValueError("Cannot locate case origin commit")
        start = anchor + match.start()
        text = text[:start] + f'commit = "{commit}"' + text[anchor + match.end():]
    updated = []
    sections = [(entry, source) for entry in data.get("sources", [])]
    sections += [(entry, source) for entry in data.get("upstream_assets", [])]
    export = data.get("source_export", {})
    for entry in export.get("files", []):
        if entry["checkout"] == "pdk":
            continue  # Owned by the referenced pdk.toml profile; refresh that manifest.
        base = source if (source / entry["path"]).is_file() else manifest.parent
        sections.append((entry, base))
    for entry, base in sections:
        digest = Asset(read_file(base, entry["path"]), entry.get("format", "text")).sha256
        if digest != entry["sha256"]:
            text = _replace_entry_digest(text, entry["path"], entry["sha256"], digest)
            updated.append(entry["path"])
    manifest.write_text(text)
    return {"commit": (previous, commit), "digests": updated}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Pinned upstream checkout")
    parser.add_argument("manifests", type=str, nargs="+",
                        help="Manifest path, optionally with #profile to refresh one profile")
    args = parser.parse_args()
    try:
        for spec in args.manifests:
            path, _, name = spec.partition("#")
            changes = refresh(args.source, Path(path), name or None)
            old, new = (value[:12] if value else "none" for value in changes["commit"])
            print(f"{spec}: commit {old} -> {new}, {len(changes['digests'])} digests refreshed")
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        print(f"Support refresh error: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
