"""Magic parasitic extraction with caller-selected technology and pin order."""

import json
import re
from pathlib import Path

from .bundles import load_bundle
from .docker import DockerTool
from .evaluate import JobResult
from .evaluation import Job, number
from .files import Asset, keys, relative, text


def _tcl_word(value: str) -> str:
    value = text(value, "Tcl argument")
    for old, new in (("\\", "\\\\"), ('"', '\\"'), ("$", "\\$"), ("[", "\\["), ("]", "\\]"),
                     ("\n", "\\n"), ("\r", "\\r")):
        value = value.replace(old, new)
    return '"' + value + '"'


class MagicCapacitanceDocker:
    """Extract devices and coupled capacitances; wire resistance is not included.

    This adapter does not certify DRC or LVS. The evaluated plan must require
    independent validity gates before extraction can count toward task success.
    """

    wire_resistance = False

    def __init__(self, *, image: str, support: str, technology: str, tech_name: str,
                 style: str, capacitance_threshold_ff: float = 0, timeout_seconds: float = 60):
        self.support = load_bundle(Path(support))
        self.technology = relative(technology, "Magic technology")
        if self.technology not in dict(self.support.files):
            raise ValueError("Magic technology is missing from the support bundle")
        self.tech_name, self.style = text(tech_name, "technology name"), text(style, "extract style")
        self.threshold = number(capacitance_threshold_ff)
        if self.threshold < 0:
            raise ValueError("Capacitance threshold cannot be negative")
        self.tool = DockerTool(image, ["magic", "--version"], timeout_seconds)

    @property
    def identity(self) -> dict:
        return {"adapter": "magic-rc-docker" if self.wire_resistance else "magic-capacitance-docker", **self.tool.identity,
                "adapter_sha256": Asset(Path(__file__).read_bytes(), "python").sha256,
                "port_alias_sha256": Asset(Path(__file__).with_name("magic_ports.py").read_bytes(), "python").sha256,
                "interface_check_sha256": Asset(Path(__file__).with_name("magic_netlist.py").read_bytes(), "python").sha256,
                "support_sha256": self.support.manifest.sha256, "technology": self.technology,
                "tech_name": self.tech_name, "extract_style": self.style,
                "parasitics": "distributed_rc" if self.wire_resistance else "coupled_capacitance",
                "wire_resistance": self.wire_resistance,
                "capacitance_threshold_ff": self.threshold,
                **({"flatten": True, "resistance_threshold_mohm": 0, "minimum_resistance_mohm": 0,
                    "minimum_delay_ps": 0, "simplify_resistance": False, "merge_devices": "none",
                    "same_conductor_ports": "rejected"}
                   if self.wire_resistance else {})}

    def run(self, job: Job, inputs: dict[str, Asset]) -> JobResult:
        if job.stage != "extract" or set(inputs) - {"layout", "task"} or "layout" not in inputs:
            raise ValueError("Magic extraction requires layout and optional task inputs")
        if inputs["layout"].format != "gds" or dict(job.outputs) != {"netlist": "spice"}:
            raise ValueError("Magic extraction requires GDS and a declared SPICE netlist output")
        params = job.parameters
        keys(params, {"ports"}, {"top_cell"}, "Magic extraction parameters")
        top = params.get("top_cell")
        if "task" in inputs:
            if inputs["task"].format != "json":
                raise ValueError("Task description must be JSON")
            configured = json.loads(inputs["task"].content)["output"]["top_cell"]
            if top is not None and top != configured:
                raise ValueError("Extraction top cell differs from task configuration")
            top = configured
        top = text(top, "top cell")
        ports = params["ports"]
        if not isinstance(ports, list) or not ports or len(set(ports)) != len(ports):
            raise ValueError("Extraction requires an ordered list of unique ports")
        # Magic trims ! (even in prefixes) and rewrites several other SPICE characters.
        # Alias only unsafe interface labels in an isolated GDS copy, never source text.
        aliases = {p: f"LBPORT_{inputs['layout'].sha256[:16]}_{i}" for i, p in enumerate(ports)
                   if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", p)}
        port_commands = []
        for index, port in enumerate(ports, 1):
            arg = _tcl_word(aliases.get(port, port))
            port_commands.extend([f'if {{[port {arg} index] eq ""}} {{port {arg} make {index}}} else {{port {arg} index {index}}}',
                                  f'if {{[port {arg} index] ne "{index}"}} {{error "Missing or ambiguous port"}}'])
        prepare_layout = bool(aliases) or self.wire_resistance
        script = "\n".join([
            "if {[catch {", "drc off", f"tech load {_tcl_word('/workspace/support/' + self.technology)}",
            f'if {{[tech name] ne {_tcl_word(self.tech_name)}}} {{error "Wrong technology"}}',
            "gds readonly true", "gds read extraction.gds" if prepare_layout else "gds read candidate.gds",
            f'if {{[cellname list exists {_tcl_word(top)}] eq "0"}} {{error "Missing top cell"}}',
            f"load {_tcl_word(top)}", "select top cell", "expand",
            *port_commands, f"extract style {_tcl_word(self.style)}", "extract warn all", "extract all",
            *(["ext2spice default", "ext2spice format ngspice", "ext2spice scale off",
               "ext2spice hierarchy off", "ext2spice subcircuit top on", "ext2spice global off",
               "ext2spice short resistor", "ext2spice extresist off", "ext2spice cthresh infinite",
               "ext2spice -o topology.spice"] if self.wire_resistance else []),
            *(["extresist threshold 0", "extresist minres 0", "extresist mindelay 0",
               "extresist simplify off", "extresist all"] if self.wire_resistance else []),
            "ext2spice default", "ext2spice format ngspice", "ext2spice scale off",
            "ext2spice hierarchy off", "ext2spice subcircuit top on", "ext2spice global off",
            *(["ext2spice merge none", "ext2spice short none", "ext2spice extresist on"]
              if self.wire_resistance else ["ext2spice extresist off"]),
            "ext2spice rthresh infinite",
            f"ext2spice cthresh {self.threshold:.17g}", "ext2spice -o extracted.spice",
            *([f"file copy -- {_tcl_word(top + '.ext')} extraction.ext",
               f"file copy -- {_tcl_word(top + '.res.ext')} resistance.ext",
               "feedback save feedback.tcl"] if self.wire_resistance else []),
            'set done [open complete.txt w]', 'puts $done "extraction complete"', "close $done",
            '} detail]} {puts stderr "EXTRACTION_ERROR: $detail"; exit 1}', "quit -noprompt", "",
        ])
        files = {"candidate.gds": inputs["layout"], "extract.tcl": Asset(script.encode(), "tcl"),
                 "empty.magicrc": Asset(b"# No user startup or device generators.\n", "tcl"),
                 **self.support.mounted_files()}
        preprocessing = {}
        if prepare_layout:
            helper = Asset(Path(__file__).with_name("magic_ports.py").read_bytes(), "python")
            mapping = Asset(json.dumps({"aliases": aliases, "ports": [aliases.get(p, p) for p in ports],
                                        **({"flatten_top": top} if self.wire_resistance else {})}).encode(), "json")
            prepared = self.tool.run(["python", "magic_ports.py"], {
                "candidate.gds": inputs["layout"], "magic_ports.py": helper, "ports.json": mapping},
                {"extraction.gds": "gds", "preparation-check.json": "json"})
            preprocessing = {"port_aliases": mapping, "alias_helper": helper,
                             **{f"alias_{k}": a for k, a in prepared.evidence.items()}, **prepared.files}
            if prepared.reason or prepared.returncode:
                return JobResult("error", prepared.reason, evidence=preprocessing)
            files["extraction.gds"] = prepared.files["extraction.gds"]
        files["magic_netlist.py"] = Asset(Path(__file__).with_name("magic_netlist.py").read_bytes(), "python")
        files["interface.json"] = Asset(json.dumps({"top_cell": top, "ports": [aliases.get(p, p) for p in ports],
                                                   "reject_aliased_ports": self.wire_resistance}).encode(), "json")
        result = self.tool.run(["python", "magic_netlist.py"], files,
                               {"extracted.spice": "spice", "complete.txt": "text", "interface-check.json": "json",
                                **({"extraction.ext": "magic-ext", "resistance.ext": "magic-ext",
                                    "feedback.tcl": "tcl", "topology.spice": "spice"}
                                   if self.wire_resistance else {})})
        evidence = {**self.support.evidence(), **preprocessing, **result.evidence, "script": files["extract.tcl"],
                    "interface": files["interface.json"], "interface_checker": files["magic_netlist.py"]}
        if "interface-check.json" in result.files:
            evidence["interface_check"] = result.files["interface-check.json"]
        if "extracted.spice" in result.files:
            evidence["extracted_netlist"] = result.files["extracted.spice"]
        for name in ("extraction.ext", "resistance.ext", "feedback.tcl", "topology.spice"):
            if name in result.files:
                evidence[name] = result.files[name]
        log = result.evidence.get("console", Asset(b"", "text")).content.decode(errors="replace")
        if result.reason or result.returncode != 0:
            return JobResult("error", result.reason or "Magic did not complete", evidence=evidence)
        if re.search(r"error|unrecognized|unknown layer|unmapped|not found|couldn't|cannot", log, re.IGNORECASE):
            return JobResult("error", "Magic reported an extraction or input error", evidence=evidence)
        return JobResult("passed", outputs={"netlist": result.files["extracted.spice"]}, evidence=evidence)


class MagicRCDocker(MagicCapacitanceDocker):
    """Extract distributed resistance and capacitance without resistor pruning.

    The isolated extraction copy is flattened with a geometry equivalence check.
    Requires the explicit threshold controls introduced in Magic 8.3.653.
    """

    wire_resistance = True

    def __init__(self, **settings):
        super().__init__(**settings)
        version = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", self.tool.identity["tool_version"].strip())
        if version is None or tuple(map(int, version.groups())) < (8, 3, 653):
            raise ValueError("Magic RC extraction requires Magic 8.3.653 or newer")
