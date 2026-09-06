import pytest

from benchmarking.toolchains import load_toolchain

pytestmark = pytest.mark.unit


def test_external_adapter_can_be_bound_without_changing_task_or_evaluator(tmp_path):
    config = tmp_path / "tools.toml"
    config.write_text('''schema_version = 1
[backends.a]
type = "independent-implementation"
settings = { scale = 2 }
[bindings]
"response.ac" = "a"
"response.transient" = "a"
''')
    created = []

    def factory(**settings):
        created.append(settings)
        return object()

    bindings = load_toolchain(config, factories={"independent-implementation": factory})
    assert created == [{"scale": 2}]
    assert bindings["response.ac"] is bindings["response.transient"]


def test_unknown_binding_fails_before_backend_creation(tmp_path):
    config = tmp_path / "tools.toml"
    config.write_text('''schema_version = 1
[backends.a]
type = "custom"
settings = {}
[bindings]
response = "absent"
''')

    def factory(**settings):
        pytest.fail("Invalid configuration must not initialize a tool")

    with pytest.raises(ValueError, match="unknown backend"):
        load_toolchain(config, factories={"custom": factory})
