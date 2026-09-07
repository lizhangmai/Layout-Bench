"""Public task qualification with real PDK tools and independently generated assets."""

import json
import runpy
from pathlib import Path

import pytest

from benchmarking.environment import prepare_pdk
from benchmarking.files import Asset
from benchmarking.prepare_support import prepare_support
from benchmarking.tasks import load_task
from benchmarking.toolchains import load_toolchain

pytestmark = [pytest.mark.integration, pytest.mark.acceptance, pytest.mark.acceptance_eda]
ROOT = Path(__file__).resolve().parents[2]
CASE_ID = 'module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate'
TASK = ROOT / f'tasks/IHP-AnalogAcademy/cases/assets/{CASE_ID}'
CONFIG = ROOT / f'tasks/IHP-AnalogAcademy/cases/{CASE_ID}.toml'


def test_public_task_reference_invalid_cases_and_pre_post_measurements(tmp_path):
    pdk = ROOT / 'third_party/IHP-Open-PDK'
    for profile, target in [('klayout', 'klayout'), ('magic', 'magic'), ('mos-models', 'models')]:
        prepare_support(pdk, ROOT / f'technology/sg13g2/{profile}.json', tmp_path / target)
    prepare_pdk(pdk, tmp_path / 'view')
    config = (TASK / 'qualification/toolchain.toml').read_text()
    for source, target in [('klayout-ports', 'klayout'), ('magic', 'magic'), ('mos-models', 'models')]:
        config = config.replace(f'build/support/sg13g2-{source}', str(tmp_path / target))
    toolchain = tmp_path / 'toolchain.toml'
    toolchain.write_text(config)
    qualify = runpy.run_path(str(TASK / 'qualification/run.py'))['qualify']
    summary, reports = qualify(tmp_path / 'view', toolchain, tmp_path / 'qualification')
    assert summary['qualified'], {k: v['jobs'] for k, v in summary['cases'].items() if not v['verified']}
    ref = reports['reference']
    assert ref['metrics']['on_resistance']['value'] == pytest.approx(5098, rel=.01)
    assert ref['metrics']['off_current']['value'] < 1e-8
    assert reports['slow']['physical_valid'] is True
    assert reports['slow']['metrics']['rise_delay_20']['status'] == 'failed'
    assert reports['slow']['quality_eligible'] is False
    assert ref['metrics']['area']['value'] == pytest.approx(118.125)
    for variant in ('translated', 'hierarchy'):
        assert reports[variant]['metrics']['area']['value'] == ref['metrics']['area']['value']
        assert reports[variant]['metrics']['rise_delay_20']['value'] == pytest.approx(ref['metrics']['rise_delay_20']['value'], rel=.01)
    evidence = ref['jobs']['parasitics']['evidence']
    root = tmp_path / 'qualification/reference/evaluation'
    aliases = json.loads((root / evidence['port_aliases']['path']).read_text())
    interface = json.loads((root / evidence['interface_check']['path']).read_text())
    assert set(aliases['aliases']) == {'!CONTROL'}
    assert len(interface['ports']) == 6 and len(set(interface['ports'])) == 6
    assert interface['ports'][2] == aliases['aliases']['!CONTROL'].upper()
    assert interface['ports'][3] == 'CONTROL'
    # Binding errors cannot turn a previous LVS report into evidence for a new GDS.
    task = load_task(CONFIG)
    outputs = ref['jobs']['lvs']['outputs']
    inputs = {'layout': Asset((tmp_path/'qualification/wrong_size/reference.gds').read_bytes(), 'gds'),
              'task': task.evaluation_inputs()['task'], 'constraints': task.evaluation_inputs()['input:constraints'],
              **{name: Asset((root / spec['path']).read_bytes(), spec['format']) for name, spec in outputs.items()}}
    with pytest.raises(ValueError, match='binding differs'):
        load_toolchain(toolchain)['layout.constraints'].run(next(j for j in task.evaluation.jobs if j.id == 'geometry'), inputs)
    calibrate = runpy.run_path(str(TASK / 'qualification/calibrate.py'))['calibrate']
    pre = calibrate(toolchain, tmp_path/'klayout', tmp_path/'schematic')
    assert pre['outcome'] == 'passed', pre['jobs']
    assert pre['metrics']['rise_delay_20']['value'] < ref['metrics']['rise_delay_20']['value']
    # Public reference and qualification assets are absent from standard solver inputs.
    task.materialize(tmp_path/'solver')
    assert not (tmp_path/'solver/reference').exists()
    assert not (tmp_path/'solver/qualification').exists()
