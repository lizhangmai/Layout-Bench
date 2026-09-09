"""Prepare an isolated GDS for Magic: label aliases and optional flat geometry."""

import json
from pathlib import Path

from klayout import db

config = json.loads(Path("ports.json").read_text())
layout = db.Layout()
layout.read("candidate.gds")
used = {s.text.string for c in layout.each_cell() for i in layout.layer_indexes()
        for s in c.shapes(i).each() if s.is_text()}
for original, alias in config["aliases"].items():
    if alias in used:
        raise ValueError("Generated extraction alias collides with a layout label")
    for cell in layout.each_cell():
        for index in layout.layer_indexes():
            for shape in cell.shapes(index).each():
                if shape.is_text() and shape.text.string == original:
                    label = shape.text
                    label.string = alias
                    shape.text = label
report = {"aliases": config["aliases"], "flattened": False}
if "flatten_top" in config:
    top = layout.cell(config["flatten_top"])
    if top is None:
        raise ValueError("Missing extraction top cell")
    regions = {i: db.Region(top.begin_shapes_rec(i)).merged() for i in layout.layer_indexes()}
    top.flatten(True)
    for index, region in regions.items():
        if not (region ^ db.Region(top.begin_shapes_rec(index)).merged()).is_empty():
            raise ValueError("Flattening changed extraction geometry")
    top.write("extraction.gds")
    report.update(flattened=True, geometry_unchanged=True, top_cell=top.name)
else:
    layout.write("extraction.gds")
Path("preparation-check.json").write_text(json.dumps(report))
