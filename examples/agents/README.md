# Harness 配置示例

先按根 [README](../../README.md#quick-start-no-model-key-required) 准备统一镜像。快速开始会在 `build/runs/preview/prepared/` 生成绑定实际镜像与绝对资源路径的配置，下面命令直接使用它们。

## 离线提交探针

[protocol-probe.toml](protocol-probe.toml) 展示一个 opaque harness 的 `command`、限额和带摘要的 `files`。程序只画矩形并显式提交，不实现题目电路；运行预期退出 1，`run.json` 应显示正常终止但任务评估失败：

```bash
uv run --locked python main.py run tasks/IHP-AnalogAcademy/cases/module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate.toml \
  --agent build/runs/preview/prepared/protocol-probe.toml \
  --toolchain build/runs/preview/prepared/toolchain.toml --output build/runs/protocol-probe
```

接入自己的程序时替换命令与文件，并更新摘要。文件路径相对配置解析，目标在只读 `/agent`；程序在 `/workspace` 工作，按 `/protocol/task.json` 写出 GDS 后运行 `python -I /protocol/submit.py`。如需声明协议版本或能力，可在配置末尾加入 `[harness]`；不声明时默认为 `external-cli`、`layout-session.v1` 和 `opaque`。配置 schema、隔离、提交与恢复见[运行指南](../../docs/running.md#offline-cli)。

统一镜像的 quickstart 只生成通用协议探针配置。其他 harness 直接提供自己的 `command`、`files` 和 `[harness]` 元数据即可；Layout-Bench 不选择或安装特定 Agent framework。

<a id="provider-neutral-canonical-harness"></a>

## Provider-neutral canonical harness（不绑定厂商的标准 harness）

[canonical_harness.py](canonical_harness.py) 提供一个固定的模型—工具循环：它读取同一份任务提示，向模型适配器发送完整对话和两个固定工具（在 `/workspace` 执行命令、提交 GDS），再把工具结果送回适配器。适配器是一个独立可执行程序，通过 JSONL 收发，不要求使用哪一家模型或 SDK：

```text
请求：{"schema_version":1,"type":"request","conversation":[...],"tools":[...]}
响应：{"schema_version":1,"type":"response","content":"...","tool_calls":[...],"stop_reason":"tool_calls"}
```

每个工具调用必须是 `{"id", "name", "arguments"}`；`run_command` 只接受参数列表并固定在 `/workspace` 执行，`submit_layout` 不接受参数。适配器负责把任意模型服务的返回值转换成这套格式，harness 负责执行工具和保存提交语义。适配器的命令、版本、提示和工具条件都应随 Agent 配置冻结。

适配器只返回这套规范字段：`stop_reason` 为 `tool_calls` 时必须有工具调用，为 `stop`、`length` 或 `error` 时不得有调用；上游厂商错误应映射为 `error`，不得把原始异常或凭据写入 JSONL。模型 token/成本统计由 host gateway 按所选 `wire_api` 的终态响应记录，canonical JSONL 不携带厂商字段，因此替换 wire adapter 不需要修改固定工具循环。

[canonical-probe-adapter.py](canonical_probe_adapter.py) 和 [canonical-probe.toml](canonical-probe.toml) 是不调用模型的确定性协议探针，只验证这个固定循环能创建并提交一个矩形；它预期评估失败，不能当作模型成绩。要接入真实模型，只替换 adapter，并保持 harness、工具定义、预算和 prompt 不变。适配器若需要访问主机 gateway，可同时加入 [inference_bridge.py](inference_bridge.py)；该桥接器不读取密钥，具体服务商协议只存在于适配器中。

`canonical_harness.py` 要求 adapter 的标准输出只写 JSONL 响应；调试信息请写标准错误。quickstart 会把该 harness、确定性 adapter 和配置一起放入 `prepared/`，因此可以先运行协议探针，再替换 adapter 文件和对应摘要。

复制 [inference.example.toml](inference.example.toml) 到本地配置，填写真实端点、模型和主机密钥变量名。付费请求前可运行 `uv run --locked python main.py inference-check <profile.toml> --agent <agent.toml>` 做无请求预检；然后执行根 [README 的模型命令](../../README.md#run-your-agent)。密钥不写入配置文件或 harness 环境。推理请求限制、用量与错误语义见[推理配置](../../docs/running.md#model-inference)。

如果 harness 选择可选的 `responses` wire family，可直接把 [inference_bridge.py](inference_bridge.py) 作为 reviewed file 放入 `[[files]]`。它不读取密钥，只实现每次连接一条请求的 framing：发送 `{"path": "/responses", "bytes": N}` 加换行和 N 个 JSON 字节，随后读取同样由 JSON header 与定长 body 组成的响应。其他 wire family 应提供自己的 reviewed bridge；最小调用方式是：

```python
from inference_bridge import InferenceClient

response = InferenceClient().create("Describe the next layout step.")
print(response.status, response.content_type, response.body)
```

`create` 和 `compact` 会从 `/protocol/inference.json` 使用冻结的 model；请求仍受 profile 的模型、请求数、超时和 Responses 语义校验约束。桥接器只负责 socket framing，不替代 harness 的上下文、工具循环或提交逻辑。
