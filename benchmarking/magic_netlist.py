"""Run Magic and verify its exported interface with a native SPICE reader."""

import json
import subprocess
from pathlib import Path

from klayout import db

run = subprocess.run(["magic", "-dnull", "-noconsole", "-rcfile", "empty.magicrc", "extract.tcl"], check=False)
if run.returncode:
    raise SystemExit(run.returncode)
config = json.loads(Path("interface.json").read_text())
netlist = db.Netlist()
netlist.read("extracted.spice", db.NetlistSpiceReader())
circuit = netlist.circuit_by_name(config["top_cell"].upper())
if circuit is None:
    raise ValueError("Extraction did not produce the requested circuit")
ports = [p.name() for p in circuit.each_pin()]
if ports != [p.upper() for p in config["ports"]]:
    raise ValueError(f"Extracted port order/names differ from the declared interface: {ports}")
if not any(circuit.each_device()) and not any(circuit.each_subcircuit()):
    raise ValueError("Extracted circuit is empty")
Path("interface-check.json").write_text(json.dumps({"top_cell": circuit.name, "ports": ports}))
