"""Plans, independent repeats, frozen execution and recomputable statistics."""

import json
from dataclasses import replace

import pytest
from test_evaluate import PLAN, Checks, Extractor, Simulator

from benchmarking.agent import run_agent
from benchmarking.files import Asset
from benchmarking.provenance import (
    framework_files,
    snapshot_framework,
    verify_framework,
)
from benchmarking.recorder import RunRecorder
from benchmarking.recording import SessionResult
from benchmarking.report import summarize_batch, wilson
from benchmarking.swarm import execute_plan, load_plan

pytestmark = [pytest.mark.unit, pytest.mark.acceptance, pytest.mark.acceptance_fast]


def make_plan(root, *, repetitions=2, retries=0, tasks=3, agents=2):
    root.mkdir(exist_ok=True)
    for index in range(tasks):
        directory = root / f"task-{index}"
        directory.mkdir()
        files = {"netlist": (b"netlist", "spice"), "constraints": (b"{}", "json"), "evaluation": (PLAN, "toml")}
        source = f'''schema_version = 1
id = "t{index}"
title = "Synthetic batch fixture"
kind = "netlist_to_gds"
family = "{'a' if index < 2 else 'b'}"
status = "candidate"
environment = "synthetic"
[output]
path = "output/final.gds"
format = "gds"
top_cell = "SYNTHETIC"
max_bytes = 1024
'''
        for name, (content, file_format) in files.items():
            (directory / name).write_bytes(content)
            source += f'\n[inputs.{name}]\npath = "{name}"\nsha256 = "{Asset(content, file_format).sha256}"\nformat = "{file_format}"\n'
            if name == "netlist":
                source += 'subcircuit = "SYNTHETIC"\n'
        (directory / "task.toml").write_text(source)
    for index in range(agents):
        (root / f"agent-{index}.toml").write_text(f'''schema_version = 1
id = "agent-{index}"
image = "synthetic:tag"
command = ["fake"]
wall_seconds = 10
memory_mb = 128
cpus = 1
pids = 16
workspace_mb = 4
''')
    (root / "tools.toml").write_text('schema_version = 1\n[backends]\n[bindings]\n')
    source = f'''schema_version = 1
id = "test-plan"
scope = "synthetic"
repetitions = {repetitions}
order = "shuffled"
seed = 27
max_infrastructure_retries = {retries}
'''
    source += ''.join(f'\n[[tasks]]\nconfig = "task-{i}/task.toml"\ntoolchain = "tools.toml"\n' for i in range(tasks))
    source += ''.join(f'\n[[agents]]\nid = "c{i}"\nconfig = "agent-{i}.toml"\n' for i in range(agents))
    path = root / "plan.toml"
    path.write_text(source)
    return path


class FakeSession:
    def __init__(self, image):
        self.image_id = "sha256:frozen-image"

    def run(self, task, config, resources, message, *, recorder, inference=None):
        candidate = Asset(b"synthetic-layout", "gds") if task.id != "t2" and config.id == "agent-0" else None
        recorder.event("synthetic.session", task_id=task.id)
        receipts = []
        if candidate:
            ref = recorder.archive(candidate)
            receipts = [{"accepted": True, "sequence": 1, **candidate.identity()}]
            recorder.event("submission", receipt=receipts[0], candidate=ref)
        return SessionResult("completed", "", 1.0, 0, receipts, candidate, Asset(b"test", "text"), False,
                             {"image_id": self.image_id, **{key: getattr(config, key) for key in
                              ("wall_seconds", "memory_mb", "cpus", "pids", "workspace_mb")}})


def backends(_):
    return {"check": Checks(), "extract": Extractor(), "response": Simulator()}


def execute(path, destination, **kwargs):
    return execute_plan(load_plan(path), destination, session_factory=FakeSession, toolchain_loader=backends, **kwargs)


def test_cross_product_family_weights_and_recomputed_evidence(tmp_path):
    path = make_plan(tmp_path / "input")
    batch = execute(path, tmp_path / "run")
    assert batch["phase"] == "finished" and batch["outcome"] == "complete"
    assert len(batch["attempts"]) == 12
    groups = batch["summary"]["groups"]
    assert groups[0]["success_rate"] == .5  # Family a has two tasks; family b has one.
    assert groups[0]["task_equal_success_rate"] == pytest.approx(2/3)
    assert groups[1]["success_rate"] == 0
    assert groups[0]["tasks"]["t0"]["successful_metrics"]["delay"] == [{"value": 3, "unit": "s"}]*2
    assert groups[0]["tasks"]["t2"]["failure_modes"] == {"no_submission": 2}
    assert groups[1]["failure_modes"] == {"no_submission": 6}
    assert groups[0]["resources"]["measured"]["input_tokens"]["sum"] is None
    assert groups[0]["resources"]["measured"]["wall_seconds"]["sum"] == 6
    assert summarize_batch(tmp_path / "run") == batch["summary"]
    assert (tmp_path / "run").stat().st_mode & 0o777 == 0o700
    run = json.loads((tmp_path / "run" / batch["attempts"][0]["report"]["path"]).read_text())
    assert run["execution"]["execution_sha256"] == batch["execution"]["sha256"]
    assert run["environment"]["image_id"] == "sha256:frozen-image"
    with pytest.raises(FileExistsError):
        execute(path, tmp_path / "run")


def test_summary_retains_numeric_metrics_for_failed_candidates(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1)

    def failing_metrics(_):
        return {**backends(None), "response": Simulator(factor=2.0)}

    batch = execute_plan(load_plan(path), tmp_path / "run", session_factory=FakeSession,
                         toolchain_loader=failing_metrics)
    task = batch["summary"]["groups"][0]["tasks"]["t0"]
    assert task["successful_metrics"] == {}
    assert task["observed_metrics"]["delay"] == [{"value": 6.0, "unit": "s"}] * 2


def test_scheduling_is_frozen_and_failures_are_not_extra_samples(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1, retries=1)
    calls = []
    def runner(*args, **kwargs):
        calls.append(kwargs["execution"])
        if kwargs["execution"]["attempt"] == 1:
            raise OSError("synthetic secret must not enter records")
        return run_agent(*args, **kwargs)
    batch = execute(path, tmp_path / "run", runner=runner)
    group = batch["summary"]["groups"][0]
    assert group["tasks"]["t0"]["measured"] == 2
    assert group["attempts"] == 4 and group["infrastructure_errors"] == 2
    assert group["success_rate"] == 1
    assert group["resources"]["all_attempts"]["wall_seconds"]["sum"] is None
    assert all('secret' not in p.read_text() for p in (tmp_path/"run").glob("*.json"))
    assert [c["attempt"] for c in calls] == [1, 2, 1, 2]


def test_exhausted_replacements_keep_main_rate_missing(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1, retries=1)
    def broken(*args, **kwargs):
        raise OSError("unavailable")
    batch = execute(path, tmp_path / "run", runner=broken)
    assert batch["outcome"] == "incomplete"
    group = batch["summary"]["groups"][0]
    assert group["success_rate"] is None and group["tasks"]["t0"]["missing"] == 2
    assert group["infrastructure_errors"] == 4


def test_configured_inference_without_forwarded_request_is_labeled_offline(tmp_path):
    from benchmarking.inference import ResponsesGateway

    path = make_plan(tmp_path / "input", repetitions=1, tasks=1, agents=1)
    (path.parent / "inference.toml").write_text('''schema_version = 1
wire_api = "responses"
base_url = "https://example.invalid/v1"
model = "synthetic-model"
api_key_env = "UNUSED"
max_requests = 1
request_timeout_seconds = 5
''')
    path.write_text(path.read_text() + 'inference = "inference.toml"\n')

    def gateway(profile):
        return ResponsesGateway(
            profile,
            transport=lambda *args: (200, "application/json", b'{"status":"completed"}'),
        )

    batch = execute(path, tmp_path / "run", gateway_factory=gateway)
    group = batch["summary"]["groups"][0]
    assert group["run_kind"] == "offline_cli_development"
    assert group["configured_run_kind"] == "model_protocol_test"
    assert group["inference_requests"] == 0
    assert group["inference_unused_runs"] == 1


def test_evaluator_error_does_not_trigger_new_agent_attempt(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1, retries=2)
    def failing_backend(_):
        return {**backends(None), "check": Checks(crash="artifact")}
    batch = execute_plan(load_plan(path), tmp_path / "run", session_factory=FakeSession, toolchain_loader=failing_backend)
    group = batch["summary"]["groups"][0]
    assert group["evaluation_errors"] == 2 and group["attempts"] == 2
    assert not group["complete"] and group["success_rate"] is None


@pytest.mark.parametrize("before,after", [('repetitions = 2', 'repetitions = true'),
                                         ('seed = 27', 'seed = -1'),
                                         ('scope = "synthetic"', 'scope = "official"'),
                                         ('order = "shuffled"', 'order = "adaptive"'),
                                         ('id = "c1"', 'id = "c0"')])
def test_invalid_plans_fail_before_execution(tmp_path, before, after):
    path = make_plan(tmp_path / "input")
    path.write_text(path.read_text().replace(before, after))
    with pytest.raises(ValueError):
        load_plan(path)


def test_duplicate_tasks_fail_before_any_solver_runs(tmp_path):
    path = make_plan(tmp_path / "input")
    plan = load_plan(path)
    plan = replace(plan, tasks=(plan.tasks[0], plan.tasks[0]))
    with pytest.raises(ValueError, match="Duplicate task"):
        execute_plan(plan, tmp_path / "run", session_factory=FakeSession, toolchain_loader=backends)
    assert not (tmp_path / "run").exists()


def test_source_snapshots_include_uncommitted_code_but_exclude_local_assets(tmp_path):
    root = tmp_path / "framework"
    (root / "benchmarking").mkdir(parents=True)
    for name in ("main.py", "Dockerfile", "pyproject.toml", "uv.lock", "benchmarking/new.py"):
        (root / name).write_text("original")
    (root / ".env").write_text("synthetic credential")
    (root / "hidden-task.toml").write_text("not framework")
    recorder = RunRecorder(tmp_path / "record")
    snapshot = snapshot_framework(recorder.archive, root)
    assert set(framework_files(root)) == {"main.py", "Dockerfile", "pyproject.toml", "uv.lock", "benchmarking/new.py"}
    verify_framework(snapshot, root)
    (root / "benchmarking/new.py").write_text("modified")
    with pytest.raises(ValueError, match="source changed"):
        verify_framework(snapshot, root)


def test_tampered_run_is_not_silently_counted(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1)
    batch = execute(path, tmp_path / "run")
    report_path = tmp_path / "run" / batch["attempts"][0]["report"]["path"]
    report_path.write_text('{}')
    with pytest.raises(ValueError, match="integrity"):
        summarize_batch(tmp_path / "run")


def _replace_evaluation_report(run_root, batch, mutate):
    """Rewrite all local references after a deliberate evidence mutation."""
    attempt = batch["attempts"][0]
    attempt_root = run_root / attempt["path"]
    evaluation_path = attempt_root / "evaluation/report.json"
    evaluation = json.loads(evaluation_path.read_text())
    mutate(evaluation, attempt_root / "evaluation")
    evaluation_path.write_text(json.dumps(evaluation, indent=2) + "\n")
    evaluation_ref = {**Asset(evaluation_path.read_bytes(), "json").identity(),
                      "path": "evaluation/report.json"}
    run_path = attempt_root
    report = json.loads((run_path / "run.json").read_text())
    report["evaluation"].update(sha256=evaluation_ref["sha256"], bytes=evaluation_ref["bytes"])
    (run_path / "run.json").write_text(json.dumps(report, indent=2) + "\n")
    report_ref = {**Asset((run_path / "run.json").read_bytes(), "json").identity(),
                  "path": attempt["report"]["path"]}
    attempt["report"] = report_ref
    (run_root / "batch.json").write_text(json.dumps(batch, indent=2) + "\n")


def test_replaced_evaluation_plan_is_not_silently_counted(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1)
    batch = execute(path, tmp_path / "run")

    def replace_plan(evaluation, evaluation_root):
        alternate = Asset(PLAN + b"\n", "toml")
        artifact = evaluation_root / "artifacts" / alternate.sha256
        artifact.write_bytes(alternate.content)
        artifact.chmod(0o400)
        evaluation["plan"] = {**alternate.identity(), "path": f"artifacts/{alternate.sha256}"}

    _replace_evaluation_report(tmp_path / "run", batch, replace_plan)
    with pytest.raises(ValueError, match="Evaluation plan"):
        summarize_batch(tmp_path / "run")


def test_replaced_evaluation_input_is_not_silently_counted(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1)
    batch = execute(path, tmp_path / "run")

    def replace_input(evaluation, _evaluation_root):
        evaluation["inputs"]["input:netlist"] = evaluation["inputs"]["candidate"]

    _replace_evaluation_report(tmp_path / "run", batch, replace_input)
    with pytest.raises(ValueError, match="Evaluation inputs"):
        summarize_batch(tmp_path / "run")


def test_wilson_intervals_include_extreme_outcome_uncertainty():
    assert wilson(0, 0) is None
    assert wilson(0, 3)[1] == pytest.approx(.5614970317550454)
    assert wilson(3, 3)[0] == pytest.approx(.4385029682449546)
    assert wilson(5, 10) == pytest.approx([.236593090512564, .763406909487436])
    with pytest.raises(ValueError):
        wilson(4, 3)


def test_changed_configuration_inputs_do_not_change_later_repeats(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1)
    calls = []
    def runner(task, config, resources, tools, destination, **kwargs):
        calls.append((task.inputs[0].content, config.source.sha256, kwargs["session"].image_id))
        (path.parent / "agent-0.toml").write_text("changed after preflight")
        (path.parent / "task-0/netlist").write_text("changed after preflight")
        (path.parent / "tools.toml").write_text("changed after preflight")
        return run_agent(task, config, resources, tools, destination, **kwargs)
    batch = execute(path, tmp_path / "run", runner=runner)
    assert batch["summary"]["complete"] and len(calls) == 2
    assert calls[0] == calls[1]
    assert calls[0][0] == b"netlist"


def test_partial_batch_does_not_silently_shrink_denominator(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1)
    calls = 0
    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return run_agent(*args, **kwargs)
    with pytest.raises(KeyboardInterrupt):
        execute(path, tmp_path / "run", runner=interrupted)
    summary = summarize_batch(tmp_path / "run")
    group = summary["groups"][0]
    assert group["tasks"]["t0"]["measured"] == 1
    assert group["tasks"]["t0"]["missing"] == 1
    assert group["tasks"]["t0"]["observed_success_rate"] == 1
    assert group["success_rate"] is None and summary["complete"] is False


def test_unfinished_batch_cannot_be_summarized_as_complete(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1)
    batch = execute(path, tmp_path / "run")
    batch["phase"] = "running"
    batch["summary"] = None
    (tmp_path / "run" / "batch.json").write_text(json.dumps(batch, indent=2) + "\n")
    with pytest.raises(ValueError, match="not finished"):
        summarize_batch(tmp_path / "run")


def test_interrupted_batch_can_only_be_summarized_when_coverage_is_incomplete(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1)
    batch = execute(path, tmp_path / "run")
    batch["phase"] = "running"
    batch["summary"] = None
    (tmp_path / "run" / "batch.json").write_text(json.dumps(batch, indent=2) + "\n")
    # Clearing the summary must not make a fully covered, unsealed batch look
    # like a final score.
    with pytest.raises(ValueError, match="not finished"):
        summarize_batch(tmp_path / "run")


def test_mutated_runtime_environment_stops_the_batch(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1)
    class ChangedImage(FakeSession):
        def run(self, *args, **kwargs):
            self.image_id = "sha256:different-image"
            return super().run(*args, **kwargs)
    with pytest.raises(ValueError, match="frozen execution"):
        execute_plan(load_plan(path), tmp_path / "run", session_factory=ChangedImage, toolchain_loader=backends)
    batch = json.loads((tmp_path / "run/batch.json").read_text())
    assert batch["phase"] == "running" and len(batch["attempts"]) == 1


def test_source_snapshot_records_dirty_git_identity(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1)
    execute(path, tmp_path / "run")
    manifest = json.loads((tmp_path / "run/execution.json").read_text())
    assert manifest["framework"]["git"]["commit"]
    assert "benchmarking/swarm.py" in manifest["framework"]["files"]
    assert manifest["framework"]["files"]["benchmarking/swarm.py"]["sha256"]


def test_qualified_task_label_does_not_turn_development_into_official_score(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1)
    task_path = path.parent / "task-0/task.toml"
    task_path.write_text(task_path.read_text().replace('status = "candidate"', 'status = "qualified"'))
    batch = execute(path, tmp_path / "run")
    assert batch["run_kind"] == "local_batch_development"
    assert batch["summary"]["scope"] == "synthetic"


def test_different_toolchain_identities_are_not_pooled(tmp_path):
    path = make_plan(tmp_path / "input", tasks=3, agents=1)
    first = backends(None)
    second = backends(None)
    second["check"].identity = {"adapter": "other-synthetic-checks", "version": "1"}
    count = 0
    def loader(_):
        nonlocal count
        count += 1
        return second if count == 3 else first
    batch = execute_plan(load_plan(path), tmp_path / "run", session_factory=FakeSession, toolchain_loader=loader)
    assert len(batch["summary"]["groups"]) == 2
    assert sorted(g["success_rate"] for g in batch["summary"]["groups"]) == [0, 1]


def test_each_repeat_has_a_fresh_gateway_and_protocol_results_stay_labelled(tmp_path):
    import time

    from benchmarking.inference import ResponsesGateway

    path = make_plan(tmp_path / "input", tasks=1, agents=1)
    (path.parent / "inference.toml").write_text('''schema_version = 1
wire_api = "responses"
base_url = "https://example.invalid/v1"
model = "synthetic-model"
api_key_env = "UNUSED"
max_requests = 1
request_timeout_seconds = 5
''')
    path.write_text(path.read_text() + 'inference = "inference.toml"\n')
    gateways = []
    def factory(profile):
        gateway = ResponsesGateway(profile, transport=lambda *a: (
            200, "application/json", b'{"status":"completed","usage":{"input_tokens":7,"output_tokens":2}}'))
        gateways.append(gateway)
        return gateway
    class ModelSession(FakeSession):
        def run(self, *args, inference, **kwargs):
            inference.deadline = time.monotonic() + 10
            assert inference.request("/responses", b'{"model":"synthetic-model"}')[0] == 200
            inference.stop()
            return super().run(*args, inference=inference, **kwargs)
    batch = execute_plan(load_plan(path), tmp_path / "run", session_factory=ModelSession,
                         toolchain_loader=backends, gateway_factory=factory)
    assert [len(g.events) for g in gateways] == [0, 1, 1]
    group = batch["summary"]["groups"][0]
    assert group["run_kind"] == "model_protocol_test"
    assert group["resources"]["all_attempts"]["input_tokens"]["sum"] == 14
    assert group["inference_forwarded_requests"] == 2
    assert group["inference_denied_requests"] == 0
    assert group["inference_failed_requests"] == 0
    assert group["inference_truncated_requests"] == 0
    assert group["inference_usage"]["input_tokens"] == {"known": 2, "missing": 0, "total": 14}


def test_corrupted_candidate_blocks_statistics_even_when_reports_are_intact(tmp_path):
    path = make_plan(tmp_path / "input", tasks=1, agents=1)
    batch = execute(path, tmp_path / "run")
    root = tmp_path / "run" / batch["attempts"][0]["path"]
    report = json.loads((root / "run.json").read_text())
    candidate = root / report["candidate"]["path"]
    candidate.chmod(0o600)
    candidate.write_bytes(b"damaged")
    with pytest.raises(ValueError, match="integrity"):
        summarize_batch(tmp_path / "run")
