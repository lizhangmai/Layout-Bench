# 公开参考解

[reference.gds](reference.gds) 是本题可直接重评的公开答案，顶层为 `T_gate`。它通过冻结规则下的 DRC/LVS、外形与端口检查，以及全部已声明的后仿限值。资格范围和反例见 [qualification](../qualification/README.md)。

[layout.py](layout.py) 只使用经过审查的 SG13G2 nmos、pmos、ptap1、ntap1 原语，按权威网表独立布置并连接两只 MOS；不读取课程参考版图或历史候选。nMOS 为 W/L = 1 µm/0.13 µm，pMOS 为 2 µm/0.13 µm。GDS 使用确定性写出选项，不写入生成时刻。[generation.json](generation.json) 记录实际镜像、生成命令、脚本摘要、PDK view 摘要及 GDS 摘要；生成日志见 [generation.log](generation.log)。

先按根 [README](../../../README.md#quick-start-no-model-key-required) 完成快速开始，然后从仓库根独立重建：

```bash
uv run --locked python tasks/academy-tgate/reference/generate.py \
  build/runs/preview/prepared/pdk-view build/runs/tgate-reference --image layout-bench-tools:local
```

重评已发布答案：

```bash
uv run --locked python main.py evaluate tasks/academy-tgate/task.toml \
  tasks/academy-tgate/reference/reference.gds \
  --toolchain build/runs/preview/prepared/toolchain.toml --output build/runs/tgate-evaluation
```

使用自定义镜像或准备目录时同步修改路径与 `--image`，每次选择新输出目录。

`generate.py` 的 `n_width` Python 参数仅用于资格脚本构造尺寸错误反例，公开参考使用默认 1 µm。本目录允许用户下载和调试，但不在 `task.toml` 的输入清单中；标准求解运行不会获得参考 GDS、生成器或资格材料。
