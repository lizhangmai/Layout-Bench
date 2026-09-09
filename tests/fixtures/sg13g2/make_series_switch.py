"""Two low-W/L MOS devices joined by an unlabelled internal Metal1 wire."""

import argparse

import pya
import sg13g2_pycell_lib  # noqa: F401 -- registers the reviewed primitives

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output")
parser.add_argument("--wire-length", type=float, required=True)
args = parser.parse_args()
if args.wire_length <= 0:
    parser.error("Wire length must be positive")

layout = pya.Layout()
layout.technology_name = "sg13g2"
mos = layout.create_cell("nmos", "SG13_dev", {"w": "0.72u", "l": "9.75u", "ng": 1})
tap = layout.create_cell("ptap1", "SG13_dev", {"w": "2u", "l": "2u"})
top = layout.create_cell("SERIES_SWITCH")
metal = layout.layer(8, 0)
metal_pins = sorted((s.dbbox() for s in mos.shapes(layout.layer(8, 2)).each()),
                    key=lambda box: box.center().x)
source, drain = (box.center() for box in metal_pins)
gate = next(mos.shapes(layout.layer(5, 2)).each()).dbbox().center()
offset = drain.x + args.wire_length - source.x
for dx in (0, offset):
    top.insert(pya.DCellInstArray(mos.cell_index(), pya.DTrans(pya.DVector(dx, 0))))
top.flatten(True)
top.shapes(metal).insert(pya.DBox(drain.x, drain.y - 0.1,
                                source.x + offset, source.y + 0.1))
for name, layer, x, y in [("S", 8, source.x, source.y),
                           ("D", 8, drain.x + offset, drain.y),
                           ("G1", 5, gate.x, gate.y),
                           ("G2", 5, gate.x + offset, gate.y)]:
    top.shapes(layout.layer(layer, 2)).insert(pya.DText(name, x, y))
top.insert(pya.DCellInstArray(tap.cell_index(), pya.DTrans(pya.DVector(-10, -10))))
center = tap.dbbox().center()
top.shapes(layout.layer(8, 2)).insert(pya.DText("B", center.x - 10, center.y - 10))
top.flatten(True)
layout.write(args.output)
