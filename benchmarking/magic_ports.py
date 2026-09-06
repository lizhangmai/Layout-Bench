"""Lossless GDS label aliases for characters Magic trims during SPICE export."""

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
layout.write("extraction.gds")
