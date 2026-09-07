import copy

import pytest

from benchmarking.geometry import validate_constraints

pytestmark = pytest.mark.unit
DATA = {
    'schema_version': 1,
    'hard': [
        {'id': 'outline', 'type': 'bbox_max', 'functional_layers': [[1, 0]],
         'max_width_um': 10.0, 'max_height_um': 10.0},
        {'id': 'ports', 'type': 'named_metal_ports', 'names': ['VIN'],
         'drawing_layer': [8, 0], 'pin_layer': [8, 0], 'text_layer': [8, 0],
         'connectivity_layer': 'metal1', 'min_access_square_um': 0.1},
    ],
    'quality': [{'id': 'area', 'type': 'functional_bbox_area', 'layers_from': 'outline'}],
}


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
