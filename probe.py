"""Report candidate joint commands. Never imports a driver or opens CAN."""
import time
import dora
import numpy as np

node = dora.Node()
counts = {'left': 0, 'right': 0}
latest = {}
last = time.monotonic()
for event in node:
    if event['type'] == 'STOP':
        break
    if event['type'] != 'INPUT':
        continue
    name = event['id']
    if name == 'command' and event['value'][0].as_py() == 'quit':
        break
    if name in counts:
        q = np.asarray(event['value'].field('qpos')[0].as_py(), dtype=float)
        if q.shape != (8,) or not np.isfinite(q).all():
            raise ValueError(f'Invalid {name} candidate joint command: {q}')
        counts[name] += 1
        latest[name] = np.round(q, 3).tolist()
    elif name == 'tick':
        now = time.monotonic()
        rates = {side: round(count / (now - last), 1) for side, count in counts.items()}
        print(f'IK CANDIDATES Hz={rates} qpos={latest}; these are not measured robot states', flush=True)
        counts = dict.fromkeys(counts, 0)
        last = now
