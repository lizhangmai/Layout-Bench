"""Native geometry inspection; no task IDs, process layers or custom netlist parser."""

import json
import math
from pathlib import Path

from klayout import db
from klayout_runner import artifact


def inspect(config):
    error = artifact(config)
    if error:
        return "failed", error, {}, {}
    layout = db.Layout()
    layout.read("candidate.gds")
    top = layout.cell(config["top_cell"])
    extracted = db.LayoutVsSchematic()
    extracted.read("lvs.db")
    reference = extracted.reference.circuit_by_name(config["subcircuit"].upper())
    xref = extracted.xref()
    if reference is None or xref is None:
        raise ValueError("LVS comparison or reference circuit is absent")
    circuit = xref.other_circuit_for(reference)
    if circuit is None or circuit.name.upper() != config["top_cell"].upper():
        raise ValueError("LVS circuit differs from the requested top cell")
    if any(p.status() != db.NetlistCrossReference.Match for p in xref.each_circuit_pair()):
        raise ValueError("Geometry requires a successful LVS comparison")
    results, areas = {}, {}

    def region(layer):
        return db.Region(top.begin_shapes_rec(layout.layer(*layer))).merged()

    for spec in config["constraints"]["hard"]:
        if spec["type"] == "bbox_max":
            bounds = db.Box()
            for layer in spec["functional_layers"]:
                shapes = region(layer)
                if shapes.area() > 0:
                    bounds += shapes.bbox()
            width, height = bounds.width()*layout.dbu, bounds.height()*layout.dbu
            passed = not bounds.empty() and width <= spec["max_width_um"] and height <= spec["max_height_um"]
            results[spec["id"]] = {"passed": passed, "width_um": width, "height_um": height}
            areas[spec["id"]] = width*height
        else:
            # The entire access square must lie on pin AND drawing AND the
            # correct electrically extracted net. A nearby text label is not proof.
            layer = extracted.polygons_by_name(config["layers"][spec["connectivity_layer"]])
            if layer is None:
                raise ValueError("Requested connectivity layer is not registered in LVS")
            pins = region(spec["pin_layer"]) & region(spec["drawing_layer"])
            ports = {}
            positions = {name: [] for name in spec["names"]}
            for shape in top.shapes(layout.layer(*spec["text_layer"])).each():
                if shape.is_text() and shape.text.string in positions:
                    positions[shape.text.string].append(shape.text.trans.disp)
            for name, points in positions.items():
                refpin = next((p for p in reference.each_pin() if p.name() == name), None)
                if refpin is None:
                    raise ValueError(f"Port constraint has no matching reference pin: {name}")
                expected = xref.other_net_for(reference.net_for_pin(refpin.id()))
                if expected is None:
                    raise ValueError("Reference pin has no extracted net correspondence")
                net_geometry = extracted.shapes_of_net(expected, layer)
                # LVS uses its own DBU. Convert to the candidate's integer grid.
                net_geometry.transform(db.ICplxTrans(extracted.internal_layout().dbu/layout.dbu, 0, False, 0, 0))
                access = pins & net_geometry
                half = math.ceil(spec["min_access_square_um"] / (2*layout.dbu) - 1e-9)
                valid = []
                for p in points:
                    square = db.Region(db.Box(p.x-half, p.y-half, p.x+half, p.y+half))
                    valid.append((square-access).is_empty())
                ports[name] = {"passed": len(points) == 1 and all(valid), "labels": len(points)}
            results[spec["id"]] = {"passed": all(v["passed"] for v in ports.values()), "ports": ports}
    passed = all(v["passed"] for v in results.values())
    measurements = {spec["id"]: {"value": areas[spec["layers_from"]], "unit": "um2"}
                    for spec in config["constraints"]["quality"]} if passed else {}
    return ("passed" if passed else "failed"), ("" if passed else "Task geometry constraints violated"), results, measurements


if __name__ == "__main__":
    try:
        status, reason, details, measurements = inspect(json.loads(Path("config.json").read_text()))
    except Exception as error:  # noqa: BLE001 -- preserve native tool errors as errors
        status, reason, details, measurements = "error", f"{type(error).__name__}: {error}", {}, {}
    Path("result.json").write_text(json.dumps({"status": status, "reason": reason,
        "details": details, "measurements": measurements}, indent=2))
