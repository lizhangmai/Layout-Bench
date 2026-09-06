#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != tools ) ]]; then
    echo 'The toolchain is unified; this check accepts only the tools image.' >&2
    exit 2
fi
image="${LAYOUT_BENCH_TEST_IMAGE:-layout-bench-tools:local}"
echo "Checking unified tool image: ${image}"
docker run --rm --network none -i "${image}" bash -es <<'CHECK'
set -euo pipefail
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
xschem --version
ngspice --version
test "$(magic --version)" = "8.3.678"
openvaf --version
QT_QPA_PLATFORM=offscreen qucs-s --version
qucsator --version
qucsator_rf --version
qucsconv --version
CHECK
