"""Independent physical-check fixture, with M1 pins and a variable drain wire.

No existing circuit layout is read. The MOS and tap use reviewed PDK primitives.
Negative cases deliberately change geometry, labels or device dimensions.
"""

import argparse

import pya
import sg13g2_pycell_lib  # noqa: F401

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output")
parser.add_argument("--length", type=float, default=10)
parser.add_argument("--fault", choices=["none", "short", "open", "parameter", "pin", "drc", "empty"], default="none")
args = parser.parse_args()
layout = pya.Layout()
layout.technology_name = "sg13g2"
top = layout.create_cell("MOS_SWITCH")
if args.fault != "empty":
    device = layout.create_cell("nmos", "SG13_dev", {"w": "2u" if args.fault == "parameter" else "1u",
                                                   "l": "0.2u", "ng": 1})
    tap = layout.create_cell("ptap1", "SG13_dev", {"w": "2u", "l": "2u"})
    top.insert(pya.DCellInstArray(device.cell_index(), pya.DTrans()))
    top.flatten(True)
    pins = sorted((s.dbbox() for s in top.shapes(layout.layer(8, 2)).each()), key=lambda b: b.center().x)
    gate = next(top.shapes(layout.layer(5, 2)).each()).dbbox().center()
    # Remove primitive pin annotations; create the fixture's explicit top ports.
    top.shapes(layout.layer(8, 2)).clear()
    top.shapes(layout.layer(5, 2)).clear()
    for layer in (8, 5):
        top.shapes(layout.layer(layer, 25)).clear()

    def box(layer, x1, y1, x2, y2):
        top.shapes(layout.layer(layer, 0)).insert(pya.DBox(x1, y1, x2, y2))

    def pin(name, x, y, width=0.1):
        top.shapes(layout.layer(8, 2)).insert(pya.DBox(x-width/2, y-width/2, x+width/2, y+width/2))
        top.shapes(layout.layer(8, 25)).insert(pya.DText(name, x, y))

    source, drain = [p.center() for p in pins]
    pin("S", source.x, source.y)
    pin("D", drain.x, drain.y)
    # Bring the poly gate to a real contact, well outside source/drain metal.
    gy = -1.0
    box(5, gate.x-0.1, gy, gate.x+0.1, gate.y)
    box(5, gate.x-0.18, gy-0.18, gate.x+0.18, gy+0.18)
    if args.fault != "open":
        box(6, gate.x-0.08, gy-0.08, gate.x+0.08, gy+0.08)
    box(8, gate.x-0.2, gy-0.2, gate.x+0.2, gy+0.2)
    pin("WRONG" if args.fault == "pin" else "G", gate.x, gy)
    box(8, drain.x, drain.y-0.1, 5+args.length, drain.y+0.1)
    box(8, 5, drain.y-0.1, 5+args.length, drain.y+1.9)
    top.insert(pya.DCellInstArray(tap.cell_index(), pya.DTrans(pya.DVector(-10, -10))))
    center = tap.dbbox().center()
    pin("B", center.x-10, center.y-10)
    top.flatten(True)
    if args.fault == "short":
        box(8, source.x, source.y-0.1, drain.x, drain.y+0.1)
    if args.fault == "drc":
        box(8, 20, -5, 21, -4.95)
layout.write(args.output)
