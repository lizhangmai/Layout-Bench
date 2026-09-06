"""Fresh extraction fixture: one M1 rectangle and a distant substrate contact.

This is an analytical tool check, not a qualified benchmark task or reference
layout. Run with KLayout Python in the extractor image; dimensions are microns.
"""

import argparse

from klayout import db

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output")
parser.add_argument("--width", type=float, default=20)
parser.add_argument("--height", type=float, default=10)
args = parser.parse_args()
if args.width <= 0 or args.height <= 0:
    parser.error("Plate dimensions must be positive")
layout = db.Layout()
layout.dbu = 0.001
cell = layout.create_cell("PLATE")
cell.shapes(layout.layer(8, 0)).insert(db.DBox(0, 0, args.width, args.height))
cell.shapes(layout.layer(8, 2)).insert(db.DText("P", 1, 1))
# The contact labels the substrate GND; it is deliberately far from the plate.
for layer, box in ((1, (-101, -101, -99, -99)), (14, (-101.4, -101.4, -98.6, -98.6)),
                   (8, (-101, -101, -99, -99)), (6, (-100.08, -100.08, -99.92, -99.92))):
    cell.shapes(layout.layer(layer, 0)).insert(db.DBox(*box))
cell.shapes(layout.layer(8, 2)).insert(db.DText("GND", -100, -100))
layout.write(args.output)
