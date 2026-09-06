# Running Agents, Batch Evaluation, and Interpreting Results

First complete the no-key quick start in the root [README](../README.md#quick-start-no-model-key-required), then use the generated configuration to connect your own harness or model gateway. One measurement is one task × one Agent configuration × one independent repetition; the harness, model, prompt, context, and tools together form the system under test.

<a id="protocol"></a>

Tools, materials, input modalities, and budgets are measurement conditions. Record a configuration difference whenever you add a layout generator, retrieval library, skill, or image-observation capability. There is not yet a unified same-semantic process-check entry point. The final judge runs independently after the session stops and does not choose the best intermediate candidate for the Agent. See [tasks and evaluation](tasks.md#evaluation) for the decisions.

<a id="offline-cli"></a>

## 1. Configure and Run One Agent

`main.py run <task.toml> --agent <agent.toml> --toolchain <toolchain.toml> --output <new-directory>` starts one offline development run. See [examples/agents](../examples/agents/README.md) for executable configurations and protocol probes that are expected to fail evaluation. `--resources <bundle>` may provide a reviewed, frozen resource bundle; the CLI does not read an arbitrary resource directory or a complete upstream checkout. Image and resource preparation and final evaluation are outside solve time. Timing starts before launching the prepared container and making the task message readable, so it includes a small amount of startup overhead.

The current Agent configuration is schema 1:

| Field | Semantics |
|---|---|
| `id`, `image`, `command` | Named harness process, tool image, and an argument list that is not expanded by a host shell; record the actual image ID and override the image's default entrypoint |
| `[harness]` | Optional `id`, `version`, `protocol`, `mode`, `capabilities`, and `wire_api`; the current protocol is `layout-session.v1`, with defaults `external-cli` and `opaque` |
| `wall_seconds`, `memory_mb`, `cpus`, `pids`, `workspace_mb` | Positive external runtime limits; the configuration does not claim enforceable token or cost caps |
| `files[]` | `path`, `target`, and `sha256`; validate ordinary files at load time, freeze them, and mount them read-only under `/agent` |
| `environment` | Optional public string settings archived verbatim; never use them for credentials |

For each session, the Runner prepares separate read-only `/task`, `/agent`, `/resources`, and `/protocol` mounts. `/protocol/harness.json` publishes the frozen session protocol and declared capabilities; it does not grant extra authority. With inference configured, `/protocol/inference.json` describes the fixed gateway and `/protocol/inference.sock` is its canonical Unix socket; the former `/protocol/model.sock` path remains a compatibility alias. The Runner does not mount the host repository, Docker socket, or evaluation support directories. `/workspace` is a size-limited tmpfs and starts empty; the root filesystem is read-only, with a fixed 64 MiB `/tmp` and 16 MiB shared memory. Containers run as non-root, with networking disabled, capabilities removed, privilege escalation disabled, and memory (without extra swap), CPU, and process counts limited. The implementation follows Docker's [container run options](https://docs.docker.com/engine/containers/run/) and [run parameter reference](https://docs.docker.com/reference/cli/docker/container/run/). Reject images that declare extra writable volumes so they cannot bypass the workspace limit. An image must provide the read-only `/usr/bin/python3` standard library and support native Unix sockets and file-descriptor reads; rerun isolation tests for every new image.

<a id="submission"></a>

### Submission and Durable Records

The CLI reads the common first message from `/protocol/prompt.txt` and obtains paths and output requirements, sourced from the task configuration, from `/protocol/task.json`. The submission action is `python -I /protocol/submit.py`: the client sends only a `submit` request to the Unix socket for this run and supplies no candidate bytes, file path, or success assertion. The host runs a read-only helper against the container, clears the CLI's custom environment, isolates Python imports, and opens each directory and ordinary file along the configured output path with `O_NOFOLLOW`. It rejects links, FIFOs, oversized files, and changes made during copying. The host recomputes the digest, accepts only after the copy completes before the deadline, and returns the sequence number, receipt time, format, size, and digest to the client.

The host first writes the candidate by content address and `fsync`s the file and directories, then checks the deadline and decides whether to accept it. It appends a `submission` event containing the receipt and artifact reference and `fsync`s successfully before returning `accepted=true`. The receipt time is the decision time after the candidate is durable; event commit and receipt delivery may be slightly later. Reject a request whose candidate reaches durable storage only after the deadline. Writes to the workspace after acceptance do not modify the archived immutable candidate. No explicit submission is `no_submission`, and a submission after the deadline is rejected. Normal exit, non-zero exit, and timeout all use the last successfully received snapshot. A submission receipt confirms delivery; it cannot self-report DRC/LVS or performance success. After the session stops, remove the entire container and pass the frozen candidate and independent trusted task materials to the existing evaluator.

`run.json` schema 2 stores termination reasons and evaluation conclusions separately, including the harness identity, actual command, messages, configuration, code, materials, inputs, limits, submission receipts, and the last candidate digest. Atomically write `phase=running` before starting. After stopping, write `phase=stopped`; after independent evaluation, write `phase=finished` and bind the size and digest of the complete event log. Synchronize every replacement of a report with its file and directory. An incomplete record cannot be a final score.

`events.jsonl` schema 1 is synchronized one record at a time and contains a globally increasing sequence number, UTC time, relative time, event kind, and structured data. Record session creation and stop, inference request/result/rejection, submission acceptance/rejection, console chunks, and run completion separately. Save an inference request before forwarding it and its result before returning it to the Agent. Preserve all retrievable messages and tool inputs and outputs in request/response artifacts and native CLI logs; CLI output cannot forge framework events. Native logs are untrusted diagnostic evidence and do not reveal model reasoning that was not exposed.

Save stdout/stderr in full as offset-bearing `console.chunk` artifacts. Keep only the first 64 KiB preview in the `console` field of `run.json`; `console_truncated` describes that preview only. The current host console archive limit is 64 MiB and is recorded in the actual environment. Stop when the limit is reached or evidence storage fails, and classify the run as an infrastructure or incomplete-record condition rather than producing a score without evidence. Disable Docker's own persistent logs. Offline token/cost is `null`; see the next section for inference usage.

Use mode `0700` for run directories and the host temporary root, `0600` for events and reports, and `0400` for artifacts; control and inference sockets are `0600`. Containers use the host's non-root UID/GID. When the root starts a run, use `1000:1000` and transfer socket ownership. Mount each input subdirectory under the temporary root separately and read-only. This isolation seam separates other ordinary host users, but not processes with the same UID, root, or Docker administrators; those identities must be trusted by the operator.

`uv run --locked python main.py recover <run-directory>` validates received artifacts in the log read-only and returns a reference to the last candidate; it does not restore the Agent or rewrite an old score. A complete receipt event is the authoritative submission record: an artifact without a receipt event is not a submission, and a client disconnect or lost confirmation message does not revoke a committed event. Recovery may ignore a final incomplete log line, but rejects a corrupt complete record, discontinuous sequence numbers, or a candidate digest/size mismatch. A confirmed submission remains recoverable after the host process is force-killed. The operator may clean up an orphaned container by the container ID in `session.created`; automatic restart, container reclamation, and rescheduling are not implemented. Re-evaluate a recovered candidate through the independent `evaluate` entry point, but an interrupted run does not thereby become a complete model score.

<a id="model-inference"></a>

## 2. Connect a Model Gateway

Copy [inference.example.toml](../examples/agents/inference.example.toml), fill in your endpoint, model, and host key-variable name, and use the command in [README](../README.md#run-your-agent). Only a command with a real inference configuration contacts the selected model; the public preview and protocol tests do not require a model account.

A run configuration normally uses `command` and optional `[[files]]`; the session runner does not require a particular Agent framework. A built-in harness profile may prepare a command and reviewed files, but it produces the same `layout-session.v1` interface. Model communication and EDA backends are separate; the session does not parse provider sessions or the task circuit.

The legacy top-level `adapter` key is accepted only as a migration path for the bundled profile. New configurations should use `[harness]` or provide their own `command` and `files`.

The optional built-in profile is one example of a native harness: it invokes a pinned non-interactive CLI with an isolated home, ignores host configuration, and uses the outer container for sandboxing and budgets. Other harnesses may provide their own command and bridge; the runner does not require them to reproduce this implementation.

`--inference <profile.toml>` selects a schema 1 configuration supplied by the trusted operator:

| Field | Semantics |
|---|---|
| `base_url` | Fixed HTTPS base URL; URL credentials, queries, fragments, and dynamic redirects are forbidden |
| `model` | The model name required for every request; the CLI may not request another model |
| `wire_api` | Wire-family identity for the host gateway; the current built-in adapter is `responses` |
| `api_key_env` | Host environment-variable name whose value is read only by the host; the TOML and records contain no key |
| `max_requests` | Maximum forwarded requests, including failures and compaction; retries count against the limit |
| `request_timeout_seconds` | Per-connection/response time limit, also bounded by the session deadline |

The configuration specifies the model and wire family; the core does not hard-code a model or harness. If a harness declares `wire_api`, it must match the inference profile. A harness bridge connects to the loopback forwarder through that declared wire family. The forwarder can reach only this run's Unix socket. The host gateway holds the API key and makes the HTTPS connection, reads no HTTP proxy environment, and accepts no target URL, authorization header, or arbitrary method from the client.

The host allows only `POST /responses` and `POST /responses/compact`, fixes the model, and forces `store=false` on generated requests. Allow only client-executed function/custom/namespace tools. Reject online search, remote MCP, remote file/image references, background execution, and server-side conversation references; inline images are exempt from this restriction. Limit requests to 8 MiB and responses to 16 MiB. Run one inference at a time with a fixed upper bound on Unix handling threads. The proxy currently buffers each complete response before forwarding SSE, rather than streaming incrementally; this delay is part of wall-clock time.

For a non-success HTTP response, return only a generic error and do not forward a body that might echo credentials or redirect headers; reject a successful body that contains a key as well. Do not print raw connection exceptions to the Agent. On stop, close the inference entry point and active connections before destroying the container; start no new request after the deadline. Whether a remote request already sent stops computation and billing depends on the provider; cancelling the connection cannot claim zero remote usage.

Archive complete request/response artifacts, digests, byte counts, fixed endpoint, model, and forwarding status. Read input/output, cached input, and reasoning output usage from the actual terminal response. Aggregate them only when every relevant response provides valid values; otherwise use `null` rather than filling gaps from CLI self-reporting. Keep cost as `null`; there is no enforced token/cost limit.

Record HTTP status separately from response semantics:

| Response semantics | Classification |
|---|---|
| Consistent successful JSON/SSE terminal state | Normal response |
| `response.failed`, an in-stream `error`, a missing or conflicting terminal state, malformed or truncated SSE, an HTTP rejection, or a connection failure | Infrastructure error; HTTP 200 cannot override it |
| `incomplete` caused by `max_output_tokens` / `content_filter` | Classify as `budget_truncated` / `content_filtered`, respectively; neither is an infrastructure failure |
| Unknown or missing `incomplete` cause | `incomplete_error`; extend the mapping only after endpoint validation |

The current `responses` wire adapter follows the semantics of the [Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create); validate compatible endpoints separately. A single truncated response does not force the session to end, so a harness may continue within the remaining budget. Deadline cancellation or an exhausted request quota is a budget stop, and previously accepted candidates are still evaluated. Identify standalone `/responses/compact` results by their independent `response.compaction` object; do not inject its undeclared `store` parameter. A future wire adapter should keep these checks local to its own implementation.

| `run_kind` | Meaning |
|---|---|
| `offline_cli_development` | An offline program with no inference endpoint configured |
| `model_protocol_test` | Protocol validation against a deterministic endpoint; not a model score |
| `model_cli_development` | Model development run through a real HTTPS gateway; endpoint compatibility and solving effectiveness require concrete measurements |

<a id="failures"></a>

### Termination Reasons and Retries

| Situation | Handling |
|---|---|
| Normal end, model refusal, Agent error, or budget exhaustion | Evaluate the last accepted candidate; no submission is a failure, and a poor result is not retried |
| Candidate format error or violation of published file/geometry limits | Artifact failure, counted in the measurement denominator |
| API service, image startup, or storage failure | Record an infrastructure error; batch runs use the predeclared retry allowance and retain the original attempt |
| Evaluator crash, timeout, or missing measurement | Keep the candidate for re-evaluation; do not count it as a model failure or start a replacement Agent |

Classify an evaluation anomaly as an artifact failure only after confirming a violation of a published candidate limit. Leave unresolved slots as `missing` and show incomplete coverage in summaries. Distinguish response budget truncation from service failure as above; HTTP 200 alone does not prove inference succeeded.

<a id="local-run-plans"></a>

## 3. Freeze a Batch Run Plan

The quick start generates `build/runs/preview/run/plan.toml`, which can be rerun and its report recomputed in a new output directory:

```bash
uv run --locked python main.py batch build/runs/preview/run/plan.toml --output build/runs/probe-batch
uv run --locked python main.py summarize build/runs/probe-batch
```

This plan repeats an offline rectangle probe and is expected to have a task success rate of 0. To customize it, start from the generated file or [protocol-probe.toml](../examples/plans/protocol-probe.toml). Repository examples refer to old manual tool paths and require preparation according to the [tools guide](tools.md#manual-tools). Batch-plan schema 1 is shown below; unknown fields and versions are rejected:

| Field | Semantics |
|---|---|
| `id`, `scope` | Plan identity; `scope` is `public_development`, `hidden_development`, or `synthetic`, recording the caller-declared data scope; all are local development |
| `repetitions` | Positive repetition count for every task/configuration combination; it cannot change based on intermediate results |
| `order`, `seed` | `interleaved` orders repetition → task → configuration, or `shuffled` uses the given non-negative integer seed; archive the expanded order before running. The seed controls scheduling only and is not a provider random seed |
| `max_infrastructure_retries` | Infrastructure replacement attempts allowed for each measurement slot; may be 0, with an independent record for every original attempt |
| `tasks[]` | Each item references `config` (`task.toml`) and `toolchain`; task IDs must be unique |
| `agents[]` | Each item has a unique configuration alias `id` and `config` (an existing CLI configuration), plus optional `resources` (frozen bundle) and `inference` (fixed inference configuration); use one CLI with different endpoints/models as separate configurations |

Resolve the file and directory references above relative to the plan file and reject symlinks. CLI file references remain relative to the CLI configuration. Preserve existing adapter semantics inside toolchain `settings`: for current built-in backends, a relative `support` path is relative to the launch working directory, and the run record saves that directory and the actual support-bundle digest. Approved environments may be assembled with absolute paths. Take budgets directly from the referenced CLI and inference configurations, put the expanded values in the frozen manifest, and keep budgets, models, and repetition arrangements out of `task.toml`.

Before execution, load and validate every task, resource bundle, CLI file, endpoint configuration, and evaluation backend, and resolve the actual image IDs for the Agent and EDA. Then archive the original plan, per-task inputs and configurations, actual commands/environment/limits, endpoint and model, backend/support-bundle identities, host description, and the complete expanded order. `provenance.py` records the current `benchmarking` Python/JSON/YAML implementation files, available root entry points/image/dependency declarations, Git commit, and a status containing both uncommitted and untracked items. Source-content digests include new modules not yet committed. When an installed package has no Git checkout, still record source digests; root entry points or build files may be absent. An externally injected backend declares its installation/source identity through `identity`; the framework does not inspect arbitrary plugin directories.

Inspect the frozen manifest in `execution.json`; authoritative content digests and artifact references are stored in `batch.json.execution`. Each slot has its own `slot_id`. Write each original or replacement attempt under `runs/<slot_id>/attempt-<n>/`. Before the first task message, write the manifest digest, slot, task, configuration, repetition, and attempt number into that run's `run.json.execution`. Reuse frozen inputs and tool identities, but create a new container, empty workspace, and inference gateway for every solve; do not read memories from earlier solves. Scheduling is currently fixed to serial `concurrency=1`. Check source and backend identities before and after every attempt; stop if the implementation changes, retain incomplete records, and keep different conditions out of one manifest.

Freeze only the provider parameters that are declared and observable: archive the model, fixed endpoint, harness identity/image/command, configuration, and request contents. Do not claim to have frozen unavailable model snapshots, server defaults, or nondeterminism. The event artifacts contain the sampling and inference fields for each request; the scheduling seed does not control provider-side behavior.

Replace infrastructure errors according to the [failure classifications](#failures), using a new session for each attempt; keep evaluation errors with their candidates for re-evaluation. Missing configuration or environment blocks the entire plan during preflight. Storage failure or source changes during execution leave the plan incomplete. For unfinished attempts, the framework records only the exception category and does not write raw exception text that may contain credentials into batch records. A batch entry point for automatic recovery/rescheduling and re-evaluating failed candidates is not implemented; single-candidate recovery and independent `evaluate` remain available.

<a id="scoring"></a>

## 4. Interpret Statistics and Reproduction Scope

`summary.json` and `main.py summarize` recompute internal statistics from durable records and record the source digest of the statistics implementation used. Recomputing after changing that implementation does not overwrite original run evidence. A summary validates the digests for the execution manifest, individual records, event logs, and evaluation reports, together with task and CLI inputs, budgets, images, inference configuration, source, and candidate/judge bindings. It rejects duplicate counts, unplanned replacements, corrupt records, and inconsistent conditions. Slots that have not run, were interrupted, exhausted replacement attempts, or await evaluation recheck remain `missing`. `complete` means that the planned measurement sample is fully covered; it does not mean that all runs succeeded or that formal admission was granted. The batch CLI returns 0 when all scheduled measurements finish and 2 when samples are missing, while per-task failures remain in the statistics.

Group statistics by configuration, task environment, and actual evaluation backend. Within a group, weight families equally and then tasks within each family equally; also report task-equal weighting. If samples are missing, the primary success rate is `null`; retain per-task observed counts, success rates, and `missing` rather than shrinking the planned denominator to make coverage appear complete. For every task, provide raw success counts and a [95% Wilson interval](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm), with non-zero uncertainty even for all-success or all-failure results. With missing samples, an observed interval describes only the observed portion. Weighted summary intervals, family-level generalization intervals, and intervals for differences between configurations are not implemented; those fields are `null`, so they cannot support claims of broad generalization or significant superiority.

Store physical-validity and task-success rates separately. Retain raw metric values and units by task for successful candidates; do not average quality measurements with different scales across tasks. Resource statistics distinguish all attempts (including replacements), valid measurements, and success/failure subsets. When usage is missing, the total is `null`, with known/missing counts and a distribution for the known portion. Keep offline programs and deterministic endpoints labeled `offline_cli_development` and `model_protocol_test`; do not combine them into real model scores.

For task `t`, schedule `n_t` independent repetitions in advance and, after infrastructure replacements are complete, calculate:

```text
p_t = successful trials / n_t
SuccessRate = Σ_t w_t · p_t
w_t = 1 / (number of families × number of tasks in t's family)
```

Multiple modifications within one run are still one solve. Independent repetitions estimate success rate; do not replace it with “succeeded at least once.” Fix repetition count, budget, and order before execution and do not change them based on intermediate results. Group different processes and actual judge configurations separately; report public development, protocol tests, and hidden scopes separately.

Correctness, quality, and efficiency answer different questions. Do not combine DRC/LVS, area, tokens, and cost into a weighted total score. Two configurations with different successful subsets cannot be ranked directly by their respective mean area; comparisons on common successful tasks must disclose coverage and selection bias. Tokens from different providers do not inherently represent equal compute, and missing usage or unpriced cost must not be filled with 0.

A per-task Wilson interval describes repetition variation on that fixed task. It does not establish generalization to a broader circuit family, and overlap of two intervals is not a substitute for a difference test.

`recover` retrieves a submission, `evaluate` re-evaluates a candidate, and `summarize` recomputes statistics; none restores a model session. An evaluation fix should create a related new record for the same frozen candidate and retain old evidence. Rerunning an Agent can reproduce conditions and the statistics process, but cannot guarantee the same GDS.

Authorized operators retain run and summary directories; complete logs are not automatically an external report. Public local `run` and `batch` need no admission policy. Use the optional [admission mechanism](admission.md) when qualification, resources, endpoints, and export fields must be checked. It does not provide a hosted service or official leaderboard.
