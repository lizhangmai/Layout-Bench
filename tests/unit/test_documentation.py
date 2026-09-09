"""The release link check works in a standalone checkout without optional sources."""

import runpy
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
check = runpy.run_path(str(ROOT / 'scripts/check_docs.py'))['check']


def test_links_stay_inside_repository_and_resolve_anchors(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path/'README.md').write_text('''# Start
[Guide](docs/guide.md#重复标题-1)
[Explicit](docs/guide.md#stable)
[Code](sample.py#L1)
[Optional PDK](third_party/IHP-Open-PDK/README.md)
[Remote](https://example.invalid/missing)
''')
    (tmp_path/'docs').mkdir()
    (tmp_path/'docs/guide.md').write_text('# 重复标题\n# 重复标题\n<a id="stable"></a>\n')
    (tmp_path/'sample.py').write_text('pass\n')
    assert check(tmp_path) == []
    (tmp_path/'README.md').write_text('''[Missing](docs/gone.md)
[Wrong anchor](docs/guide.md#missing)
[Sibling](../another-repository/README.md)
''')
    errors = check(tmp_path)
    assert len(errors) == 3
    assert 'missing target' in errors[0]
    assert 'missing anchor' in errors[1]
    assert 'outside this repository' in errors[2]


def test_tracked_docs_are_checked_even_if_gitignored(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path/'README.md').write_text('[Broken](missing.md)\n')
    subprocess.run(['git', 'add', 'README.md'], cwd=tmp_path, check=True)
    (tmp_path/'.gitignore').write_text('*.md\n')
    (tmp_path/'ignored.md').write_text('[Ignored output](also-missing.md)\n')
    assert len(check(tmp_path)) == 1


def test_document_symlink_does_not_read_outside_checkout(tmp_path):
    root = tmp_path/'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    (tmp_path/'outside.md').write_text('[Must not inspect](sensitive-path.md)\n')
    (root/'README.md').symlink_to(tmp_path/'outside.md')
    errors = check(root)
    assert len(errors) == 1
    assert 'regular file' in errors[0]
    assert 'sensitive-path' not in errors[0]
