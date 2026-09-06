"""Check repository-local Markdown links without fetching third-party checkouts."""

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'\[[^\]\n]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')


def anchors(content):
    result = set(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)', content))
    seen = {}
    for title in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', content, re.MULTILINE):
        slug = re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')
        count = seen.get(slug, 0)
        result.add(slug + (f'-{count}' if count else ''))
        seen[slug] = count + 1
    return result


def check(root=ROOT):
    paths = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root).decode().split('\0')
    errors = []
    for name in sorted(set(paths)):
        if not name.endswith('.md') or name.startswith('third_party/'):
            continue
        source = root / name
        if source.resolve() != source or not source.is_file():
            errors.append(name + ' (document must be a regular file inside the checkout)')
            continue
        content = source.read_text()
        for match in LINK.finditer(content):
            url = urlsplit(match[1].strip('<>'))
            if url.scheme or url.netloc:
                continue
            target = (source.parent / unquote(url.path)).resolve() if url.path else source
            line = content.count('\n', 0, match.start()) + 1
            label = f'{name}:{line}: {match[1]}'
            if not target.is_relative_to(root):
                errors.append(label + ' (outside this repository)')
                continue
            if target.relative_to(root).parts[:1] == ('third_party',):
                continue  # Explicit submodule links require that optional checkout.
            if not target.exists():
                errors.append(label + ' (missing target)')
            elif url.fragment and target.suffix == '.md' and unquote(url.fragment) not in anchors(target.read_text()):
                errors.append(label + ' (missing anchor)')
    return errors


if __name__ == '__main__':
    failures = check()
    for failure in failures:
        print(failure, file=sys.stderr)
    print(f'Markdown links: {len(failures)} error(s); remote and optional submodule targets were not fetched.')
    raise SystemExit(bool(failures))
