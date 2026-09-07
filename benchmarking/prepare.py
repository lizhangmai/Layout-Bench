"""Export a source schematic with Xschem using a reviewed file manifest.

This maintainer command never edits the exported netlist. It prepares only the
explicit source files, records their identities and runs without network access.
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
import tomllib
from pathlib import Path

from .files import keys as _keys
from .files import read_file as _read_file
from .files import relative as _relative


def export_xschem(manifest: Path, checkouts: dict[str, Path], output: Path,
                  image: str = "layout-bench-tools:local") -> None:
    manifest_bytes = manifest.read_bytes()
    spec = tomllib.loads(manifest_bytes.decode("utf-8"))
    source_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if spec.get("kind") == "layout_case":
        if not isinstance(spec.get("source_export"), dict):
            raise ValueError("Circuit case does not declare source_export")
        spec = spec["source_export"]
        source_manifest_sha256 = hashlib.sha256(
            json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    _keys(spec, {"tool", "schematic", "netlist", "files"}, set(), "source")
    if spec["tool"] != "xschem-lvs":
        raise ValueError("Only the xschem-lvs exporter is implemented")
    schematic = _relative(spec["schematic"], "source.schematic")
    netlist = _relative(spec["netlist"], "source.netlist")
    if "/" in netlist:
        raise ValueError("source.netlist must be a filename")
    if not isinstance(spec["files"], list) or not spec["files"]:
        raise ValueError("source.files must be a nonempty list")
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        source = Path(temporary) / "source"
        source.mkdir()
        records = []
        targets = set()
        for entry in spec["files"]:
            _keys(entry, {"checkout", "path", "target", "sha256"}, set(), "source.files")
            if entry["checkout"] not in checkouts:
                raise ValueError(f"Missing checkout: {entry['checkout']}")
            relative = _relative(entry["path"], "source.files.path")
            target = _relative(entry["target"], "source.files.target")
            if any(target == p or target.startswith(p + "/") or p.startswith(target + "/")
                   for p in targets):
                raise ValueError(f"Duplicate/overlapping source target: {target}")
            targets.add(target)
            checkout = checkouts[entry["checkout"]].resolve(strict=True)
            content = _read_file(checkout, relative)
            digest = hashlib.sha256(content).hexdigest()
            if digest != entry["sha256"]:
                raise ValueError(f"Source checksum mismatch: {relative}")
            destination = source / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            records.append({**entry, "commit": subprocess.check_output(
                ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True,
            ).strip()})
        if schematic not in targets:
            raise ValueError("Schematic is not in the source file manifest")
        image_id = subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True,
        ).strip()
        tcl = (
            'file mkdir /workspace/export; '
            'set XSCHEM_LIBRARY_PATH /source:$XSCHEM_SHAREDIR/xschem_library/devices; '
            'set top_is_subckt 1; set lvs_netlist 1; set spiceprefix 1'
        )
        command = ["xschem", "-i", "-x", "-q", "-r", "-s", "--tcl", tcl,
                   "--command", "xschem set format lvs_format; xschem netlist",
                   "-o", "/workspace/export", "-N", netlist, f"/source/{schematic}"]
        cid = subprocess.check_output([
            "docker", "create", "--network", "none", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--memory", "1g", "--cpus", "1",
            "--pids-limit", "64", "--mount", f"type=bind,src={source},dst=/source,readonly",
            image_id, *command,
        ], text=True).strip()
        try:
            run = subprocess.run(["docker", "start", "-a", cid], capture_output=True,
                                 text=True, timeout=60, check=True)
            code = subprocess.check_output(
                ["docker", "inspect", "--format", "{{.State.ExitCode}}", cid], text=True,
            ).strip()
            if code != "0":
                raise RuntimeError(f"Xschem failed ({code}): {run.stderr}")
            # Xschem may return success despite ERC errors. Keep the diagnostics
            # and reject known export errors, then qualify semantics separately.
            diagnostics = run.stdout + run.stderr
            if any(marker in diagnostics.lower() for marker in
                   ("error", "not found", "missing symbol", "can't read")):
                raise RuntimeError(f"Xschem export requires investigation: {diagnostics}")
            stage = Path(temporary) / "export"
            subprocess.run(["docker", "cp", f"{cid}:/workspace/export", str(stage)], check=True)
            if not (stage / netlist).is_file():
                raise RuntimeError(f"Xschem did not produce {netlist}: {diagnostics}")
            content = (stage / netlist).read_bytes()
            if not content.strip():
                raise ValueError("Xschem did not export a nonempty netlist")
            version = subprocess.check_output(
                ["docker", "run", "--rm", "--network", "none", image_id, "xschem", "--version"],
                stderr=subprocess.STDOUT, text=True, timeout=30,
            )
            provenance = {
                "exporter": "xschem-lvs", "image_id": image_id, "version": version,
                "source_manifest_sha256": source_manifest_sha256,
                "files": records, "command": command,
                "netlist": netlist, "netlist_sha256": hashlib.sha256(content).hexdigest(),
                "postprocessing": "none",
            }
            (stage / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
            (stage / "netlist.log").write_text(diagnostics)
            stage.rename(output)
        finally:
            subprocess.run(["docker", "rm", "-f", cid], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path, help="New directory for the raw export and provenance")
    parser.add_argument("--checkout", action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("--image", default="layout-bench-tools:local")
    args = parser.parse_args()
    checkouts = {}
    for entry in args.checkout:
        name, separator, path = entry.partition("=")
        if not separator or not name or not path or name in checkouts:
            parser.error("--checkout requires unique NAME=PATH entries")
        checkouts[name] = Path(path)
    export_xschem(args.manifest, checkouts, args.output, args.image)
    print(f"Raw Xschem export: {args.output}")
