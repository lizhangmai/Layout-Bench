# 传输门资格与校准

本目录提供传输门 case 的公开资格套件，包括 14 个裁判场景和原理图/后仿校准。资格和校准均固定在 `sg13g2-klayout-main-magic-c-v1` 工具环境中；机器可读的结果、实际工具身份和每个场景的测量值分别记录在 [qualification.json](qualification.json) 和 [calibration.json](calibration.json) 中。

本题已在 `sg13g2-klayout-main-magic-c-v1` 环境通过下列 14 场景验证。[qualification.json](qualification.json) 保存任务、候选、生成脚本、裁判和实际工具身份，以及各场景的检查状态和测量值；[calibration.json](calibration.json) 保存使用相同工况和测量定义得到的前后仿结果。公开参考见 [reference](../reference/README.md)。

资格限定于所选上游 main DRC、严格 LVS 和已声明的几何/性能判据。main DRC 不含密度、天线和 precheck 流程。Magic 提取器件及寄生电容，不含布线电阻；标称 MOS 模型在 1.2 V、27/125 °C 下测量，不代表完整 PVT 或生产签核。

## 性能校准

测量方法、工况和限值的权威定义为 [evaluation.toml](../inputs/evaluation.toml) 和其引用的 testbench。下表为各指标最坏工况的近似数值，机器记录保留每个观测值。

| 指标 | 前仿 | 参考版图后仿 | 上限 |
|---|---:|---:|---:|
| 导通电阻 | 5.098 kΩ | 5.098 kΩ | 6 kΩ |
| 关断漏电 | 6.499 nA | 6.499 nA | 10 nA |
| 20 fF 上升延迟 | 37.26 ps | 39.06 ps | 50 ps |
| 20 fF 下降延迟 | 37.24 ps | 39.00 ps | 50 ps |
| 100 fF 上升延迟 | 164.48 ps | 166.29 ps | 200 ps |
| 100 fF 下降延迟 | 162.27 ps | 164.04 ps | 200 ps |
| 20 fF 采样误差 | 0.0432 µV | 0.0430 µV | 100 µV |
| 100 fF 采样误差 | 8.242 mV | 8.897 mV | 12 mV |
| 功能层外形面积 | — | 118.125 µm² | 仅报告 |

限值从参考版图在声明工况下的结果留出余量并取整，用于公开开发题的可行性和区分性；不是最优版图指标或工艺保证。20 fF 采样误差已接近仿真数值底限，因此采用较宽的 100 µV 上限；100 fF 下的 12 mV 上限能排除额外金属负载反例。采样在输入上升沿开始后 0.8 ns；导通电阻测量覆盖 0.2/0.6/1.0 V 三档直流输入、1 µA 负载。全部性能逐工况判定，不以聚合值掩盖失败。

此轮前后仿直流结果相同，符合当前没有布线电阻的提取范围，不能据此评价布线电阻优化。瞬态结果已随提取电容变化：`slow` 的 20 fF 上升延迟约 69.81 ps、100 fF 采样误差约 20.33 mV，尽管 DRC/LVS 和几何检查均通过，完整任务仍失败。

## 场景矩阵

所有变体均由新建参考生成，不读取上游版图。`variants.py` 使用 KLayout 原生几何 API；尺寸反例由参考生成器改变 nMOS 宽度获得，权威网表保持不变。

| 场景 | 预期 |
|---|---|
| `reference`、`translated`、`hierarchy` | 全部通过；平移和带顶层端口标签的层次结构保持结果 |
| `slow` | 物理与几何通过，后仿性能失败 |
| `outline` | 外形超过 30 × 30 µm，几何检查失败 |
| `pin_size` | 端口可接入区域不足，几何检查失败 |
| `nested_labels`、`duplicate_label` | 缺少唯一顶层端口标签，几何检查失败 |
| `missing_pin`、`short`、`open`、`wrong_size` | 严格 LVS 失败 |
| `drc` | 上游 DRC 失败 |
| `empty` | 交付检查失败 |

## 复现与证据

先完成根 [README](../../../../../../README.md#quick-start-no-model-key-required) 的快速开始，再执行该处的 `qualify` 命令；它使用统一镜像配置，输出 `qualification/qualification.json` 与 `calibration.json`，可重建本目录两个公开摘要。任一场景或校准不符合预期即失败。

单独重验时，可分别运行：

```bash
uv run --locked python tasks/IHP-AnalogAcademy/cases/assets/module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate/qualification/run.py \
  build/runs/preview/prepared/pdk-view build/runs/tgate-qualification \
  --toolchain build/runs/preview/prepared/toolchain.toml
uv run --locked python tasks/IHP-AnalogAcademy/cases/assets/module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate/qualification/calibrate.py build/runs/tgate-schematic \
  --toolchain build/runs/preview/prepared/toolchain.toml --support build/runs/preview/prepared/klayout
```

每次使用新输出目录。资格脚本重新生成全部 GDS；校准通过 PDK 原生 reader 和 KLayout writer 生成模型调用，再复用题目仿真 job，不手工修订权威 CDL。

完整报告、原生 DRC/LVS 数据库、提取网表、波形和日志在复现输出的 `evaluation/` 或 `measurements/` 中按摘要保存。仓库中的两个 JSON 是该次运行的公开摘要，包含报告摘要但不打包全部原始工具工件；可用上述命令重建并检查。环境或规则变化后必须重新校准、验证并更新记录。集成测试还检查特殊端口别名不会把 `!CONTROL` 与 `CONTROL` 合并、LVS 证据不能移用到另一份 GDS，以及参考/资格目录不进入标准求解输入。

<a id="source-reproduction"></a>

## 重导出来源网表

此步骤用于维护题目来源，不是运行已发布输入的前提。初始化课程 submodule 后，从仓库根执行：

```bash
git submodule update --init --recursive third_party/IHP-AnalogAcademy
uv run --locked python -m benchmarking.prepare tasks/IHP-AnalogAcademy/cases/module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate.toml build/runs/tgate-source \
  --checkout academy=third_party/IHP-AnalogAcademy --checkout pdk=third_party/IHP-Open-PDK \
  --image layout-bench-tools:local
```

case TOML 的 `[source_export]` 段限定可读文件；准备器保存原始 LVS 网表和 provenance。核对导出与已发布输入一致，再按[任务录入要求](../../../../../../docs/tasks.md)处理来源或工具变化。
