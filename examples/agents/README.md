# Harness 配置示例

先按根 [README](../../README.md#quick-start-no-model-key-required) 准备统一镜像。快速开始会在 `build/runs/preview/prepared/` 生成绑定实际镜像与绝对资源路径的配置，下面命令直接使用它们。

## 离线提交探针

[protocol-probe.toml](protocol-probe.toml) 展示一个 opaque harness 的 `command`、限额和带摘要的 `files`。程序只画矩形并显式提交，不实现题目电路；运行预期退出 1，`run.json` 应显示正常终止但任务评估失败：

```bash
uv run --locked python main.py run tasks/academy-tgate/task.toml \
  --agent build/runs/preview/prepared/protocol-probe.toml \
  --toolchain build/runs/preview/prepared/toolchain.toml --output build/runs/protocol-probe
```

接入自己的程序时替换命令与文件，并更新摘要。文件路径相对配置解析，目标在只读 `/agent`；程序在 `/workspace` 工作，按 `/protocol/task.json` 写出 GDS 后运行 `python -I /protocol/submit.py`。如需声明协议版本或能力，可在配置末尾加入 `[harness]`；不声明时默认为 `external-cli`、`layout-session.v1` 和 `opaque`。配置 schema、隔离、提交与恢复见[运行指南](../../docs/running.md#offline-cli)。

## 可选的内置 profile

[codex.toml](codex.toml) 和 [codex-sg13g2.toml](codex-sg13g2.toml) 展示一个可选的 native harness profile；它们不是会话协议的要求。前者只声明 profile，后者增加 PDK 原语所需的公开环境设置。统一镜像使用 quickstart 生成的配置与 `agent-resources`；其他 harness 直接提供自己的 `command` 和 `files` 即可。

复制 [inference.example.toml](inference.example.toml) 到本地配置，填写真实端点、模型和主机密钥变量名，然后执行根 [README 的模型命令](../../README.md#run-your-agent)。密钥不写入配置文件或 harness 环境。推理请求限制、用量与错误语义见[推理配置](../../docs/running.md#model-inference)，无凭据验证命令见 [CONTRIBUTING](../../CONTRIBUTING.md#verification)。
