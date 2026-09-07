"""Isolated KLayout artifact, DRC and LVS checks with frozen external rule decks."""

import json
import re
from pathlib import Path

from .bundles import load_bundle
from .docker import DockerTool
from .evaluate import JobResult
from .evaluation import Job
from .files import Asset, keys, relative, text


def validate_drc_waivers(value: object) -> list[dict]:
    """Validate case-local DRC marker waivers before invoking KLayout.

    A waiver names the report category, exact report cell, and the textual
    marker values that may be accepted.  Requiring exact markers keeps an
    exception local to the reviewed geometry instead of turning a rule into a
    task-wide allow-list.  The runner validates the same shape inside the
    isolated tool container before applying it to a report.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("DRC waivers must be a list")
    waivers = []
    seen = set()
    for index, waiver in enumerate(value):
        keys(waiver, {"category", "cell", "markers", "reason"}, set(),
             f"DRC waiver {index}")
        category = text(waiver["category"], f"DRC waiver {index} category")
        cell = text(waiver["cell"], f"DRC waiver {index} cell")
        reason = text(waiver["reason"], f"DRC waiver {index} reason")
        markers = waiver["markers"]
        if not isinstance(markers, list) or not markers:
            raise ValueError(f"DRC waiver {index} markers must be a nonempty list")
        markers = [text(marker, f"DRC waiver {index} marker") for marker in markers]
        if len(set(markers)) != len(markers):
            raise ValueError(f"DRC waiver {index} markers must be unique")
        for marker in markers:
            identity = (category, cell, marker)
            if identity in seen:
                raise ValueError(f"Duplicate DRC waiver marker: {identity}")
            seen.add(identity)
        waivers.append({"category": category, "cell": cell, "markers": markers,
                        "reason": reason})
    return waivers


class KLayoutDocker:
    """Check one concern. Technology settings live in a reviewed support bundle.

    The profile selects a deck and fixed -rd variables, not arbitrary commands.
    The task supplies only its top cell, authoritative netlist and size limit.
    DRC jobs may add exact, case-local marker waivers; they never alter the deck.
    """

    def __init__(self, *, image: str, check: str, support: str | None = None,
                 profile: str | None = None, timeout_seconds: float = 120):
        if check not in {"artifact", "drc", "lvs"}:
            raise ValueError("Unknown KLayout check")
        self.check = check
        self.support = load_bundle(Path(support)) if support else None
        self.settings = {}
        if check == "artifact":
            if support is not None or profile is not None:
                raise ValueError("Artifact checks do not use technology support")
        else:
            if self.support is None:
                raise ValueError("DRC/LVS requires a reviewed support bundle")
            profile = relative(profile, "KLayout check profile")
            self.settings = json.loads(dict(self.support.files)[profile].content)
            required = {"deck", "variables", "scope"}
            if check == "drc":
                required.add("required_categories")
            keys(self.settings, required, {"layer_names"} if check == "lvs" else set(), "KLayout check profile")
            for name, variable in self.settings.get("layer_names", {}).items():
                if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or not re.fullmatch(r"[a-z][a-z0-9_]*", variable):
                    raise ValueError("LVS layer names must be simple identifiers")
            deck = relative(self.settings["deck"], "KLayout deck")
            if (deck not in dict(self.support.files) or not deck.endswith("." + check)
                    or not re.fullmatch(r"[A-Za-z0-9_./-]+", deck)):
                raise ValueError("Missing or incorrectly typed KLayout deck")
            text(self.settings["scope"], "check scope")
            variables = self.settings["variables"]
            if not isinstance(variables, dict):
                raise TypeError("KLayout variables must be a mapping")
            for name, value in variables.items():
                if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in {
                    "input", "topcell", "report", "log", "schematic", "target_netlist"}:
                    raise ValueError("Invalid or reserved KLayout variable")
                if not isinstance(value, str) or "\x00" in value:
                    raise ValueError("KLayout variable values must be strings")
            if check == "drc":
                categories = self.settings["required_categories"]
                if not isinstance(categories, list) or not categories or len(set(categories)) != len(categories):
                    raise ValueError("DRC requires its required, unique report category list")
                for category in categories:
                    text(category, "DRC category")
        self.tool = DockerTool(image, ["klayout", "-v"], timeout_seconds)
        self.runner = Asset(Path(__file__).with_name("klayout_runner.py").read_bytes(), "python")

    @property
    def identity(self) -> dict:
        return {"adapter": "klayout-docker", "check": self.check, **self.tool.identity,
                "adapter_sha256": Asset(Path(__file__).read_bytes(), "python").sha256,
                "runner_sha256": self.runner.sha256, "settings": self.settings,
                "support_sha256": self.support.manifest.sha256 if self.support else None}

    def run(self, job: Job, inputs: dict[str, Asset]) -> JobResult:
        required = {"layout", "netlist"} if self.check == "lvs" else {"layout"}
        keys(inputs, required, {"task"}, "KLayout check inputs")
        if job.gate not in {None, self.check}:
            raise ValueError("KLayout check does not implement the declared gate")
        allowed_outputs = {"database": "klayout-lvs", "binding": "json"}
        if (job.stage != "check" or inputs["layout"].format != "gds"
                or job.outputs and (self.check != "lvs" or dict(job.outputs) != allowed_outputs)):
            raise ValueError("KLayout checks require GDS; only LVS may export database and binding")
        allowed = {"top_cell", "max_bytes"} | ({"subcircuit"} if self.check == "lvs" else set())
        if self.check == "drc":
            allowed.add("waivers")
        keys(job.parameters, set(), allowed, "KLayout check parameters")
        params = dict(job.parameters)
        if self.check == "drc":
            params["waivers"] = validate_drc_waivers(params.get("waivers"))
        if "task" in inputs:
            if inputs["task"].format != "json":
                raise ValueError("Task description must be JSON")
            task = json.loads(inputs["task"].content)
            configured = {"top_cell": task["output"]["top_cell"], "max_bytes": task["output"]["max_bytes"]}
            if self.check == "lvs":
                configured["subcircuit"] = task["netlist_subcircuit"]
            for name, value in configured.items():
                if name in params and params[name] != value:
                    raise ValueError(f"KLayout {name} differs from task configuration")
                params[name] = value
        text(params.get("top_cell"), "top cell")
        if type(params.get("max_bytes")) is not int or params["max_bytes"] <= 0:
            raise ValueError("KLayout checks require the published positive max_bytes limit")
        if self.check == "lvs":
            text(params.get("subcircuit"), "reference subcircuit")
            if inputs["netlist"].format not in {"spice", "text"}:
                raise ValueError("LVS requires an authoritative SPICE/CDL netlist")
        config = Asset(json.dumps({"check": self.check, **params, **self.settings}).encode(), "json")
        files = {"candidate.gds": inputs["layout"], "run.py": self.runner, "config.json": config}
        if "netlist" in inputs:
            files["reference.spice"] = inputs["netlist"]
        if self.support:
            files.update(self.support.mounted_files())
        # The runner always creates diagnostic files, even for a rejected GDS.
        exports = {"result.json": "json", "tool.log": "text"}
        if self.check != "artifact":
            exports.update({"report.db": "klayout-" + self.check, "complete.txt": "text"})
        if self.check == "lvs":
            exports["extracted.spice"] = "spice"
            exports["layer-map.json"] = "json"
        result = self.tool.run(["python", "run.py"], files, exports)
        evidence = {**(self.support.evidence() if self.support else {}), **result.evidence,
                    **result.files, "runner": self.runner, "configuration": config}
        if result.returncode != 0 or result.reason:
            return JobResult("error", result.reason or "KLayout runner did not complete", evidence=evidence)
        try:
            verdict = json.loads(result.files["result.json"].content)
            if verdict["status"] not in {"passed", "failed", "error"}:
                raise ValueError("Unknown verdict")
            outputs = {}
            if verdict["status"] == "passed" and job.outputs:
                database = result.files["report.db"]
                outputs = {"database": database, "binding": Asset(json.dumps({
                    "candidate_sha256": inputs["layout"].sha256, "database_sha256": database.sha256,
                    "top_cell": params["top_cell"], "layers": json.loads(result.files["layer-map.json"].content)}).encode(), "json")}
            return JobResult(verdict["status"], verdict["reason"], outputs=outputs, evidence=evidence)
        except (ValueError, KeyError, TypeError) as error:
            return JobResult("error", f"Invalid KLayout result: {error}", evidence=evidence)
