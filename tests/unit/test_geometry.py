import copy
import json
from pathlib import Path

import pytest

from benchmarking.geometry import validate_constraints

pytestmark = pytest.mark.unit
DATA = json.loads((Path(__file__).resolve().parents[2] / 'tasks/IHP-AnalogAcademy/cases/assets/module_3_8_bit_SAR_ADC.part_2_digital_comps.T_gate/inputs/constraints.json').read_text())


@pytest.mark.parametrize('change', ['unknown', 'negative', 'duplicate', 'wrong_layer', 'unbound_area', 'nan'])
def test_geometry_requirements_reject_unsupported_or_ambiguous_semantics(change):
    data = copy.deepcopy(DATA)
    if change == 'unknown':
        data['hard'][0]['type'] = 'looks_symmetric'
    elif change == 'negative':
        data['hard'][1]['min_access_square_um'] = -1
    elif change == 'duplicate':
        data['hard'][1]['names'].append('VIN')
    elif change == 'wrong_layer':
        data['hard'][1]['pin_layer'] = [8, True]
    elif change == 'unbound_area':
        data['quality'][0]['layers_from'] = 'missing'
    else:
        data['hard'][0]['max_width_um'] = float('nan')
    with pytest.raises((ValueError, TypeError)):
        validate_constraints(data)
