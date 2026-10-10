"""Load the packaged pedestal and exercise IK without a renderer or CAN."""
import argparse
import json
import os
from pathlib import Path
import statistics
import time

os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
import numpy as np
from openarm_control import Kinematics, register_common_args, register_ik_args, setup_from_args, ik_params_from_args

root = Path(__file__).resolve().parent
p = argparse.ArgumentParser()
register_common_args(p)
register_ik_args(p)
args = p.parse_args(['--xml', str(root / 'openarm_mujoco/v2/pedestal/pedestal.xml'),
                     '--mode', 'bimanual', '--max-iters', '10', '--dt', '0.01',
                     '--damping', '0.1', '--posture-cost', '0.01', '--lm-damping', '0.01',
                     '--limit-velocity', '--config', str(root / 'config/ik.yaml')])
setup = setup_from_args(args)
kin = Kinematics(setup, ik_params_from_args(args))
poses = {side: setup.read_ee_pose(side).copy() for side in setup.sides}
durations = []
for i in range(110):
    for side, pose in poses.items():
        target = pose.copy()
        target[0] += 0.005 * np.sin(i / 20)
        kin.set_target(side, target)
    start = time.perf_counter()
    q = kin.solve()
    elapsed = (time.perf_counter() - start) * 1000
    assert q is not None and q.shape == (16,) and np.isfinite(q).all()
    if i >= 10:
        durations.append(elapsed)
print(json.dumps({'samples': len(durations), 'median_ms': statistics.median(durations),
                  'p95_ms': float(np.percentile(durations, 95)), 'max_ms': max(durations),
                  'scope': 'small-motion IK only; no renderer, CAN, headset or real-time guarantee'}, indent=2))
