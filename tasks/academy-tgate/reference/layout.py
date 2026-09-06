"""Independent T_gate reference, composed from reviewed PDK MOS/tap primitives."""

import argparse

import pya
import sg13g2_pycell_lib  # noqa: F401

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output")
parser.add_argument("--n-width", default="1u")
args = parser.parse_args()
layout = pya.Layout()
layout.technology_name = "sg13g2"
top = layout.create_cell("T_gate")


def box(layer, x1, y1, x2, y2):
    top.shapes(layout.layer(layer, 0)).insert(pya.DBox(x1, y1, x2, y2))


def pin(name, x, y):
    box(8, x-.25, y-.25, x+.25, y+.25)
    top.shapes(layout.layer(8, 2)).insert(pya.DBox(x-.2, y-.2, x+.2, y+.2))
    top.shapes(layout.layer(8, 25)).insert(pya.DText(name.upper(), x, y))


for kind, width, y, gate_y, name in [("nmos", args.n_width, 0, -1, "Control"), ("pmos", "2u", 8, 12, "!Control")]:
    cell = layout.create_cell(kind, "SG13_dev", {"w": width, "l": "0.13u", "ng": 1})
    cell.flatten(True)
    pins = sorted((p.bbox().to_dtype(layout.dbu) for p in pya.Region(cell.begin_shapes_rec(layout.layer(8, 0))).merged().each()), key=lambda b: b.center().x)
    assert len(pins) == 2
    gate = pya.Region(cell.begin_shapes_rec(layout.layer(5, 0))).bbox().to_dtype(layout.dbu).center()
    top.insert(pya.DCellInstArray(cell.cell_index(), pya.DTrans(pya.DVector(0, y))))
    source, drain = [b.center() for b in pins]
    box(8, -2.2, y+source.y-.1, source.x, y+source.y+.1)
    box(8, drain.x, y+drain.y-.1, 3.2, y+drain.y+.1)
    box(5, gate.x-.065, min(gate_y, y+gate.y), gate.x+.065, max(gate_y, y+gate.y))
    box(5, gate.x-.18, gate_y-.18, gate.x+.18, gate_y+.18)
    box(6, gate.x-.08, gate_y-.08, gate.x+.08, gate_y+.08)
    pin(name, gate.x, gate_y)
box(8, -2.2, .4, -1.8, 9.1)
box(8, 2.8, .4, 3.2, 9.1)
pin("Vout", -2, 4)
pin("Vin", 3, 4)
for kind, y, name in [("ptap1", 0, "gnd"), ("ntap1", 8, "vdd")]:
    cell = layout.create_cell(kind, "SG13_dev", {"w": "2u", "l": "2u"})
    top.insert(pya.DCellInstArray(cell.cell_index(), pya.DTrans(pya.DVector(-5, y))))
    pin(name, -4, y+1)
# Join the PMOS well to its physical well tap.
box(31, -5.5, 7.5, 1.5, 11)
top.flatten(True)
# Retain only the explicit top interface; primitive pins are construction details.
for layer in (5,):
    top.shapes(layout.layer(layer, 2)).clear()
options = pya.SaveLayoutOptions()
options.gds2_write_timestamps = False
layout.write(args.output, options)
