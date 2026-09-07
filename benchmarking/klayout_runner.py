"""Container-only implementation. Uses KLayout's native GDS and report readers."""

import json
import math
import subprocess
from pathlib import Path

from klayout import db, rdb


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be a nonempty string without NUL")
    return value


def _validate_waivers(value):
    """Validate the case-local marker allow-list inside the tool container."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("DRC waivers must be a list")
    waivers = []
    seen = set()
    for index, waiver in enumerate(value):
        if not isinstance(waiver, dict):
            raise TypeError(f"DRC waiver {index} must be an object")
        required = {"category", "cell", "markers", "reason"}
        if set(waiver) != required:
            raise ValueError(f"DRC waiver {index} has invalid fields")
        category = _text(waiver["category"], f"DRC waiver {index} category")
        cell = _text(waiver["cell"], f"DRC waiver {index} cell")
        reason = _text(waiver["reason"], f"DRC waiver {index} reason")
        markers = waiver["markers"]
        if not isinstance(markers, list) or not markers:
            raise ValueError(f"DRC waiver {index} markers must be a nonempty list")
        markers = [_text(marker, f"DRC waiver {index} marker") for marker in markers]
        if len(set(markers)) != len(markers):
            raise ValueError(f"DRC waiver {index} markers must be unique")
        for marker in markers:
            identity = (category, cell, marker)
            if identity in seen:
                raise ValueError(f"Duplicate DRC waiver marker: {identity}")
            seen.add(identity)
        waivers.append({"category": category, "cell": cell, "markers": markers,
                        "reason": reason})
    return waivers


def _drc_item_signature(report, item):
    category_object = report.category_by_id(item.category_id())
    cell_object = report.cell_by_id(item.cell_id())
    category = category_object.path() if category_object is not None else ""
    cell = cell_object.name() if cell_object is not None else ""
    values = tuple(value.to_s() for value in item.each_value())
    return category, cell, values


def _apply_drc_waivers(report, waivers):
    """Return raw/unwaived counts while preserving the native report."""
    allowed = {
        (waiver["category"], waiver["cell"], (marker,)): (index, waiver)
        for index, waiver in enumerate(waivers) for marker in waiver["markers"]
    }
    used = set()
    waived_by_category = {}
    unwaived_by_category = {}
    matched_by_waiver = [0] * len(waivers)
    unwaived = []
    for item in report.each_item():
        category, cell, values = _drc_item_signature(report, item)
        key = (category, cell, values)
        match = allowed.get(key)
        if match is not None and key not in used:
            used.add(key)
            index, _ = match
            matched_by_waiver[index] += 1
            waived_by_category[category] = waived_by_category.get(category, 0) + 1
        else:
            unwaived.append((category, cell, values))
            unwaived_by_category[category] = unwaived_by_category.get(category, 0) + 1

    waiver_details = []
    for waiver, matched in zip(waivers, matched_by_waiver):
        waiver_details.append({"category": waiver["category"], "cell": waiver["cell"],
                               "declared_markers": len(waiver["markers"]),
                               "matched_markers": matched, "reason": waiver["reason"]})
    return unwaived, waived_by_category, unwaived_by_category, waiver_details


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
    waivers = _validate_waivers(config.get("waivers"))
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
    unwaived, waived_by_category, unwaived_by_category, waiver_details = _apply_drc_waivers(report, waivers)
    details.update({"waived_violations": report.num_items() - len(unwaived),
                    "unwaived_violations": len(unwaived),
                    "waived_by_category": waived_by_category,
                    "unwaived_by_category": unwaived_by_category,
                    "waivers": waiver_details})
    if unwaived:
        return "failed", "Unexpected DRC violations found", details
    if report.num_items():
        reasons = sorted({entry["reason"] for entry in waiver_details if entry["matched_markers"]})
        return "passed", "DRC violations waived: " + " | ".join(reasons), details
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
