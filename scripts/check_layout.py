#!/usr/bin/env python3
"""Check workflow references and documentation links without launching nodes."""
from pathlib import Path
import re
import shlex
from urllib.parse import unquote
import yaml

root = Path(__file__).resolve().parents[1]
flows = sorted((root / 'dataflows').glob('*/*.yaml'))
assert len(flows) == 10, f'Expected 10 workflows, found {len(flows)}'
for flow in flows:
    graph = yaml.safe_load(flow.read_text())
    outputs = {n['id']: set(n.get('outputs', [])) for n in graph['nodes']}
    for node in graph['nodes']:
        for source in node.get('inputs', {}).values():
            source = source['source'] if isinstance(source, dict) else source
            if source.startswith('dora/'): continue
            name, output = source.split('/', 1)
            assert output in outputs[name], (flow, source)
        path = node['path']
        if '/' in path:
            assert (flow.parent / path).is_file(), (flow, path)
        env = node.get('env', {})
        for key in ('METADATA_FILE', 'VIEW_CONFIGURATION_FILE'):
            if key in env: assert (flow.parent / env[key]).is_file(), (flow, env[key])
        args = shlex.split(node.get('args', ''))
        for flag in ('--xml', '--config'):
            if flag in args:
                value = args[args.index(flag) + 1]
                if '/' in value: assert (flow.parent / value).is_file(), (flow, value)
        if 'DIRECTORY' in env:
            assert (flow.parent / env['DIRECTORY']).resolve() == root / 'data/raw'
    if flow.stem.startswith('check'):
        assert not any(name.startswith('follower-') or name == 'recorder' for name in outputs)
for doc in [root / 'README.md', root / 'README.zh-CN.md', *sorted((root / 'docs').glob('*.md'))]:
    for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', doc.read_text()):
        if '://' in target or target.startswith('#'): continue
        target = unquote(target.split('#', 1)[0])
        assert (doc.parent / target).exists(), (doc, target)
print(f'Layout checked: {len(flows)} workflows and project documentation links')
