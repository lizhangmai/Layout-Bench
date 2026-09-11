"""Minimal task inputs for session/CLI tests; no circuit or EDA qualification."""

from benchmarking.files import Asset


def write_protocol_task(root):
    root.mkdir(parents=True, exist_ok=True)
    netlist = b"* Protocol-only input; never simulated or compared by LVS.\n.subckt TEST A B\n.ends\n"
    (root / "input.spice").write_bytes(netlist)
    config = '''schema_version = 1
id = "protocol-test"
title = "Synthetic protocol input"
kind = "netlist_to_gds"
family = "protocol"
status = "candidate"
environment = "no-eda"
[inputs.netlist]
path = "input.spice"
format = "spice"
sha256 = "NETLIST_HASH"
subcircuit = "TEST"
[constraints]
hard = []
[output]
path = "output/final.gds"
format = "gds"
top_cell = "TEST"
max_bytes = 1048576
[evaluation]
schema_version = 1
mode = "post_layout"
'''.replace("NETLIST_HASH", Asset(netlist, "spice").sha256)
    for gate in ("artifact", "drc", "lvs"):
        config += f'''[[evaluation.jobs]]
id = "{gate}"
stage = "check"
operation = "check"
gate = "{gate}"
inputs = {{layout = "candidate"}}
'''
    config += '''[[evaluation.jobs]]
id = "extract"
stage = "extract"
operation = "extract"
requires = ["artifact", "drc", "lvs"]
inputs = {layout = "candidate"}
outputs = {netlist = "spice"}
[[evaluation.jobs]]
id = "simulate"
stage = "simulate"
operation = "simulate"
inputs = {dut = "job:extract:netlist"}
[[evaluation.metrics]]
id = "response"
category = "performance"
observations = ["simulate:response"]
unit = "s"
direction = "minimize"
aggregation = "max"
upper = 1
'''
    path = root / "task.toml"
    path.write_text(config)
    return path
