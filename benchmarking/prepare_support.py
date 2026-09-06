"""Prepare reviewed tool support; optionally compile Verilog-A with OpenVAF."""

import argparse
import json
from pathlib import Path

from .bundles import publish_bundle
from .docker import DockerTool
from .evaluation import identifier
from .files import Asset, keys, read_file, relative


def prepare_support(source: Path, profile: Path, destination: Path, *,
                    compiler_image: str = "layout-bench-tools:local") -> str:
    source, profile = source.absolute(), profile.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Support destination exists: {destination}")
    raw = Asset(read_file(profile.parent, profile.name), "json")
    data = json.loads(raw.content)
    keys(data, {"schema_version", "source", "files"}, {"generated", "compile"}, "support profile")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported support profile schema_version")
    if not isinstance(data["files"], dict) or not data["files"]:
        raise ValueError("Support profile needs reviewed files")
    files = {"preparation.json": raw}
    for name, spec in data["files"].items():
        relative(name, "support output")
        keys(spec, {"path", "sha256", "format"}, set(), "support source")
        asset = Asset(read_file(source, spec["path"]), spec["format"])
        if asset.sha256 != spec["sha256"]:
            raise ValueError(f"Support source checksum mismatch: {spec['path']}")
        if name in files:
            raise ValueError(f"Duplicate support output: {name}")
        files[name] = asset
    for name, spec in data.get("generated", {}).items():
        relative(name, "generated support output")
        keys(spec, {"content", "format"}, set(), "generated support file")
        if name in files:
            raise ValueError(f"Duplicate support output: {name}")
        files[name] = Asset(spec["content"].encode(), spec["format"])
    builds = data.get("compile", [])
    if not isinstance(builds, list):
        raise TypeError("compile must be a list")
    outputs = set(files)
    for job in builds:
        keys(job, {"source", "output", "defines"}, set(), "OpenVAF compilation")
        relative(job["output"], "compiled support output")
        if job["source"] not in files or job["output"] in outputs:
            raise ValueError("Unknown compile source or duplicate output")
        if not isinstance(job["defines"], list):
            raise TypeError("Compiler defines must be a list")
        for define in job["defines"]:
            # Preprocessor names may start with underscores, unlike job IDs.
            identifier(define.lstrip("_"))
        outputs.add(job["output"])
    provenance = {"profile_sha256": raw.sha256, "source": data["source"], "compilations": []}
    if builds:
        compiler = DockerTool(compiler_image, ["openvaf", "--version"], 180)
        provenance["compiler"] = compiler.identity
        for index, job in enumerate(builds):
            command = ["openvaf", "--target_cpu", "generic", *[f"-D{x}" for x in job["defines"]],
                       "-o", "compiled.osdi", job["source"]]
            result = compiler.run(command, files, {"compiled.osdi": "osdi"})
            if result.reason or result.returncode != 0:
                # Failed builds remain inspectable, without publishing a usable bundle.
                diagnostics = destination.with_name(destination.name + ".failed")
                publish_bundle({"profile.json": raw, **{f"logs/{k}": a for k, a in result.evidence.items()}},
                               {"compiler": compiler.identity, "reason": result.reason}, diagnostics)
                raise ValueError(f"OpenVAF compilation failed; diagnostics: {diagnostics}")
            files[job["output"]] = result.files["compiled.osdi"]
            for name, asset in result.evidence.items():
                files[f"compilation/{index}/{name}"] = asset
            provenance["compilations"].append({"command": command, "output": job["output"]})
    return publish_bundle(files, provenance, destination).manifest.sha256


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("profile", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--compiler-image", default="layout-bench-tools:local")
    args = parser.parse_args()
    print(prepare_support(args.source, args.profile, args.destination, compiler_image=args.compiler_image))
