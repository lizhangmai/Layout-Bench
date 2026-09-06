"""Container-only implementation. Uses KLayout's native GDS and report readers."""

import json
import math
import subprocess
from pathlib import Path

from klayout import db, rdb


def artifact(config):
    path = Path("candidate.gds")
    if path.stat().st_size > config["max_bytes"]:
        return "Candidate exceeds the published max_bytes limit"
    if path.read_bytes()[:4] != b"\x00\x06\x00\x02":
        return "Candidate is not a GDSII stream"
    layout = db.Layout()
    try:
        layout.read(str(path))
    except RuntimeError as error:
        return f"Unreadable GDS: {error}"
    if not math.isfinite(layout.dbu) or layout.dbu <= 0:
        return "Invalid GDS database unit"
    top = layout.cell(config["top_cell"])
    if top is None or top not in layout.top_cells():
        return "Specified top cell is missing or is not a top-level cell"
    # Ghost cells are unresolved hierarchy references, not empty helper cells.
    if any(layout.cell(i).is_ghost_cell() for i in top.called_cells()):
        return "Unresolved cell reference in the candidate hierarchy"
    # Region can retain text placeholders while reporting is_empty=False.
    # Positive area requires actual polygon/path geometry.
    if not any(db.Region(top.begin_shapes_rec(i)).area() > 0 for i in layout.layer_indexes()):
        return "Specified top cell has no polygon/path geometry"
    return ""


def drc(config):
    report = rdb.ReportDatabase()
    report.load("report.db")
    def all_categories(iterator):
        for category in iterator:
            yield category
            yield from all_categories(category.each_sub_category())

    categories = list(all_categories(report.each_category()))
    names = sorted(c.path() for c in categories)
    details = {"categories": names, "violations": report.num_items(),
               "by_category": {c.path(): c.num_items() for c in categories if c.num_items()}}
    if report.top_cell_name != config["top_cell"]:
        return "error", "DRC report does not describe the requested top cell", details
    if not set(config["required_categories"]) <= set(names):
        return "error", "DRC report lacks required categories from the configured rule scope", details
    if report.num_items():
        return "failed", "DRC violations found", details
    return "passed", "", details


def lvs(config):
    report = db.LayoutVsSchematic()
    report.read("report.db")
    xref = report.xref()
    if xref is None or xref.circuit_count() == 0:
        return "error", "LVS database has no completed comparison", {}
    pairs = list(xref.each_circuit_pair())
    details = {"circuits": [{"layout": p.first().name if p.first() else None,
                              "reference": p.second().name if p.second() else None,
                              "status": str(p.status())} for p in pairs]}
    # SPICE names are case insensitive; the reader canonicalizes them to uppercase.
    wanted = config["subcircuit"].upper()
    reference = report.reference.circuit_by_name(wanted)
    if reference is None or not any(reference.each_device()) and not any(reference.each_subcircuit()):
        return "error", "Authoritative reference circuit is missing or empty", details
    target = [p for p in pairs if p.first() and p.first().name.upper() == config["top_cell"].upper()
              and p.second() and p.second().name.upper() == wanted]
    if not target or any(p.status() != db.NetlistCrossReference.Match for p in pairs):
        return "failed", "LVS circuit, device, parameter or connectivity mismatch", details
    if not any(target[0].first().each_device()) and not any(target[0].first().each_subcircuit()):
        return "failed", "LVS extracted circuit is empty", details
    if not report.flag_missing_ports(reference):
        return "failed", "LVS top-level ports are missing or mislabeled", details
    return "passed", "", details


def main(config):
    error = artifact(config)
    if error:
        return "failed", error, {}
    if config["check"] == "artifact":
        return "passed", "", {}
    mode = config["check"]
    wrapper = f"check.{mode}"
    mapping = ", ".join(f'"{name}" => lvs_data.layer_name(lvs_data.layer_of({variable}.data))'
                        for name, variable in config.get("layer_names", {}).items())
    names = ('require "json"\nFile.write("layer-map.json", JSON.generate({' + mapping + '}))\n') if mode == "lvs" else ""
    Path(wrapper).write_text(f'# %include /workspace/support/{config["deck"]}\n' + names +
                            'File.write("/workspace/complete.txt", "complete\\n")\n')
    variables = {**config["variables"], "input": "/workspace/candidate.gds", "topcell": config["top_cell"],
                 "report": "/workspace/report.db", "log": "/workspace/deck.log"}
    if mode == "lvs":
        variables.update(schematic="/workspace/reference.spice", target_netlist="/workspace/extracted.spice")
    command = ["klayout", "-b", "-r", wrapper]
    command.extend(arg for k, v in variables.items() for arg in ("-rd", f"{k}={v}"))
    with Path("tool.log").open("wb") as log:
        run = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
    if run.returncode or Path("complete.txt").read_text() != "complete\n" or not Path("report.db").stat().st_size:
        return "error", "KLayout did not produce a complete check report", {"returncode": run.returncode}
    return (drc if mode == "drc" else lvs)(config)


if __name__ == "__main__":
    config = json.loads(Path("config.json").read_text())
    for name in ("tool.log", "report.db", "complete.txt", "extracted.spice", "layer-map.json"):
        Path(name).touch()
    try:
        status, reason, details = main(config)
    except Exception as error:  # noqa: BLE001 -- retain tool/report errors as errors, never failures.
        status, reason, details = "error", f"{type(error).__name__}: {error}", {}
    Path("result.json").write_text(json.dumps({"status": status, "reason": reason, "details": details}, indent=2))
