"""ngspice batch adapter; simulator syntax stays outside the evaluation core."""

import re
from pathlib import Path

from .bundles import load_bundle
from .docker import DockerTool
from .evaluate import JobResult, Measurement
from .evaluation import Job, identifier, number
from .files import Asset, keys, relative


class NgspiceDocker:
    """Each input role becomes <role>.spice; deck owns analyses and measurements.

    Optional support is a verified snapshot of models, compiled libraries and
    startup settings. It is supplied by tool configuration, independent of tasks.
    """

    def __init__(self, *, image: str, timeout_seconds: float = 60, support: str | None = None):
        self.support = load_bundle(Path(support)) if support else None
        self.tool = DockerTool(image, ["ngspice", "--version"], timeout_seconds)

    @property
    def identity(self) -> dict:
        return {"adapter": "ngspice-docker",
                "adapter_sha256": Asset(Path(__file__).read_bytes(), "python").sha256,
                **self.tool.identity,
                "support_sha256": self.support.manifest.sha256 if self.support else None}

    def run(self, job: Job, inputs: dict[str, Asset]) -> JobResult:
        if job.stage != "simulate" or "deck" not in inputs:
            raise ValueError("ngspice requires a simulate job with a deck input")
        params = job.parameters
        keys(params, {"measurements"}, {"values", "exports"}, "ngspice parameters")
        units, values, exports = params["measurements"], params.get("values", {}), params.get("exports", {})
        if not isinstance(units, dict) or not units:
            raise ValueError("ngspice needs named measurements with units")
        if not isinstance(values, dict) or not isinstance(exports, dict):
            raise TypeError("values and exports must be tables")
        for name, unit in units.items():
            identifier(name)
            if not isinstance(unit, str) or not unit:
                raise ValueError("Measurement unit must be a nonempty string")
        if set(exports) != set(dict(job.outputs)) or len(set(exports.values())) != len(exports):
            raise ValueError("ngspice exports must match unique declared job outputs")
        for path in exports.values():
            relative(path, "ngspice export")
            if path == "ngspice.log":
                raise ValueError("ngspice.log is reserved for evidence")
        files = {}
        for name, asset in inputs.items():
            identifier(name)
            if name == "parameters" or asset.format != "spice":
                raise ValueError("ngspice inputs must be SPICE; parameters is a reserved role")
            files[f"{name}.spice"] = asset
        assignments = "".join(f".param {identifier(k)}={number(v):.17g}\n" for k, v in values.items())
        files["parameters.spice"] = Asset(assignments.encode(), "spice")
        evidence = {"parameters": files["parameters.spice"]}
        environment = {}
        if self.support:
            files.update(self.support.mounted_files())
            evidence.update(self.support.evidence())
            environment["SPICE_USERINIT_DIR"] = "/workspace/support"
        requested = {"ngspice.log": "text", **{path: dict(job.outputs)[name] for name, path in exports.items()}}
        result = self.tool.run(["ngspice", "-b", "-o", "ngspice.log", "deck.spice"],
                               files, requested, environment=environment)
        evidence.update(result.evidence)
        if "ngspice.log" in result.files:
            evidence["log"] = result.files["ngspice.log"]
        if result.reason or result.returncode != 0:
            return JobResult("error", result.reason or "ngspice did not complete", evidence=evidence)
        measurements = {}
        log = result.files["ngspice.log"].content.decode("utf-8", errors="replace")
        # Failed .measure may coexist with exit code 0. Require each finite scalar.
        for name, unit in units.items():
            matches = re.findall(rf"^\s*{re.escape(name)}\s*=\s*(\S+)", log,
                                 flags=re.MULTILINE | re.IGNORECASE)
            if len(matches) != 1:
                return JobResult("error", f"Missing/ambiguous ngspice measurement: {name}", evidence=evidence)
            try:
                value = number(float(matches[0]))
            except ValueError:
                return JobResult("error", f"Invalid ngspice measurement: {name}", evidence=evidence)
            measurements[name] = Measurement(value, unit)
        combined = log + "\n" + result.evidence["console"].content.decode("utf-8", errors="replace")
        if re.search(r"^\s*(?:fatal|error)\b|simulation interrupted|timestep too small|unknown model type",
                     combined, flags=re.MULTILINE | re.IGNORECASE):
            return JobResult("error", "ngspice reported an execution or model error", evidence=evidence)
        return JobResult("passed", measurements=measurements,
                         outputs={name: result.files[path] for name, path in exports.items()}, evidence=evidence)
