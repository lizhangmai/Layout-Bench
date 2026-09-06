#!/usr/bin/env bash
set -euo pipefail

if [[ $# -eq 0 ]]; then
    set -- agent evaluator preparer simulator extractor model-compiler
fi
for target in "$@"; do
    case "${target}" in
        tools|agent|evaluator|preparer|simulator|extractor|model-compiler) ;;
        *) echo "Unknown toolchain target: ${target}" >&2; exit 2 ;;
    esac
    echo "Checking layout-bench-${target}:local"
    docker run --rm --network none -i "layout-bench-${target}:local" \
        bash -es -- "${target}" <<'CHECK'
test "$(id -u)" -ne 0
python - <<'PY'
import importlib.util
import subprocess
import pya
import psutil
import tkinter
assert pya.__version__ in subprocess.check_output(['klayout', '-b', '-v'], text=True)
assert pya.Box(0, 0, 10, 20).area() == 200
assert psutil.Process().pid > 0
assert tkinter.Tcl().eval('expr {2 + 3}') == '5'
for name in ('benchmarking', 'pytest', 'flake8'):
    assert importlib.util.find_spec(name) is None, name
print('Python KLayout', pya.__version__)
PY
printf '%s\n' 'puts "Embedded Ruby #{RUBY_VERSION}"' > /tmp/runtime.rb
klayout -b -r /tmp/runtime.rb
test ! -e /home/ubuntu/.codex/auth.json
test ! -e /home/ubuntu/.codex/config.toml
if [[ "$1" == agent || "$1" == tools ]]; then
    codex --version
    codex exec --help > /dev/null
    test -x /opt/codex/bin/codex-code-mode-host
    test -x /opt/codex/codex-resources/bwrap
else
    ! command -v codex
    test ! -e /opt/codex
fi
if [[ "$1" == preparer || "$1" == tools ]]; then
    xschem --version
else
    ! command -v xschem
fi
if [[ "$1" == simulator || "$1" == tools ]]; then
    ngspice --version
else
    ! command -v ngspice
fi
if [[ "$1" == extractor || "$1" == tools ]]; then
    test "$(magic --version)" = "8.3.678"
else
    ! command -v magic
fi
if [[ "$1" == model-compiler || "$1" == tools ]]; then
    openvaf --version
else
    ! command -v openvaf
fi
CHECK
done
