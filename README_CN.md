<p align="center">
<strong>Layout-Bench</strong><br/>
<sub>面向生成集成电路版图的 AI Agent 可复现基准测试。</sub>
</p>

<p align="center">
衡量 Agent 能否将电路网表、物理约束和工艺资源转换为有效的 GDS 版图。
</p>

<p align="center">
<a href="README.md">English</a> •
简体中文 •
<a href="#quick-start">快速开始</a> •
<a href="docs/architecture.md">架构</a> •
<a href="CONTRIBUTING.md">参与贡献</a>
</p>

<p align="center">
<a href="https://github.com/lizhangmai/Layout-Bench/actions/workflows/checks.yml"><img src="https://github.com/lizhangmai/Layout-Bench/actions/workflows/checks.yml/badge.svg?branch=main" alt="框架检查"></a>
<a href="https://github.com/lizhangmai/Layout-Bench/actions/workflows/cd.yml"><img src="https://github.com/lizhangmai/Layout-Bench/actions/workflows/cd.yml/badge.svg" alt="发布流程"></a>
<a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12%2B-3776AB.svg?logo=python&logoColor=white" alt="Python 3.12+"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ea44f.svg" alt="MIT license"></a>
</p>

Layout-Bench 在隔离容器中运行 Agent，记录明确提交的 GDS，并使用独立的 EDA 工具评估冻结后的候选版图。DRC/LVS 用于建立物理有效性；完整任务还会检查声明的几何约束和后仿性能限值。

> **开发预览版。** 当前仓库包含一个公开任务 `academy-tgate`、对应参考解和 14 个资格验证场景。基准仍在扩展，API 和报告 schema 可能变化。

## 为什么选择 Layout-Bench？

| 能力 | 提供内容 |
| --- | --- |
| **端到端版图任务** | 冻结网表、约束、工艺资源和评估计划，最终产出 GDS 工件。 |
| **可复现的运行条件** | 固定输入、配置摘要、镜像 ID、预算、事件日志和持久提交记录。 |
| **独立裁判** | Agent 停止后由可信评估器重新检查候选；自报检查结果不决定分数。 |
| **开放的接入接口** | 手写 CLI、内置 Codex adapter 和可配置 EDA 后端共享同一会话契约。 |
| **资格验证优先** | 通过参考 witness、反例、提取检查及原理图/后仿校准，在发布前暴露裁判问题。 |

## 前置条件

- **Linux x86-64**、Git 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。
- **启用 BuildKit 且用户可访问的 Docker**。工具镜像使用 Ubuntu 24.04；原生 macOS、Windows 和 ARM 执行尚未验证。
- **网络和存储空间**，用于首次下载工具、镜像和 PDK，并准备数 GB 可用空间。评估容器不访问外部网络。

请使用源码 checkout，并从仓库根目录运行命令。快速开始会通过 uv 提供 Python 3.12。不需要私有仓库 checkout、PyPI 安装包或预构建镜像发布版。

<a id="quick-start"></a>

## 快速开始

克隆公开仓库后运行：

```bash
git clone https://github.com/lizhangmai/Layout-Bench.git
cd Layout-Bench
uv run --python 3.12 --locked python scripts/public_preview.py quickstart --output build/runs/preview
```

该命令只构建一个 `layout-bench-tools:local` 镜像，获取固定版本的 PDK，准备经过审查的资料，并运行参考解、提交和批量检查。KLayout、ngspice、Magic、OpenVAF、Xschem 和 Codex CLI 已包含在镜像中，不需要单独的 Agent 镜像。快速开始不会调用模型账户。

首次运行需要下载工具和 PDK，可能耗时数分钟。后续运行会复用 Docker 层和 PDK checkout，同时重新准备已验证的资料和全新工作区。每次运行都应选择新的 `--output` 目录；已有证据不会被覆盖。若要复用已构建的镜像，可使用 `--skip-build`。该命令只初始化 PDK submodule，其他公开资料 submodule 为可选项。

仓库本地生成的文件统一放在顶层 `build/`：benchmark 运行证据放在 `build/runs/`，手工准备的 PDK 和 EDA 支持包放在 `build/support/`，Python 分发包放在 `build/dist/`。`build/lib/` 和 `build/bdist.*` 是 setuptools 的临时打包目录。该目录已被 Git 忽略；不需要本地报告或已准备资源时可以删除。

成功的 smoke run 会以 `PASS` 结束，并写入：

| 文件 | 预期结果 |
| --- | --- |
| `build/runs/preview/run/preview.json` | 参考解通过、协议失败符合预期、批量运行完成，且未调用模型。 |
| `build/runs/preview/run/reference/report.json` | 发布的参考解通过 DRC/LVS、几何和后仿限值。 |
| `build/runs/preview/run/probe/run.json` | 离线探针成功提交矩形，然后按预期在任务评估中失败。 |
| `build/runs/preview/run/batch/summary.json` | 两次独立探针运行、样本完整覆盖、任务成功数为 0。 |

当这些预期都满足时，包装脚本返回 **0**。详细输出保存在运行目录的 `.log` 文件中。各命令会区分版图被拒绝和基础设施错误：`main.py run` 在版图被拒绝时返回 **1**；`main.py batch` 在所有计划测量都完成时返回 **0**，即使每个版图都失败。

重建参考解和反例，并重新执行完整资格验证及原理图校准：

```bash
uv run --locked python scripts/public_preview.py qualify \
  --prepared build/runs/preview/prepared \
  --output build/runs/preview-qualification
```

[参考解](tasks/academy-tgate/reference/README.md)和[资格证据](tasks/academy-tgate/qualification/README.md)公开用于调试。标准 Agent 运行只接收声明的任务输入，永远不会挂载参考解。

## 如何使用

工作流程如下：

1. **选择任务**：从公开的 `academy-tgate` 任务及其声明输入开始。
2. **配置 Agent**：使用手写 CLI 或 Codex adapter，并指定经过审查的文件、资料和预算。
3. **提交候选版图**：在 `/workspace` 中工作，然后运行 `python -I /protocol/submit.py`，明确提交配置的 GDS。
4. **评估和比较**：单个候选使用独立评估器；批量测量使用冻结的“任务 × 配置 × 重复次数”计划。

Agent 会收到 `/protocol/prompt.txt`、`/protocol/task.json` 和只读的 `/task` 输入。标准运行不会收到公开参考解。

使用 Codex adapter 时，复制 [inference.example.toml](examples/agents/inference.example.toml)，填写端点、模型和主机密钥变量名，然后运行：

```bash
uv run --locked python main.py run tasks/academy-tgate/task.toml \
  --agent build/runs/preview/prepared/codex-sg13g2.toml \
  --resources build/runs/preview/prepared/agent-resources \
  --toolchain build/runs/preview/prepared/toolchain.toml \
  --inference build/runs/inference.toml \
  --output build/runs/my-first-model-run
```

该命令会调用你配置的模型；快速开始本身不会调用模型。凭据保留在主机上。当前尚未实现同语义的会话内裁判反馈。

## 工作原理

Layout-Bench 运行一个四阶段循环：

1. **定义**：`task.toml` 固定任务输入、输出契约、约束和可选评估计划。
2. **运行**：Runner 固定 Agent 配置、资料、预算、工具链和执行身份，然后启动隔离会话。
3. **裁判**：明确提交后，评估器使用声明的 artifact、DRC、LVS、几何、提取和性能 job 检查冻结的 GDS。
4. **报告**：持久事件和工件支持独立重新评估、批量统计和可复现性检查。

DRC/LVS 是物理有效性门槛。任务成功还要求所有硬约束、必需的后仿 job 和声明的性能限值全部通过。

<a id="documentation-and-development"></a>

## 资源

| 需求 | 链接 |
| --- | --- |
| 重现无需模型密钥的公开预览 | [快速开始](#quick-start) |
| 接入自定义 CLI 或 Codex | [CLI adapter 示例](examples/agents/README.md) |
| 添加任务并验证裁判 | [任务与评估](docs/tasks.md) |
| 了解运行计划、推理限制和评分 | [运行指南](docs/running.md) |
| 准备 PDK/EDA 资料或排错 | [工具指南](docs/tools.md) |
| 应用操作方准入和受限导出 | [准入](docs/admission.md) |
| 了解 CI/CD 和发布触发条件 | [参与贡献](CONTRIBUTING.md#ci-cd) |
| 参与贡献或报告问题 | [CONTRIBUTING.md](CONTRIBUTING.md) |

框架检查不需要 Docker 镜像、PDK 或模型凭据。CI 会运行 lint、单元测试和本地文档链接检查；手动的[公开 EDA 预览](.github/workflows/public-eda.yml)工作流会在真实容器中执行公开任务。

## 常见问题

<details>
<summary><strong>运行 benchmark 需要模型密钥吗？</strong></summary>

不需要。公开快速开始使用确定性的离线探针和已发布参考解。只有在为自己的 Agent 运行配置真实推理端点时才需要模型密钥。

</details>

<details>
<summary><strong>通过 DRC/LVS 就代表任务通过了吗？</strong></summary>

不代表。DRC/LVS 只说明选定规则下的物理有效性。任务成功还要求任务的几何约束和后仿性能限值通过。

</details>

<details>
<summary><strong>可以使用 Codex 之外的 Agent 吗？</strong></summary>

可以。任何遵循会话契约的 CLI 都能配置其命令、经过审查的文件、资料和预算。Codex adapter 是可选项。

</details>

<details>
<summary><strong>标准 Agent 会收到参考解吗？</strong></summary>

不会。参考 GDS 和资格证据公开用于调试，但标准运行只会物化 `task.toml` 声明的任务输入。

</details>

<details>
<summary><strong>有托管服务或官方排行榜吗？</strong></summary>

没有。当前版本是本地开发预览。托管评估、身份认证和官方排行榜不在范围内。

</details>

<details>
<summary><strong>为什么有 14 个资格验证场景？</strong></summary>

它们覆盖公开任务的正例、负例、几何、提取、性能和稳定性路径，是裁判资格用例，并不是 14 个独立的 benchmark 任务。

</details>

## 预览状态

当前版本是本地开发预览，包含一个公开任务及其资格材料、Codex CLI adapter、受控 Responses gateway、可配置 EDA 后端和本地批量统计。下一步计划包括配置真实模型基线、同语义过程反馈，以及来自另一电路家族的第二个公开任务。预览期间 API 和报告 schema 可能变化。

框架采用 [MIT](LICENSE) 许可。公开的 `academy-tgate` 任务保留其 [Apache-2.0 许可](tasks/academy-tgate/LICENSE)。Submodule、工具和依赖保留各自的许可与声明；来源和资料准备见[工具指南](docs/tools.md#external-sources)。

<p align="center">
<a href="README.md">阅读英文文档 →</a>
</p>
