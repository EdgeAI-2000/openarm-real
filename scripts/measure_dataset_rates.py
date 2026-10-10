#!/usr/bin/env python3
"""Measure raw episode rates from timestamps; optionally repair frequency metadata."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import yaml


def rate(timestamps):
    values = np.asarray(timestamps, dtype=np.int64)
    if len(values) < 2 or np.any(np.diff(values) <= 0):
        return None, 0, 0
    duration = (int(values[-1]) - int(values[0])) / 1e9
    return (len(values) - 1) / duration, len(values) - 1, duration


def measure(dataset):
    metadata = yaml.safe_load((dataset / 'metadata.yaml').read_text())
    totals = defaultdict(lambda: [0, 0.0])
    episodes = {}
    for episode in metadata.get('episodes', []):
        base = dataset / 'episodes' / str(episode['id'])
        result = {'action': {'arms': {}}, 'obs': {'arms': {}}, 'cameras': {}}
        sources = []
        for kind in ('action', 'obs'):
            for side in ('right', 'left'):
                p = base / kind / 'arms' / side / 'state.parquet'
                if p.exists():
                    stamps = pq.read_table(p, columns=['timestamp'])['timestamp'].cast(pa.int64()).to_numpy()
                    sources.append(((kind, 'arms', side), stamps))
        cameras = base / 'cameras'
        if cameras.exists():
            for camera in cameras.iterdir():
                if camera.is_dir():
                    stamps = sorted(int(p.stem) for p in camera.iterdir() if p.stem.isdigit())
                    sources.append((('cameras', camera.name), stamps))
        for keys, stamps in sources:
            hz, count, duration = rate(stamps)
            current = result
            for k in keys[:-1]: current = current[k]
            current[keys[-1]] = hz
            totals[keys][0] += count
            totals[keys][1] += duration
        episodes[str(episode['id'])] = result
    aggregate = {'action': {'arms': {}}, 'obs': {'arms': {}}, 'cameras': {}}
    for keys, (count, duration) in totals.items():
        current = aggregate
        for k in keys[:-1]: current = current[k]
        current[keys[-1]] = count / duration if duration > 0 else None
    return metadata, {'frequencies': aggregate, 'episodes': episodes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--update', action='store_true', help='Back up metadata, then atomically replace its frequency fields.')
    args = parser.parse_args()
    metadata, report = measure(args.dataset)
    if args.update:
        path = args.dataset / 'metadata.yaml'
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = path.with_name(f'metadata.before-rates-{stamp}.yaml')
        shutil.copy2(path, backup)
        metadata.setdefault('nominal_frequencies', metadata.get('frequencies', {}))
        metadata['frequencies'] = report['frequencies']
        metadata['frequency_reference'] = 'measured_from_recorded_source_timestamps'
        for episode in metadata['episodes']:
            episode['measured_frequencies'] = report['episodes'][str(episode['id'])]
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False, encoding='utf-8') as output:
            yaml.safe_dump(metadata, output, sort_keys=False, allow_unicode=True)
            temporary = Path(output.name)
        temporary.chmod(path.stat().st_mode & 0o777)
        temporary.replace(path)
        report['metadata_backup'] = str(backup)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
