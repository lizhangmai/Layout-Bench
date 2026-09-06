#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"
test_tmp="$(mktemp -d "${TMPDIR:-/tmp}/layout-bench-task.XXXXXX")"
trap 'rm -rf "${test_tmp}"' EXIT

uv run --locked python -m benchmarking.prepare tasks/IHP-AnalogAcademy/module_3_8_bit_SAR_ADC/part_2_digital_comps/T_gate/source.toml \
    "${test_tmp}/export" \
    --checkout academy=third_party/IHP-AnalogAcademy \
    --checkout pdk=third_party/IHP-Open-PDK
cmp "${test_tmp}/export/T_gate.spice" tasks/IHP-AnalogAcademy/module_3_8_bit_SAR_ADC/part_2_digital_comps/T_gate/inputs/circuit.spice
uv run --locked python main.py task tasks/IHP-AnalogAcademy/module_3_8_bit_SAR_ADC/part_2_digital_comps/T_gate/task.toml \
    --materialize "${test_tmp}/inputs" > "${test_tmp}/task.json"
uv run --locked python -m benchmarking.environment \
    third_party/IHP-Open-PDK "${test_tmp}/pdk" > /dev/null

# This is a source-input preflight in the preparation environment, not a GDS
# evaluator. Read the same configured netlist with the PDK's existing reader.
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
    --memory 1g --cpus 1 --pids-limit 64 -i \
    --mount "type=bind,src=${test_tmp}/pdk,dst=/pdk,readonly" \
    --mount "type=bind,src=${test_tmp}/inputs,dst=/task,readonly" \
    --mount "type=bind,src=${test_tmp}/task.json,dst=/task-config.json,readonly" \
    layout-bench-tools:local bash -s <<'CHECK'
set -eu
cat > /tmp/check.rb <<'RUBY'
require 'json'
require 'logger'
$logger = Logger.new($stderr)
base = '/pdk/ihp-sg13g2/libs.tech/klayout/tech/lvs/rule_decks'
load File.join(base, 'globals.lvs')
load File.join(base, 'custom_reader.lvs')
task = JSON.parse(File.read('/task-config.json'))
netlist = RBA::Netlist.new
netlist.read(task['inputs']['netlist'], RBA::NetlistSpiceReader.new(CustomReader.new))
circuit = netlist.each_circuit.find { |c| c.name.casecmp?(task['netlist_subcircuit']) }
raise 'Configured subcircuit was not read' unless circuit
raise 'Netlist has no recognized devices' if circuit.each_device.to_a.empty?
raise 'Unresolved subcircuits in flat MOS input' unless circuit.each_subcircuit.to_a.empty?
devices = circuit.each_device.map do |d|
  raise "Unsupported primitive #{d.device_class.name}" unless d.device_class.is_a?(RBA::DeviceClassMOS4Transistor)
  { name: d.name, model: d.device_class.name, w_um: d.parameter('W'), l_um: d.parameter('L'),
    terminals: d.device_class.terminal_definitions.to_h { |t| [t.name, d.net_for_terminal(t.id).name] } }
end
puts JSON.generate({circuit: circuit.name, pins: circuit.each_pin.map(&:name), devices: devices})
RUBY
klayout -b -r /tmp/check.rb
CHECK
echo 'PASS: raw schematic re-export matches the task input; configured netlist is readable with the PDK reader'
