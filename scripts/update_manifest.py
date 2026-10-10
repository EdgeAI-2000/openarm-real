#!/usr/bin/env python3
"""Refresh/check public source hashes using Git's non-ignored file inventory."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
path = ROOT / 'MANIFEST.json'
manifest = json.loads(path.read_text())
files = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).decode().split('\0')
hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(set(files)) if name and name != 'MANIFEST.json' and (ROOT / name).is_file()}
if args.check:
    if hashes != manifest['files']:
        raise SystemExit('Source manifest differs; run python scripts/update_manifest.py')
    print(f'Manifest verified: {len(hashes)} files')
else:
    manifest['files'] = hashes
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'Manifest updated: {len(hashes)} files')
