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

> **公开预览版。** 快速开始直接评估 [comparator](tasks/IHP-AnalogAcademy/cases/comparator/README.md) 的参考版图，也可选择 [full_OTA](tasks/IHP-AnalogAcademy/cases/full_OTA/README.md)。其余公开电路见 [IHP AnalogAcademy](tasks/IHP-AnalogAcademy/catalog.toml) 和 [TO_Apr2025](tasks/TO_Apr2025/catalog.toml) 清单；是否具备可执行评测和通过见证，以各 case 的状态和说明为准。

## 为什么选择 Layout-Bench？

| 能力 | 提供内容 |
| --- | --- |
| **端到端版图任务** | 冻结网表、约束、工艺资源和评估计划，最终产出 GDS 工件。 |
| **可复现的运行条件** | 固定输入、配置摘要、镜像 ID、预算、事件日志和持久提交记录。 |
| **独立裁判** | Agent 停止后由可信评估器重新检查候选；自报检查结果不决定分数。 |
| **开放的接入接口** | 任意可执行 harness 和可配置 EDA 后端都能使用统一的会话与评估契约。 |
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

该命令只构建一个 `layout-bench-tools:local` 镜像，获取固定版本的 PDK，准备经过审查的资料，并按 comparator 自身的完整评测计划验证参考 GDS。KLayout、ngspice、Qucs-S/Qucsator、Magic、OpenVAF、Xschem 和 Python 包含在这个镜像中；harness runtime 通过统一会话契约由各 harness 自行提供，因此不需要按 EDA 角色拆分镜像。快速开始不会调用模型账户。

如果主机代理只监听 `127.0.0.1` 或 `localhost`，请在 quick-start 命令中加入 `--network host`，让镜像构建能够访问该代理。该选项只影响镜像构建；评估容器仍然禁用网络。

首次运行需要下载工具和 PDK，可能耗时数分钟。后续运行会复用 Docker 层和 PDK checkout，同时重新准备已验证的资料和全新工作区。每次运行都应选择新的 `--output` 目录；已有证据不会被覆盖。若要复用已构建的镜像，可使用 `--skip-build`。快速开始只初始化 PDK 以及已验证视图所需的两个 KLayout Python 子模块；digital、openEMS 和 Palace 子模块保持可选。若这些必需目录已经有完整文件但没有 Git 元数据，快速开始会复用它们，后续准备阶段仍会逐文件校验哈希。

仓库本地生成的文件统一放在顶层 `build/`：benchmark 运行证据放在 `build/runs/`，手工准备的 PDK 和 EDA 支持包放在 `build/support/`，Python 分发包放在 `build/dist/`。`build/lib/` 和 `build/bdist.*` 是 setuptools 的临时打包目录。该目录已被 Git 忽略；不需要本地报告或已准备资源时可以删除。

成功运行会以 `PASS` 结束，并生成：

| 文件 | 内容 |
| --- | --- |
| `build/runs/preview/run/preview.json` | case ID、参考评估结果和未调用模型的记录。 |
| `build/runs/preview/run/reference/report.json` | GDS、DRC、LVS、几何约束、RC 提取和后仿性能的完整结果。 |
| `build/runs/preview/prepared/case/case.toml` | 绑定实际镜像 ID 和资源路径的 case 配置，可直接用于 `main.py run` 或 `evaluate`。 |

包装脚本只在参考见证通过完整评测时返回 **0**。这说明声明条件下存在通过解，不代表模型能力、最优解或所有工况的签核。

使用已有镜像验证 full_OTA：

```bash
uv run --locked python scripts/public_preview.py quickstart --case full_OTA \
  --skip-build --output build/runs/ota-preview
```

IHP 和 TO_Apr2025 的参考解和 qualification 资产只会随通过“上游已有完整实现”门槛的电路公开。标准 Agent 运行只接收 case TOML 的 `[task]` 段声明的输入，永远不会挂载参考解。

## 如何使用

工作流程如下：

1. **选择任务**：从 comparator 或 full_OTA 等已经具备完整评测和通过见证的 case 开始。
2. **配置 harness**：提供任意可执行命令、经过审查的文件、资料和预算；可选 harness profile 只记录协议和执行语义。
3. **提交候选版图**：在 `/workspace` 中工作，然后运行 `python -I /protocol/submit.py`，明确提交配置的 GDS。
4. **评估和比较**：单个候选使用独立评估器；批量测量使用冻结的“任务 × 配置 × 重复次数”计划。

配置的 harness 会收到 `/protocol/prompt.txt`、`/protocol/task.json`、`/protocol/harness.json`、`/protocol/resources.json` 和只读的 `/task` 输入。标准运行不会收到公开参考解。Runner 不解析 harness 内部会话；harness 只需按协议显式提交候选版图。挂载经过审查的 PDK 资源包时，Runner 会自动提供容器内的 `KLAYOUT`/`PYTHONPATH`，并在 `/protocol/resources.json` 中给出导入 preflight。

通过主机持有的 gateway 连接模型时，按[运行指南](docs/running.md#model-inference)创建 schema 1 推理配置，填写端点、模型和主机密钥变量名，再运行自己的 harness 配置：

```bash
uv run --locked python main.py run build/runs/preview/prepared/case/case.toml \
  --agent path/to/agent.toml \
  --resources build/runs/preview/prepared/agent-resources \
  --inference build/runs/inference.toml \
  --output build/runs/my-first-model-run
```

在消耗请求前，可以先检查 profile、可选的 harness wire 声明和主机凭据；该命令不会联系模型服务：

```bash
uv run --locked python main.py inference-check build/runs/inference.toml --agent path/to/agent.toml
```

当 harness 实际转发请求时，该命令会调用你配置的模型；快速开始本身不会调用模型。仅配置 profile 但没有转发请求时，报告会明确标记为离线运行。凭据保留在主机上。gateway 通过 provider-neutral adapter registry 选择配置中声明的 wire family；可选的 Responses adapter 只是其中一种，harness 自己负责所需桥接。harness 可以声明 `process-feedback.v1` 来请求同语义的会话内检查；每次检查使用冻结候选快照，并在报告中与最终独立成绩分开。

## 工作原理

Layout-Bench 运行一个四阶段循环：

1. **定义**：统一 case TOML 固定电路来源、任务输入、输出契约、约束和可选评估计划。
2. **运行**：Runner 固定 Agent 配置、资料、预算、工具链和执行身份，然后启动隔离会话。
3. **裁判**：明确提交后，评估器使用声明的 artifact、DRC、LVS、几何、提取和性能 job 检查冻结的 GDS。
4. **报告**：持久事件和工件支持独立重新评估、批量统计和可复现性检查。

DRC/LVS 是物理有效性门槛。任务成功还要求所有硬约束、必需的后仿 job 和声明的性能限值全部通过。

<a id="documentation"></a>

## 资源

| 需求 | 链接 |
| --- | --- |
| 重现无需模型密钥的公开预览 | [快速开始](#quick-start) |
| 接入自定义 harness | [运行指南](docs/running.md#offline-cli) |
| 添加任务并验证裁判 | [任务与评估](docs/tasks.md) |
| 了解运行计划、推理限制和评分 | [运行指南](docs/running.md) |
| 准备 PDK/EDA 资料或排错 | [工具指南](docs/tools.md) |
| 应用操作方准入和受限导出 | [准入](docs/admission.md) |
| 了解 CI/CD 和发布触发条件 | [参与贡献](CONTRIBUTING.md#ci-cd) |
| 参与贡献或报告问题 | [CONTRIBUTING.md](CONTRIBUTING.md) |

框架检查不需要 Docker 镜像、PDK 或模型凭据。CI 会运行 lint、单元测试和本地文档链接检查；手动的[公开 EDA 预览](.github/workflows/public-eda.yml)工作流会在真实容器中评估公开 case 的参考见证，并运行相应的 EDA 回归检查。

## 常见问题

<details>
<summary><strong>运行 benchmark 需要模型密钥吗？</strong></summary>

不需要。公开快速开始直接评估已发布 case 的参考 GDS。只有在为自己的 Agent 运行配置真实推理端点时才需要模型密钥。

</details>

<details>
<summary><strong>通过 DRC/LVS 就代表任务通过了吗？</strong></summary>

不代表。DRC/LVS 只说明选定规则下的物理有效性。任务成功还要求任务的几何约束和后仿性能限值通过。

</details>

<details>
<summary><strong>可以使用内置 profile 之外的 harness 吗？</strong></summary>

可以。任何遵循会话协议的可执行程序都能配置其命令、经过审查的文件、资料和预算。内置 profile 只是便利项，Runner 不要求特定 Agent 框架。

</details>

<details>
<summary><strong>标准 Agent 会收到参考解吗？</strong></summary>

不会。通过准入的任务才会公开参考 GDS 和资格证据用于调试；标准运行只会物化 case TOML 的 `[task]` 段声明的任务输入。

</details>

<details>
<summary><strong>有托管服务或官方排行榜吗？</strong></summary>

没有。这是本地预览包。托管评估、身份认证和官方排行榜不在范围内。

</details>

<details>
<summary><strong>快速开始会运行哪个电路？</strong></summary>

默认运行 comparator；使用 `--case full_OTA` 运行 OTA。两者均直接采用其 `case.toml` 声明的规则、约束和性能限值。

</details>

## 范围

本公开包包含通用可执行 harness 会话协议、不绑定厂商的 canonical harness 示例、由主机持有的模型 gateway、可配置 EDA 后端、公开电路 case 和本地批量统计。不包含托管评测、身份认证或官方排行榜。

框架采用 [MIT](LICENSE) 许可。IHP AnalogAcademy 和 TO_Apr2025 录入清单保留上游许可和逐文件声明；后续派生任务资产也必须保留对应上游声明。Submodule、工具和依赖保留各自的许可与声明；来源和资料准备见[工具指南](docs/tools.md#external-sources)。

<p align="center">
<a href="README.md">阅读英文文档 →</a>
</p>
