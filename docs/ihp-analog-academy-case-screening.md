# IHP AnalogAcademy case screening

本文按 pinned upstream commit `133ecf657572e021b5921b5a1b7693abfb209623`
逐一检查 catalog 中的 30 个 case。筛选门槛是“上游已经公开提供可复用的完整
版图实现”：至少要能在不生成新版图的前提下拿到对应的 GDS、源电路/LVS
网表，以及足够的 DRC/LVS/抽取或后仿证据。只有原理图、testbench、仿真结果，
或者只有一块无法和源电路对上的 GDS，都不能进入公开 Bench。

## 结论

当前只保留 4 个上游版图组作为公开 Bench 的候选入口：

- `module_1_bandgap_reference.part_3_layout.OTA_layout.full_OTA`
- `module_1_bandgap_reference.part_3_layout.OTA_layout.input_pair`
- `module_1_bandgap_reference.part_3_layout.OTA_layout.output_stage`
- `module_3_8_bit_SAR_ADC.part_5_analog_layout.comparator`

这 4 个 case 的 TOML 仍需完成任务约束、评估计划和独立 qualification 后才能
标成 `qualified`；但它们的 reference 必须直接取自 pinned upstream，不能另写
layout generator。当前没有任何 IHP case 标成 `qualified`。之前为 T_gate 写的
参考 GDS、qualification 脚本和校准文件已删除；T_gate 只保留上游 schematic 和
testbench 来源记录。

统计为 **include 4，defer 5，exclude 21**。`defer` 表示上游确实有部分版图
或存在可合并的物理实现，但端口、层次、网表或证据还不闭合；`exclude` 表示
当前没有可公开复用的完整 transistor layout，或它根本不是本 Bench 的
`netlist_to_gds` 对象。

## 逐案筛选

| Case | Decision | 上游证据和理由 |
|---|---|---|
| [`module_0_foundations.inverter`](../tasks/IHP-AnalogAcademy/cases/module_0_foundations.inverter.toml) | **exclude** | 只有原理图和 transient testbench；唯一的 inverter GDS 属于 input-isolation 明确排除的历史 `PEX_Demo`，没有可公开复用版图。 |
| [`module_0_foundations.lvs_tester`](../tasks/IHP-AnalogAcademy/cases/module_0_foundations.lvs_tester.toml) | **exclude** | 有 GDS/CDL/DRC，但它是单 NMOS 的 LVS tester fixture，没有功能 testbench 或任务级目标，不是公开 Bench 电路。 |
| [`module_1_bandgap_reference.part_1_OTA.gmid_example`](../tasks/IHP-AnalogAcademy/cases/module_1_bandgap_reference.part_1_OTA.gmid_example.toml) | **exclude** | 是 gm/Id 教程原理图和仿真 deck；没有对应上游 GDS/LVS 版图实现。 |
| [`module_1_bandgap_reference.part_1_OTA`](../tasks/IHP-AnalogAcademy/cases/module_1_bandgap_reference.part_1_OTA.toml) | **exclude** | 有 PDK-native OTA 原理图和 testbench，但没有同 case 的上游完整版图；不能把别处版图冒充 reference。 |
| [`module_1_bandgap_reference.part_2_full_bgr`](../tasks/IHP-AnalogAcademy/cases/module_1_bandgap_reference.part_2_full_bgr.toml) | **defer** | 有完整 BGR 原理图/温度/Monte Carlo 变体，但 canonical variant、层次网表和物理实现尚未唯一闭合；应与 part-3 BGR 版图先做对应核对。 |
| [`module_1_bandgap_reference.part_3_layout.BGR_layout.final_bandgapreference`](../tasks/IHP-AnalogAcademy/cases/module_1_bandgap_reference.part_3_layout.BGR_layout.final_bandgapreference.toml) | **defer** | 上游有 `full_bandgap_layout.gds` 和 extracted netlist，但 top `.SUBCKT full_bandgap vdd` 缺少完整外部端口，也没有可直接对应的 post-layout testbench；不能直接纳入。 |
| [`module_1_bandgap_reference.part_3_layout.OTA_layout.full_OTA`](../tasks/IHP-AnalogAcademy/cases/module_1_bandgap_reference.part_3_layout.OTA_layout.full_OTA.toml) | **include** | 上游同时提供 layout schematic、`two_stage_OTA_layout.cdl`、`two_stage_OTA_layout.gds`、extracted netlist 和 minimal/maximal DRC reports；这是可复用的完整 OTA 版图组。 |
| [`module_1_bandgap_reference.part_3_layout.OTA_layout.input_pair`](../tasks/IHP-AnalogAcademy/cases/module_1_bandgap_reference.part_3_layout.OTA_layout.input_pair.toml) | **include** | 上游同时提供 common-centroid schematic、CDL、`input_common_centroid.gds` 和 extracted netlist；版图和电路对象闭合，可作为 matching/layout block。 |
| [`module_1_bandgap_reference.part_3_layout.OTA_layout.input_stage`](../tasks/IHP-AnalogAcademy/cases/module_1_bandgap_reference.part_3_layout.OTA_layout.input_stage.toml) | **defer** | 有 GDS 和 extracted netlist，但缺 source CDL、DRC evidence 和独立 testbench；更像 full OTA 内部 block，不能先拆成独立任务。 |
| [`module_1_bandgap_reference.part_3_layout.OTA_layout.output_stage`](../tasks/IHP-AnalogAcademy/cases/module_1_bandgap_reference.part_3_layout.OTA_layout.output_stage.toml) | **include** | 上游同时提供 output-stage schematic、CDL、`output_stage.gds` 和 extracted netlist；版图、源网表和抽取结果齐全，可复用为物理 block。 |
| [`module_1_bandgap_reference.part_3_layout.startup_circuit`](../tasks/IHP-AnalogAcademy/cases/module_1_bandgap_reference.part_3_layout.startup_circuit.toml) | **defer** | 有 startup schematic 和 GDS，但没有对应 source/extracted netlist、DRC/LVS evidence 或 startup testbench；应先作为 BGR 的内部参考。 |
| [`module_2_50GHz_MPA.part_1_biasing.bias_1_fingers`](../tasks/IHP-AnalogAcademy/cases/module_2_50GHz_MPA.part_1_biasing.bias_1_fingers.toml) | **exclude** | Qucs RF/HBT biasing deck，依赖外部用户库；没有公开 PDK transistor layout contract、GDS/LVS/DRC 任务证据。 |
| [`module_2_50GHz_MPA.part_1_biasing.bias_2_stability`](../tasks/IHP-AnalogAcademy/cases/module_2_50GHz_MPA.part_1_biasing.bias_2_stability.toml) | **exclude** | Qucs stability 分析和外部 HBT model，不是可交给 Layout Agent 的公开 transistor layout case。 |
| [`module_2_50GHz_MPA.part_2_matching_ideal.input_matching`](../tasks/IHP-AnalogAcademy/cases/module_2_50GHz_MPA.part_2_matching_ideal.input_matching.toml) | **exclude** | Qucs Smith-chart/理想 L/C matching source；没有 process-native physical implementation 和 candidate-GDS judge。 |
| [`module_2_50GHz_MPA.part_3_nonlinear_analysis.harmonic_balance`](../tasks/IHP-AnalogAcademy/cases/module_2_50GHz_MPA.part_3_nonlinear_analysis.harmonic_balance.toml) | **exclude** | Qucs/Xyce harmonic-balance characterization deck，只有 RF 仿真，不是 PDK layout 输入。 |
| [`module_2_50GHz_MPA.part_3_nonlinear_analysis.load_pull_final`](../tasks/IHP-AnalogAcademy/cases/module_2_50GHz_MPA.part_3_nonlinear_analysis.load_pull_final.toml) | **exclude** | Qucs/Xyce load-pull 仿真和外部 HBT model；没有可公开复用的 transistor layout 实现。 |
| [`module_2_50GHz_MPA.part_4_layout_EMsims.BJT_core`](../tasks/IHP-AnalogAcademy/cases/module_2_50GHz_MPA.part_4_layout_EMsims.BJT_core.toml) | **exclude** | OpenEMS core/port geometry 产生 S-parameter，目标是 EM reduced-order model，不是普通 DRC/LVS transistor layout。 |
| [`module_2_50GHz_MPA.part_4_layout_EMsims.T_connection_post_layout`](../tasks/IHP-AnalogAcademy/cases/module_2_50GHz_MPA.part_4_layout_EMsims.T_connection_post_layout.toml) | **exclude** | 消费既有 EM T-connection 子电路的 post-layout 仿真；没有待布局的公开源网表和版图任务契约。 |
| [`module_2_50GHz_MPA.part_4_layout_EMsims.T_connection_subcircuit`](../tasks/IHP-AnalogAcademy/cases/module_2_50GHz_MPA.part_4_layout_EMsims.T_connection_subcircuit.toml) | **exclude** | 是 OpenEMS S-parameter wrapper/custom ports，不是 PDK transistor netlist-to-GDS case。 |
| [`module_2_50GHz_MPA.part_4_layout_EMsims.core_post_layout`](../tasks/IHP-AnalogAcademy/cases/module_2_50GHz_MPA.part_4_layout_EMsims.core_post_layout.toml) | **exclude** | Qucs/Xyce 消费 EM core 的仿真 source；缺独立 layout 输入、DRC/LVS 和普通后仿评估。 |
| [`module_3_8_bit_SAR_ADC.part_1_comparator`](../tasks/IHP-AnalogAcademy/cases/module_3_8_bit_SAR_ADC.part_1_comparator.toml) | **defer** | 有 dynamic comparator 原理图、transient 和 mismatch testbench，但没有该 case 自己的 GDS；part-5 有一个需要先核对拓扑/端口对应关系的物理 comparator。 |
| [`module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate`](../tasks/IHP-AnalogAcademy/cases/module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate.toml) | **exclude** | pinned upstream 只有 schematic/testbench；此前 Bench 中的 reference GDS、qualification 和 calibrate 文件均为本仓库自造，已经删除。 |
| [`module_3_8_bit_SAR_ADC.part_2_digital_comps.algorithm.sar_logic`](../tasks/IHP-AnalogAcademy/cases/module_3_8_bit_SAR_ADC.part_2_digital_comps.algorithm.sar_logic.toml) | **exclude** | Verilog 行为级 SAR logic 和 mixed-signal bridge，没有 PDK transistor layout 实现。 |
| [`module_3_8_bit_SAR_ADC.part_2_digital_comps.bootstrap_switch`](../tasks/IHP-AnalogAcademy/cases/module_3_8_bit_SAR_ADC.part_2_digital_comps.bootstrap_switch.toml) | **exclude** | 有 MOS/CMIM 原理图和 testbench，但没有上游 GDS/LVS/DRC 完整物理实现；不能自行补画。 |
| [`module_3_8_bit_SAR_ADC.part_2_digital_comps.nand_gate`](../tasks/IHP-AnalogAcademy/cases/module_3_8_bit_SAR_ADC.part_2_digital_comps.nand_gate.toml) | **exclude** | 四 MOS 原理图和逻辑 testbench，没有可公开复用的上游版图。 |
| [`module_3_8_bit_SAR_ADC.part_3_array_components.C-DAC`](../tasks/IHP-AnalogAcademy/cases/module_3_8_bit_SAR_ADC.part_3_array_components.C-DAC.toml) | **exclude** | CMIM 阵列只有原理图，没有上游 GDS/抽取/DRC/LVS 完整实现。 |
| [`module_3_8_bit_SAR_ADC.part_3_array_components.switch_array`](../tasks/IHP-AnalogAcademy/cases/module_3_8_bit_SAR_ADC.part_3_array_components.switch_array.toml) | **exclude** | hierarchical T_gate/inverter array 只有 source；child 版图本身也不存在，不能把层次结构转换成自造 reference。 |
| [`module_3_8_bit_SAR_ADC.part_4_SAR_ADC`](../tasks/IHP-AnalogAcademy/cases/module_3_8_bit_SAR_ADC.part_4_SAR_ADC.toml) | **exclude** | 混合信号教程把 Verilog、bridge、switch/C-DAC/comparator 串起来，没有完整 transistor physical implementation。 |
| [`module_3_8_bit_SAR_ADC.part_5_analog_layout.comparator`](../tasks/IHP-AnalogAcademy/cases/module_3_8_bit_SAR_ADC.part_5_analog_layout.comparator.toml) | **include** | 上游提供 `DIFF_COMPARATOR.gds`/flat GDS、LVS netlist、PEX 输出、layout schematic 和 post-layout comparator/offset testbench；这是现有最完整的物理 comparator。 |
| [`utils.gmid_demonstration`](../tasks/IHP-AnalogAcademy/cases/utils.gmid_demonstration.toml) | **exclude** | 只有 gm/Id demonstration testbench/support files，没有待布局的 design source 或上游版图。 |

## 进入 Bench 的硬性规则

每个 `include` case 后续只能做“封装和验证”：从 pinned upstream 复制已有 GDS、
CDL/extracted netlist、DRC/LVS/PEX 和 testbench，记录原路径、commit、hash、
license，并在一个统一 TOML 中声明输入、约束、评估、reference 和 qualification。
不得为缺失版图编写新的 layout.py/generator/reference GDS，也不得把历史
`PEX_Demo` 当作公开资产。若源电路与版图端口或网表无法闭合，立即降为 `defer`。
