"""Generate the public extraction fixtures with a verified primitive view."""

import argparse
import json
from pathlib import Path

from benchmarking.docker import DockerTool
from benchmarking.environment import verify_pdk
from benchmarking.files import Asset

EXAMPLES = Path(__file__).resolve().parent


def generate_fixtures(view: Path, destination: Path, *, suite: str = "extraction") -> dict[str, Asset]:
    if suite not in {"extraction", "checks"}:
        raise ValueError("Unknown fixture suite")
    view_digest = verify_pdk(view)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    tool = DockerTool("layout-bench-extractor:local", ["magic", "--version"], 60)
    primitive_files = {"pdk/" + p.relative_to(view).as_posix(): Asset(p.read_bytes(), "binary")
                       for p in view.rglob("*") if p.is_file()}
    environment = {"KLAYOUT": "1", "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": "/workspace/pdk/ihp-sg13g2/libs.tech/klayout/python:"
                                 "/workspace/pdk/ihp-sg13g2/libs.tech/klayout/python/pycell4klayout-api/source/python"}
    outputs, records = {}, []
    destination.mkdir(parents=True)
    cases = (
        ("plate20", "make_plate.py", ["--width", "20", "--height", "10"]),
        ("plate40", "make_plate.py", ["--width", "40", "--height", "10"]),
        ("switch10", "make_switch.py", ["--plate", "10"]),
        ("switch100", "make_switch.py", ["--plate", "100"]),
    ) if suite == "extraction" else (
        ("valid", "make_checked_switch.py", []),
        ("slow", "make_checked_switch.py", ["--length", "2000"]),
        *[(fault, "make_checked_switch.py", ["--fault", fault])
          for fault in ("short", "open", "parameter", "pin", "drc", "empty")],
    )
    for name, script, args in cases:
        source = Asset((EXAMPLES / script).read_bytes(), "python")
        files = {script: source, **(primitive_files if script != "make_plate.py" else {})}
        command = ["python", script, "fixture.gds", *args]
        result = tool.run(command, files, {"fixture.gds": "gds"}, environment=environment)
        (destination / f"{name}.log").write_bytes(result.evidence["console"].content)
        if result.reason:
            raise ValueError(f"Fixture generation failed: {result.reason}; see {destination}")
        outputs[name] = result.files["fixture.gds"]
        (destination / f"{name}.gds").write_bytes(outputs[name].content)
        records.append({"name": name, "command": command, "source_sha256": source.sha256,
                        "output": outputs[name].identity()})
    (destination / "generation.json").write_text(json.dumps(
        {"tool": tool.identity, "primitive_view_sha256": view_digest, "fixtures": records}, indent=2) + "\n")
    return outputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("view", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--suite", choices=["extraction", "checks"], default="extraction")
    args = parser.parse_args()
    generate_fixtures(args.view, args.destination, suite=args.suite)
