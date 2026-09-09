"""Synthetic case metadata shared by loader, CLI, and upstream API tests."""

import hashlib

import pytest


@pytest.fixture
def circuit_case(tmp_path):
    checkout = tmp_path / "synthetic-source"
    checkout.mkdir()
    netlist = b".subckt CIRCUIT_REF A B\nR1 A B 1000\n.ends\n"
    layout = b"Original layout bytes; tests replace the EDA boundary."
    (checkout / "circuit.spice").write_bytes(netlist)
    (checkout / "original.gds").write_bytes(layout)
    netlist_hash = hashlib.sha256(netlist).hexdigest()
    path = tmp_path / "case.toml"
    path.write_text(f'''schema_version = 2
kind = "layout_case"
id = "synthetic-circuit"
title = "Synthetic circuit"
status = "candidate"
[origin]
checkout = "synthetic-source"
commit = "{'a' * 40}"
license = "Synthetic test data"
[[sources]]
id = "source"
path = "circuit.spice"
role = "design"
format = "spice"
sha256 = "{netlist_hash}"
[[upstream_assets]]
id = "layout"
path = "original.gds"
role = "reference"
format = "gds"
sha256 = "{hashlib.sha256(layout).hexdigest()}"
[[upstream_assets]]
id = "netlist"
path = "circuit.spice"
role = "source-netlist"
format = "spice"
sha256 = "{netlist_hash}"
[[upstream_assets]]
id = "extracted"
path = "extracted.spice"
role = "extracted-netlist"
format = "spice"
sha256 = "{'b' * 64}"
[upstream_evaluation]
layout = "layout"
netlist = "netlist"
top_cell = "LAYOUT_TOP"
subcircuit = "CIRCUIT_REF"
drc_profile = "rules.json"
lvs_profile = "compare.json"
basis = "Synthetic fixture with distinct layout and circuit names"
''')
    return path
