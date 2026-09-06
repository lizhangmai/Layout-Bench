#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"
test_tmp="$(mktemp -d "${TMPDIR:-/tmp}/layout-bench-pdk.XXXXXX")"
trap 'rm -rf "${test_tmp}"' EXIT
uv run --locked python -m benchmarking.environment third_party/IHP-Open-PDK "${test_tmp}/pdk"
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
    --memory 1g --cpus 1 --pids-limit 64 -i \
    --mount "type=bind,src=${test_tmp}/pdk,dst=/pdk,readonly" \
    -e PYTHONDONTWRITEBYTECODE=1 -e KLAYOUT=1 \
    -e PYTHONPATH=/pdk/ihp-sg13g2/libs.tech/klayout/python:/pdk/ihp-sg13g2/libs.tech/klayout/python/pycell4klayout-api/source/python \
    layout-bench-agent:local python - <<'PY'
import pya
import sg13g2_pycell_lib

layout = pya.Layout()
layout.technology_name = "sg13g2"
# Generic primitive smoke checks, with parameters unrelated to the task witness.
for name, params in (
    ("nmos", {"w": "0.6u", "l": "0.2u", "ng": 1}),
    ("pmos", {"w": "1.5u", "l": "0.3u", "ng": 1}),
    ("ptap1", {"w": "0.8u", "l": "0.8u"}),
    ("ntap1", {"w": "0.8u", "l": "0.8u"}),
):
    cell = layout.create_cell(name, "SG13_dev", params)
    assert cell is not None and not cell.is_empty(), name
    assert not cell.dbbox().empty(), name
    print(name, "generated")
PY
echo 'PASS: reviewed PDK view supports headless MOS/tap generation'
