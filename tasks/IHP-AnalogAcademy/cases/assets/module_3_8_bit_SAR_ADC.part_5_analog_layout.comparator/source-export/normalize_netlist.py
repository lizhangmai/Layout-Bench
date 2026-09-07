"""Create the SG13G2 task netlist from the pinned upstream LVS netlist.

The upstream file includes explicit ntap1/ptap1 process-tie devices.  The
Layout-Bench SG13G2 LVS profile models those ties as connectivity, so this
small, deterministic projection removes the two process devices and ties the
MOS bulk terminals to VDD/GND.  It does not change signal connectivity,
device models, geometry parameters, or the top-level interface.
"""

import argparse
import hashlib
from pathlib import Path

SOURCE_SHA256 = "fb74cb22eebf4ee891956ef779718a9378ef3a5d538c62b527684873f9bec1f5"
TARGET_SHA256 = "0922f97fc3ffeff2ca68ccf3a834f0b8b6f47c9dcdee1e3af8bb814fe22cd77c"


def normalize(source: Path, target: Path) -> None:
    source_bytes = source.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != SOURCE_SHA256:
        raise ValueError("Pinned upstream netlist checksum mismatch")

    output = [
        "** Source-normalized netlist for the Layout-Bench SG13G2 LVS profile.",
        "** Derived from the pinned upstream LVS netlist; ntap1/ptap1 are process ties,",
        "** so their explicit resistor devices are omitted and bulk nodes are tied to",
        "** the corresponding supply rails.",
        ".SUBCKT DIFF_COMPARATOR VDD GND V+ V- CLK OUT- OUT+ VBIAS",
        "*.PININFO VDD:B GND:B V+:I V-:I CLK:I OUT-:O OUT+:O VBIAS:I",
    ]
    for line in source_bytes.decode("utf-8").splitlines():
        if line.startswith(("**", ".SUBCKT", "*.PININFO", ".ENDS")):
            continue
        if line.startswith(("R1 ", "R2 ")):
            continue
        if line.startswith("M"):
            fields = line.split()
            fields[1:5] = [
                "vdd" if net == "well" else "gnd" if net == "sub" else net
                for net in fields[1:5]
            ]
            line = " ".join(fields)
        output.append(line)
    output.append(".ENDS")
    target_bytes = ("\n".join(output) + "\n").encode("utf-8")
    if hashlib.sha256(target_bytes).hexdigest() != TARGET_SHA256:
        raise ValueError("Normalization output checksum mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(target_bytes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    normalize(args.source, args.target)
