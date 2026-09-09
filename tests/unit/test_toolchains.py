import pytest

from benchmarking.toolchains import load_toolchain

pytestmark = pytest.mark.unit


@pytest.fixture(params=[False, True], ids=["standalone", "embedded"])
def toolchain_config(request, tmp_path):
    def write(content):
        if request.param:
            content = ('schema_version = 2\nkind = "layout_case"\n[toolchain]\n'
                       + content.replace('[', '[toolchain.'))
        path = tmp_path / "tools.toml"
        path.write_text(content)
        return path
    return write


def test_external_adapter_can_be_bound_without_changing_task_or_evaluator(toolchain_config):
    config = toolchain_config('''schema_version = 1
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


def test_unknown_binding_fails_before_backend_creation(toolchain_config):
    config = toolchain_config('''schema_version = 1
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


@pytest.mark.parametrize("content, message", [
    ('schema_version = 2\nkind = "layout_case"\n', "does not declare a toolchain"),
    ('schema_version = 1\nkind = "netlist_to_gds"\n', "schema-2 layout_case"),
    ('schema_version = 3\nkind = "layout_case"\n', "schema-2 layout_case"),
    (('schema_version = 2\nkind = "layout_case"\n[toolchain]\nschema_version = 2\n'
      '[toolchain.backends]\n[toolchain.bindings]\n'), "Unsupported toolchain schema_version"),
])
def test_invalid_embedded_toolchain_is_rejected(tmp_path, content, message):
    config = tmp_path / "case.toml"
    config.write_text(content)
    with pytest.raises(ValueError, match=message):
        load_toolchain(config, factories={})
