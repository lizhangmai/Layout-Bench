"""Generate the public reference using only a verified primitive view."""

import argparse
import json
from pathlib import Path

from benchmarking.docker import DockerTool
from benchmarking.environment import verify_pdk
from benchmarking.files import Asset


def generate(view: Path, destination: Path, *, n_width: str = "1u", image: str = "layout-bench-tools:local"):
    digest = verify_pdk(view)
    if destination.exists():
        raise FileExistsError(destination)
    source = Asset(Path(__file__).with_name("layout.py").read_bytes(), "python")
    files = {"layout.py": source, **{"pdk/" + p.relative_to(view).as_posix(): Asset(p.read_bytes(), "binary")
                                  for p in view.rglob("*") if p.is_file()}}
    tool = DockerTool(image, ["klayout", "-v"], 60)
    command = ["python", "layout.py", "reference.gds", "--n-width", n_width]
    result = tool.run(command, files, {"reference.gds": "gds"}, environment={
        "KLAYOUT": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": "/workspace/pdk/ihp-sg13g2/libs.tech/klayout/python:"
                      "/workspace/pdk/ihp-sg13g2/libs.tech/klayout/python/pycell4klayout-api/source/python"})
    destination.mkdir(parents=True)
    (destination / "generation.log").write_bytes(result.evidence["console"].content)
    if result.reason:
        raise ValueError(result.reason)
    (destination / "reference.gds").write_bytes(result.files["reference.gds"].content)
    (destination / "generation.json").write_text(json.dumps({"tool": tool.identity, "command": command,
        "source_sha256": source.sha256, "primitive_view_sha256": digest,
        "output": result.files["reference.gds"].identity()}, indent=2)+"\n")
    return result.files["reference.gds"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("view", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--image", default="layout-bench-tools:local")
    args = parser.parse_args()
    generate(args.view, args.destination, image=args.image)
