"""Operator attestations for synthetic tests only; these are never task qualifications."""

from datetime import UTC, datetime, timedelta

from benchmarking.admission import QUALIFICATION_CHECKS, conditions, load_policy
from benchmarking.files import Asset
from benchmarking.provenance import json_asset

SECRET = "SYNTHETIC_HIDDEN_REFERENCE_DO_NOT_RELEASE"


def approve(root, manifest, **export_options):
    root.mkdir(exist_ok=True)
    ledger = root / "ledger"
    ledger.mkdir(mode=0o700, exist_ok=True)

    def evidence(name, content):
        (root / name).write_bytes(content)
        return {"path": name, "sha256": Asset(content, "binary").sha256}

    authorization = evidence("authorization.txt", f"Synthetic operator authorization: {SECRET}".encode())
    tasks = {}
    for task_id, task in manifest["tasks"].items():
        qualification = {"schema_version": 1, "task_sha256": task["task_sha256"],
                         "backends_sha256": json_asset(task["backends"]).sha256,
                         "framework_sha256": manifest["framework"]["sha256"],
                         "checks": dict.fromkeys(QUALIFICATION_CHECKS, True), "review": SECRET}
        tasks[task_id] = {"source_kind": "synthetic", "authorization": authorization,
                          "materials": [evidence(task_id + "-evidence.txt", (SECRET + " synthetic qualification fixture").encode())],
                          "qualification": evidence(task_id + ".json", json_asset(qualification).content)}
    data = {"schema_version": 1, "id": "synthetic-release", "dataset": "synthetic_hidden",
            "exposure_mode": "external_api" if any(a["inference"] for a in manifest["agents"].values()) else "offline",
            "conditions_sha256": json_asset(conditions(manifest)).sha256,
            "valid_until": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "ledger": str(ledger), "tasks": tasks,
            "agents": {key: {"conditions_sha256": json_asset(agent).sha256,
                              "resource_review": authorization, "endpoint": None}
                       for key, agent in manifest["agents"].items()},
            "export": {"fields": ["success_rate", "physical_valid_rate", "infrastructure_error_rate"],
                       "min_tasks": 3, "min_families": 2, "min_trials": 6, "decimals": 2,
                       "groups": [{"configuration_id": key, "environment_group": group,
                                   "label": f"system-{i}-environment-{j}"}
                                  for i, key in enumerate(manifest["agents"])
                                  for j, group in enumerate(sorted({t["environment_group"] for t in manifest["tasks"].values()}))],
                       **export_options}}
    return data


def save_policy(root, data):
    path = root / "policy.json"
    asset = json_asset(data)
    path.write_bytes(asset.content)
    return load_policy(path, asset.sha256)
