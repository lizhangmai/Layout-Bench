"""Fresh MOS extraction fixture using the reviewed IHP device primitives.

The square drain plate varies parasitic load without changing MOS dimensions.
This fixture qualifies extraction/simulation only; DRC/LVS are separate checks.
"""

import argparse

import pya
import sg13g2_pycell_lib  # noqa: F401 -- registers the reviewed primitive library

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output")
parser.add_argument("--plate", type=float, default=10)
args = parser.parse_args()
if args.plate <= 0:
    parser.error("Plate dimension must be positive")
layout = pya.Layout()
layout.technology_name = "sg13g2"
device = layout.create_cell("nmos", "SG13_dev", {"w": "1u", "l": "0.2u", "ng": 1})
tap = layout.create_cell("ptap1", "SG13_dev", {"w": "2u", "l": "2u"})
top = layout.create_cell("MOS_SWITCH")
top.insert(pya.DCellInstArray(device.cell_index(), pya.DTrans()))
top.flatten(True)
# The fixed primitive has source at left, drain at right, and one gate pin.
metal_pins = sorted((s.dbbox() for s in top.shapes(layout.layer(8, 2)).each()), key=lambda b: b.center().x)
gate_pins = [s.dbbox() for s in top.shapes(layout.layer(5, 2)).each()]
assert len(metal_pins) == 2 and len(gate_pins) == 1
for name, box, layer in (("S", metal_pins[0], 8), ("D", metal_pins[1], 8), ("G", gate_pins[0], 5)):
    center = box.center()
    top.shapes(layout.layer(layer, 2)).insert(pya.DText(name, center.x, center.y))
drain = metal_pins[1].center()
top.shapes(layout.layer(8, 0)).insert(pya.DBox(drain.x, drain.y - 0.1, 5 + args.plate, drain.y + 0.1))
top.shapes(layout.layer(8, 0)).insert(pya.DBox(5, drain.y - 0.1, 5 + args.plate, drain.y - 0.1 + args.plate))
top.insert(pya.DCellInstArray(tap.cell_index(), pya.DTrans(pya.DVector(-10, -10))))
center = tap.dbbox().center()
top.shapes(layout.layer(8, 2)).insert(pya.DText("B", center.x - 10, center.y - 10))
top.flatten(True)
layout.write(args.output)
