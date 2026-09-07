# Convert the authoritative device netlist with KLayout's existing PDK reader.
# No source lines are edited or reparsed by Layout-Bench.
require 'json'
require 'logger'
$logger = Logger.new($stderr)
base = '/workspace/support/ihp-sg13g2/libs.tech/klayout/tech/lvs/rule_decks'
load File.join(base, 'globals.lvs')
load File.join(base, 'custom_reader.lvs')
class SimulationWriter < RBA::NetlistSpiceWriterDelegate
  def write_device(device)
    dc = device.device_class
    raise "Unsupported simulation primitive #{dc.name}" unless %w[sg13_lv_nmos sg13_lv_pmos].include?(dc.name)
    terminals = %w[D G S B].map { |t| net_to_string(device.net_for_terminal(dc.terminal_id(t))) }
    parameters = %w[W L].map { |p| "#{p}=#{device.parameter(p)}u" }
    emit_line((["X#{device.expanded_name}"] + terminals + [dc.name] + parameters).join(' '))
  end
end
n = RBA::Netlist.new
n.read('source.spice', RBA::NetlistSpiceReader.new(CustomReader.new))
writer = RBA::NetlistSpiceWriter.new(SimulationWriter.new)
writer.use_net_names = true
n.write('schematic.spice', writer)
