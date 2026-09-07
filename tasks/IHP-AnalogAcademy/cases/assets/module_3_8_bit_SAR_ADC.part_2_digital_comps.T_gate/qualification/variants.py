"""Construct public negative cases from the freshly generated reference GDS."""

import argparse
from pathlib import Path

from klayout import db

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("reference")
parser.add_argument("destination")
args = parser.parse_args()
out = Path(args.destination)
out.mkdir(parents=True, exist_ok=False)
for variant in ("slow", "outline", "pin_size", "missing_pin", "short", "open", "drc", "empty", "translated", "hierarchy", "nested_labels", "duplicate_label"):
    layout = db.Layout()
    layout.read(args.reference)
    top = layout.cell("T_gate")
    def box(x1,y1,x2,y2, top=top, layout=layout):
        top.shapes(layout.layer(8,0)).insert(db.DBox(x1,y1,x2,y2))
    if variant == "slow":
        box(-24,-1,-6,24)
        box(-6.1,3.9,-2,4.1)
    elif variant == "outline":
        box(35,20,36,21)
    elif variant == "pin_size":
        shapes = top.shapes(layout.layer(8,2))
        for s in list(shapes.each()):
            if s.dbbox().contains(db.DPoint(-2,4)):
                s.delete()
        shapes.insert(db.DBox(-2.1,3.9,-1.9,4.1))
    elif variant == "missing_pin":
        for s in list(top.shapes(layout.layer(8,25)).each()):
            if s.is_text() and s.text.string == "CONTROL":
                s.delete()
    elif variant == "short":
        box(-2,3.9,3,4.1)
    elif variant == "open":
        for s in list(top.shapes(layout.layer(6,0)).each()):
            if s.dbbox().contains(db.DPoint(.405,-1)):
                s.delete()
    elif variant == "drc":
        box(5,4,6,4.05)
    elif variant == "empty":
        layout = db.Layout()
        top = layout.create_cell("T_gate")
    elif variant == "translated":
        top.transform(db.Trans(100000,-200000))
    elif variant == "duplicate_label":
        top.shapes(layout.layer(8,25)).insert(db.DText("VIN",3,4))
    elif variant in {"hierarchy", "nested_labels"}:
        top.name = "DEVICES"
        parent = layout.create_cell("T_gate")
        parent.insert(db.CellInstArray(top.cell_index(),db.Trans()))
        # Move interface labels to the top while retaining all geometry in its child.
        for s in list(top.shapes(layout.layer(8,25)).each()) if variant == "hierarchy" else []:
            parent.shapes(layout.layer(8,25)).insert(s.text)
            s.delete()
    options = db.SaveLayoutOptions()
    options.gds2_write_timestamps = False
    layout.write(str(out / f"{variant}.gds"),options)
