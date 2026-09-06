"""Synthetic hidden data exercises operator pins, admission and aggregate-only release."""

import json

import pytest
from admission_helpers import SECRET, approve, save_policy
from test_swarm import FakeSession, backends, execute, make_plan

from benchmarking.admission import (
    export_batch,
    load_policy,
)
from benchmarking.files import Asset
from benchmarking.provenance import json_asset
from benchmarking.report import summarize_batch
from benchmarking.swarm import execute_plan, load_plan

pytestmark = pytest.mark.unit

def setup(tmp_path, **plan_options):
    path = make_plan(tmp_path / "input", **plan_options)
    prepared = execute(path, tmp_path / "prepared", prepare_only=True)
    manifest = json.loads((tmp_path / "prepared" / "execution.json").read_text())
    assert prepared["outcome"] == "prepared" and prepared["attempts"] == []
    assert not (tmp_path / "prepared" / "runs").exists()
    root = tmp_path / "operator"
    return path, root, approve(root, manifest), manifest


def test_pinned_admission_complete_run_and_whitelist_export(tmp_path):
    path, root, data, _ = setup(tmp_path)
    policy = save_policy(root, data)
    seen = []

    class Isolated(FakeSession):
        def run(self, task, config, resources, message, **kwargs):
            seen.append(task.id)
            assert SECRET not in message
            assert all(SECRET.encode() not in item.content for item in task.inputs)
            assert all(SECRET.encode() not in asset.content for asset in resources.values())
            return super().run(task, config, resources, message, **kwargs)

    result = execute_plan(load_plan(path), tmp_path / "run", policy=policy,
                          session_factory=Isolated, toolchain_loader=backends)
    assert len(seen) == 12 and result["outcome"] == "complete"
    assert summarize_batch(tmp_path / "run") == result["summary"]
    released = export_batch(tmp_path / "run", policy.source.sha256)
    assert [g["success_rate"] for g in released["groups"]] == [.5, 0]
    assert released["dataset"] == "synthetic_hidden"
    assert all(g["run_kind"] == "offline_cli_development" for g in released["groups"])
    assert all(set(g) == {"label", "run_kind", "task_count", "family_count", "trials", *data["export"]["fields"]}
               for g in released["groups"])
    raw = json.dumps(released)
    assert SECRET not in raw and '"t0"' not in raw and "successful_metrics" not in raw
    assert "environment_group" not in raw and "sha256" not in raw and "resources" not in raw
    reservation = json.loads((root / "ledger" / (policy.source.sha256 + ".json")).read_text())
    assert reservation == result["admission_reservation"]
    assert (root / "ledger" / (policy.source.sha256 + ".json")).stat().st_mode & 0o777 == 0o600
    assert export_batch(tmp_path / "run", policy.source.sha256) == released
    with pytest.raises(FileExistsError):
        execute(path, tmp_path / "duplicate", policy=policy)
    assert not (tmp_path / "duplicate" / "runs").exists()


@pytest.mark.parametrize("change", ["plan", "image", "budget", "command", "agent_file", "task", "tools"])
def test_changed_conditions_stop_before_solver_access(tmp_path, change):
    path, root, data, _ = setup(tmp_path)
    policy = save_policy(root, data)
    if change == "plan":
        path.write_text(path.read_text().replace("repetitions = 2", "repetitions = 3"))
    elif change in {"image", "budget", "command", "agent_file"}:
        agent = path.parent / "agent-0.toml"
        if change == "agent_file":
            (path.parent / "extra.py").write_text(SECRET)
            agent.write_text(agent.read_text() + f'\n[[files]]\npath="extra.py"\ntarget="extra.py"\nsha256="{Asset(SECRET.encode(), "binary").sha256}"\n')
        else:
            before, after = {"image": ('synthetic:tag', 'another:tag'), "budget": ('wall_seconds = 10', 'wall_seconds = 11'),
                             "command": ('["fake"]', '["other"]')}[change]
            agent.write_text(agent.read_text().replace(before, after))
    elif change == "task":
        task = path.parent / "task-0/task.toml"
        task.write_text(task.read_text().replace('status = "candidate"', 'status = "qualified"'))
    else:
        tools = path.parent / "tools.toml"
        tools.write_text(tools.read_text() + "# different tools\n")
    def forbidden(*args, **kwargs):
        pytest.fail("Denied execution started a solver")
    with pytest.raises(ValueError, match="conditions were not approved"):
        execute(path, tmp_path / "denied", policy=policy, runner=forbidden)
    assert not list((root / "ledger").iterdir())


@pytest.mark.parametrize("bad", ["missing", "task", "tools", "framework", "witness", "geometry", "performance"])
def test_scoped_qualification_required_even_with_operator_policy_pin(tmp_path, bad):
    path, root, data, _ = setup(tmp_path)
    reference = data["tasks"]["t0"]["qualification"]
    evidence = root / reference["path"]
    record = json.loads(evidence.read_text())
    if bad == "missing":
        del record["checks"]["calibration"]
    elif bad in {"task", "tools", "framework"}:
        record[{"task": "task_sha256", "tools": "backends_sha256", "framework": "framework_sha256"}[bad]] = "0"*64
    else:
        record["checks"][{"witness": "witness", "geometry": "invalid_geometry", "performance": "invalid_performance"}[bad]] = False
    asset = json_asset(record)
    evidence.write_bytes(asset.content)
    reference["sha256"] = asset.sha256
    policy = save_policy(root, data)
    with pytest.raises(ValueError, match="[Qq]ualification"):
        execute(path, tmp_path / "denied", policy=policy)
    assert not list((root / "ledger").iterdir())


def test_pin_evidence_expiry_and_ledger_permissions(tmp_path):
    path, root, data, _ = setup(tmp_path)
    policy = save_policy(root, data)
    with pytest.raises(ValueError, match="operator pin"):
        load_policy(root / "policy.json", "0"*64)
    (root / "authorization.txt").write_text("altered")
    with pytest.raises(ValueError, match="evidence integrity"):
        load_policy(root / "policy.json", policy.source.sha256)
    # Loaded evidence is immutable; the frozen original is still what would be used.
    (root / "ledger").chmod(0o755)
    with pytest.raises(ValueError, match="private permissions"):
        execute(path, tmp_path / "denied", policy=policy)
    (root / "ledger").chmod(0o700)
    data["valid_until"] = "2000-01-01T00:00:00+00:00"
    expired = type(policy)(json_asset(data), policy.evidence)
    with pytest.raises(ValueError, match="expired"):
        execute(path, tmp_path / "expired", policy=expired)
    assert not (tmp_path / "expired").exists()


@pytest.mark.parametrize("threshold", ["min_tasks", "min_families", "min_trials"])
def test_small_groups_suppressed_and_repetitions_do_not_replace_diversity(tmp_path, threshold):
    path, root, data, _ = setup(tmp_path)
    data["export"][threshold] = 100
    policy = save_policy(root, data)
    execute(path, tmp_path / "run", policy=policy)
    assert export_batch(tmp_path / "run", policy.source.sha256)["groups"] == []


@pytest.mark.parametrize("field", ["tasks", "successful_metrics", "resources", "environment_group", "prompt"])
def test_unknown_export_fields_rejected_before_execution(tmp_path, field):
    _, root, data, _ = setup(tmp_path)
    data["export"]["fields"].append(field)
    with pytest.raises(ValueError, match="whitelist"):
        save_policy(root, data)


def test_incomplete_or_unapproved_runs_cannot_be_exported(tmp_path):
    path, root, data, _ = setup(tmp_path)
    policy = save_policy(root, data)
    def broken(*args, **kwargs):
        raise OSError(SECRET)
    execute(path, tmp_path / "run", policy=policy, runner=broken)
    with pytest.raises(ValueError, match="Incomplete"):
        export_batch(tmp_path / "run", policy.source.sha256)
    execute(path, tmp_path / "development")
    with pytest.raises(ValueError, match="no frozen admission"):
        export_batch(tmp_path / "development", policy.source.sha256)


def test_export_uses_original_frozen_policy_not_posthoc_looser_rules(tmp_path):
    path, root, data, _ = setup(tmp_path)
    policy = save_policy(root, data)
    execute(path, tmp_path / "run", policy=policy)
    data["export"]["min_trials"] = 2
    altered = save_policy(root, data)
    with pytest.raises(ValueError, match="operator export pin"):
        export_batch(tmp_path / "run", altered.source.sha256)
    assert export_batch(tmp_path / "run", policy.source.sha256)["groups"]
    archived = tmp_path / "run" / "artifacts" / policy.source.sha256
    archived.chmod(0o600)
    archived.write_bytes(altered.source.content)
    with pytest.raises(ValueError, match="evidence integrity"):
        export_batch(tmp_path / "run", policy.source.sha256)


@pytest.mark.parametrize("bad", [None, "missing", "url", "model", "no_training", "zero_data_retention", "authorization"])
def test_endpoint_requires_exact_reviewed_data_arrangement(tmp_path, bad):
    import time

    from benchmarking.inference import ResponsesGateway

    path = make_plan(tmp_path / "input", agents=1)
    (path.parent / "inference.toml").write_text('''schema_version = 1
base_url = "https://example.invalid/v1"
model = "synthetic-model"
api_key_env = "UNUSED"
max_requests = 1
request_timeout_seconds = 5
''')
    path.write_text(path.read_text() + 'inference = "inference.toml"\n')
    calls = []
    def transport(*args):
        calls.append(args)
        return 200, "application/json", b'{"status":"completed","usage":{"input_tokens":7,"output_tokens":2}}'
    def factory(profile):
        return ResponsesGateway(profile, transport=transport)
    class ModelSession(FakeSession):
        def run(self, *args, inference, **kwargs):
            inference.deadline = time.monotonic() + 10
            assert inference.request("/responses", b'{"model":"synthetic-model"}')[0] == 200
            inference.stop()
            return super().run(*args, inference=inference, **kwargs)
    execute(path, tmp_path / "prepared", prepare_only=True, gateway_factory=factory)
    assert not calls
    manifest = json.loads((tmp_path / "prepared/execution.json").read_text())
    root = tmp_path / "operator"
    data = approve(root, manifest)
    endpoint = {"provider": "deterministic-fixture", "base_url": "https://example.invalid/v1",
                "model": "synthetic-model", "no_training": True, "zero_data_retention": True,
                "authorization": data["tasks"]["t0"]["authorization"]}
    data["agents"]["c0"]["endpoint"] = endpoint
    if bad == "missing":
        data["agents"]["c0"]["endpoint"] = None
    elif bad in {"url", "model"}:
        endpoint["base_url" if bad == "url" else "model"] = "different"
    elif bad in {"no_training", "zero_data_retention"}:
        endpoint[bad] = False
    elif bad == "authorization":
        endpoint["authorization"] = {"path": "missing", "sha256": "0"*64}
    def run():
        policy = save_policy(root, data)
        result = execute_plan(load_plan(path), tmp_path / "run", policy=policy,
                              session_factory=ModelSession, toolchain_loader=backends, gateway_factory=factory)
        return policy, result
    if bad:
        with pytest.raises((ValueError, OSError)):
            run()
        assert not calls
        assert not list((root / "ledger").iterdir())
    else:
        policy, result = run()
        assert len(calls) == 6 and result["outcome"] == "complete"
        assert export_batch(tmp_path / "run", policy.source.sha256)["groups"][0]["run_kind"] == "model_protocol_test"


def test_new_bundle_content_requires_resource_review_even_if_plan_is_reapproved(tmp_path):
    from benchmarking.admission import conditions
    from benchmarking.bundles import publish_bundle

    path = make_plan(tmp_path / "input", agents=1)
    bundle = path.parent / "resources"
    publish_bundle({"generic.txt": Asset(b"approved generic help", "text")}, {"source": "synthetic"}, bundle)
    path.write_text(path.read_text() + 'resources = "resources"\n')
    execute(path, tmp_path / "prepared", prepare_only=True)
    manifest = json.loads((tmp_path / "prepared/execution.json").read_text())
    root = tmp_path / "operator"
    data = approve(root, manifest)
    raw = json.loads((bundle / "manifest.json").read_text())
    changed = Asset(SECRET.encode(), "text")
    for filename in ("generic.txt", "manifest.json"):
        (bundle / filename).chmod(0o600)
    (bundle / "generic.txt").write_bytes(changed.content)
    raw["files"]["generic.txt"] = changed.identity()
    (bundle / "manifest.json").write_bytes(json_asset(raw).content)
    execute(path, tmp_path / "changed", prepare_only=True)
    updated = json.loads((tmp_path / "changed/execution.json").read_text())
    data["conditions_sha256"] = json_asset(conditions(updated)).sha256
    policy = save_policy(root, data)
    with pytest.raises(ValueError, match="Agent resources"):
        execute(path, tmp_path / "denied", policy=policy)
    assert not list((root / "ledger").iterdir())


def test_interrupted_batch_consumes_admission_before_first_solver_input(tmp_path):
    path, root, data, _ = setup(tmp_path)
    policy = save_policy(root, data)
    def interrupted(*args, **kwargs):
        assert (root / "ledger" / (policy.source.sha256 + ".json")).exists()
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        execute(path, tmp_path / "run", policy=policy, runner=interrupted)
    assert summarize_batch(tmp_path / "run")["complete"] is False
    with pytest.raises(FileExistsError):
        execute(path, tmp_path / "rerun", policy=policy)
    with pytest.raises(ValueError, match="finished"):
        export_batch(tmp_path / "run", policy.source.sha256)


def test_task_pool_exposure_cannot_be_relabelled(tmp_path):
    path, root, data, _ = setup(tmp_path)
    data["exposure_mode"] = "external_api"
    policy = save_policy(root, data)
    with pytest.raises(ValueError, match="exposure mode"):
        execute(path, tmp_path / "denied", policy=policy)
    assert not list((root / "ledger").iterdir())


@pytest.mark.parametrize("bad", ["public-source", "dataset", "task-coverage", "agent-coverage", "duplicate-group", "small-threshold"])
def test_policy_cannot_infer_hidden_rights_or_relax_coverage(tmp_path, bad):
    path, root, data, _ = setup(tmp_path)
    if bad == "public-source":
        data["tasks"]["t0"]["source_kind"] = "public"
    elif bad == "dataset":
        data["dataset"] = "hidden"
        for task in data["tasks"].values():
            task["source_kind"] = "independent_unpublished"
    elif bad == "task-coverage":
        del data["tasks"]["t0"]
    elif bad == "agent-coverage":
        del data["agents"]["c0"]
    elif bad == "duplicate-group":
        data["export"]["groups"].append(data["export"]["groups"][0])
    else:
        data["export"]["min_tasks"] = 1
    with pytest.raises(ValueError):
        execute(path, tmp_path / "denied", policy=save_policy(root, data))
    assert not list((root / "ledger").iterdir())


def test_concurrent_reservations_have_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from benchmarking.admission import reserve

    _, root, data, _ = setup(tmp_path)
    policy = save_policy(root, data)
    def attempt():
        try:
            return reserve(policy, "1"*64)
        except FileExistsError:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: attempt(), range(4)))
    assert sum(result is not None for result in results) == 1
    assert len(list((root / "ledger").iterdir())) == 1
