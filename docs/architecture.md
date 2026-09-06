# Architecture and Extension Interfaces

Layout-Bench measures an Agent's ability to turn authoritative netlists, constraints, and process resources into GDS. The system under test includes the model, prompt, context strategy, and tools; each measurement covers one task, one configuration, and one independent repetition. See the root [README](../README.md) for the current scope and next steps.

<a id="repositories"></a>

The public repository owns the common framework, public tasks, reference solutions, and qualification materials. Private assembles hidden tasks, dedicated materials, authorization, evaluation plans, and deployment configuration; the dependency direction is **Private → Public**. Public installation and CI do not depend on the private repository. Credentials and continually growing raw run artifacts live outside the repositories.

<a id="architecture"></a>

## From Run to Report

```mermaid
flowchart LR
    P[Task and Agent configuration / run plan] --> R[Runner freezes conditions]
    R --> A[Isolated Agent session]
    A -->|Explicit submission| C[Durable GDS snapshot]
    C --> E[Independent evaluator]
    T[Trusted task and tool materials] --> E
    R --> L[Durable records]
    E --> L
    L --> S[Statistics / optional restricted export]
```

| Responsibility | Code entry points | Boundary |
|---|---|---|
| Configuration and freezing | `tasks.py`, `model_config.py`, `provenance.py` | Validate inputs, configuration, files, and the actual execution identity; do not interpret the circuit |
| Run orchestration | `agent.py`, `swarm.py` | One execution and independent batch repetitions; invoke evaluation after stopping |
| Session and submission | `session.py`, `snapshot.py`, `submit.py` | Isolation, budgets, and the last valid submission; do not judge layout correctness |
| Model integration | `codex_cli.py`, `inference.py` | CLI integration, the fixed inference endpoint, and host credentials; no EDA dependency |
| Evaluation | `evaluation.py`, `evaluate.py`, `toolchains.py` | Execute each task's dependency graph, call backends, and decide metrics |
| EDA and materials | `klayout.py`, `geometry.py`, `magic.py`, `ngspice.py`; `prepare.py`, `environment.py`, `prepare_support.py` | Tool execution, format interpretation, resource preparation, and validation |
| Evidence and statistics | `recording.py`, `recorder.py`, `report.py`, `admission.py` | Durable events and artifacts, evidence binding, statistics, and optional admission/export |

These modules live under `benchmarking/` and are assembled by the root `main.py`. The Agent owns provider conversations and tool orchestration, the runner enforces external budgets, and the evaluator rejudges frozen candidates. Generated scripts, self-reported check results, and process logs cannot replace the final judge.

<a id="extension-layers"></a>

## Where to Change When Extending

- **New task**: add inputs, constraints, and an evaluation plan, then complete [qualification](tasks.md#qualification). Models, budgets, and repetitions belong to the [run configuration](running.md), not to `task.toml`.
- **New Agent**: use command/file configuration or add an adapter that produces the same interface. The current CLI manages model state itself; add a shared provider-runtime abstraction only when an actual consumer needs it.
- **New EDA backend**: implement `identity` and `run(job, inputs) -> JobResult`, returning measured values with units, declared artifacts, and diagnostic evidence. The backend owns execution isolation and format interpretation and may use a container, a native library, or a controlled remote tool.
- **New process or environment**: configure support bundles, device mappings, rules, and parameters, then validate the supported range using the [tools guide](tools.md). Individual tools being usable does not mean their combination has passed task qualification.

`evaluation.py` and `evaluate.py` do not import concrete tools; `tasks.py` depends only on evaluation data definitions. `toolchains.py` assembles backends at the entry point: `backends.<id>` declares `type` and `settings`, while `bindings` maps logical operations to backend IDs. Python callers may also inject a backend instance or factory. Task files cannot trigger dynamic Python imports; decks and file formats for different EDAs must be adapted explicitly.

A unified image serves preparation, solving, and judging, while each role runs in its own container. The host harness controls mounts, the inference endpoint, budgets, and trusted materials; the evaluator never sees Agent credentials or a writable workspace. A public development host may be controlled by the user; confidentiality for hidden data depends on a host controlled by the evaluator and cannot be provided by containers on the user's machine. See [admission and export](admission.md) for optional mechanisms and trust boundaries.

## Design Basis

The references below explain design choices; they are not execution rules or runtime dependencies for this project:

| Pinned source | What is borrowed and where it stops |
|---|---|
| [ARC-AGI-3 Benchmarking](https://github.com/arcprize/arc-agi-3-benchmarking/tree/1aa78da7e3058e0ead572ede7cd97065d1e5befc) | Adapters, exit reasons, and structured step-by-step records are useful; game actions, human baselines, and the scoring formula do not apply to layout. Its hidden-task access and official scoring depend on an external platform, so the local harness is not a complete hosted-service specification. |
| [SWE-bench harness](https://github.com/SWE-bench/SWE-bench/blob/02e7a74ffd0b707aab73d203fe87bdc7c76afc8e/docs/reference/harness.md) | Independent environments, execution limits, and machine-readable evidence are useful; caches still need to bind this project's candidate and judge inputs. |
| [VerilogEval](https://github.com/NVlabs/verilog-eval/blob/c498220d0a52248f8e3fdffe279075215bde2da6/README.md) | Fixed tools, sampling parameters, and result identity are useful; successful RTL simulation does not imply task success for layout. |

Use [tasks and evaluation](tasks.md) for actual decisions and the [running guide](running.md#scoring) for statistics. DRC/LVS are physical-validity gates; a complete task must also meet its declared geometry and post-layout requirements.
