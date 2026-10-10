"""Fault-injection checks using a driver that never connects to hardware."""
import importlib
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'nodes/dora-openarm/src'))
from dora_openarm.session import Session, GuardFault
from dora_openarm_kinematics import ik
from dora_openarm_dataset_recorder.main import Episode, DatasetWriter, FrequencyDetector, episode_frequencies


class Driver:
    def __init__(self):
        self.q = np.zeros(8)
        self.sent = []
        self.starts = self.stops = 0
        self.fail_send = False
    def start(self): self.starts += 1
    def stop(self): self.stops += 1
    def fetch_position(self, refresh=True): return self.q.copy()
    def fetch_state(self, refresh=True): return {k: self.q.copy() for k in ('qpos','qvel','qtorque','tmos','trotor')}
    def send_position(self, q):
        if self.fail_send: raise RuntimeError('injected driver failure')
        self.sent.append(q.copy())
        self.q = q.copy()


@pytest.fixture
def runtime():
    clock = [0.0]
    driver = Driver()
    outputs = []
    session = Session(lambda: driver, lambda *o: outputs.append(o), side='right', clock=lambda: clock[0])
    return session, driver, clock, outputs


def test_no_driver_start_until_explicit_command(runtime):
    session, driver, clock, outputs = runtime
    session.target(np.ones(8), 0)
    assert driver.starts == 0 and driver.sent == []
    session.start(); session.start()
    assert driver.starts == 1


@pytest.mark.parametrize('age', [0.51, -0.1, float('nan'), float('inf')])
def test_old_or_invalid_target_refused(runtime, age):
    s,d,c,o=runtime; s.start()
    with pytest.raises(GuardFault): s.target(np.zeros(8), age)
    assert not d.sent


@pytest.mark.parametrize('value', [np.zeros(7), [float('nan')]*8, [float('inf')]*8])
def test_bad_vectors_refused(runtime, value):
    s,d,c,o=runtime; s.start()
    with pytest.raises(GuardFault): s.target(value, 0)
    assert not d.sent


def test_no_target_timeout_and_manual_restart(runtime):
    s,d,c,o=runtime; s.start(); c[0]=0.51
    with pytest.raises(GuardFault): s.check_timeouts()
    s.stop('target timeout'); s.target(np.ones(8),0)
    assert d.stops==1 and not d.sent and s.status=='stopped'
    assert ('safety_stop','target timeout') in o
    s.start(); assert d.starts==2


def test_feedback_timeout_even_when_targets_continue(runtime):
    s,d,c,o=runtime; s.start(); c[0]=0.4; s.target(np.zeros(8),0); c[0]=0.6
    with pytest.raises(GuardFault, match='feedback'): s.check_timeouts()


def test_tracking_error_refused(runtime):
    s,d,c,o=runtime; s.start(); d.q[0]=0.36
    with pytest.raises(GuardFault, match='differs'): s.feedback()


def test_wall_clock_limits_include_gripper(runtime):
    s,d,c,o=runtime; s.start(); s.status='aligned'; c[0]=0.01; s.target(np.ones(8),0)
    np.testing.assert_allclose(d.sent[-1],s.caps*0.01)
    c[0]=0.0101; s.target(np.ones(8),0)
    np.testing.assert_allclose(d.sent[-1]-d.sent[-2],s.caps*0.0001)
    assert np.array_equal(o[-1][1],d.sent[-1])


def test_alignment_never_jumps_directly_to_target(runtime):
    s,d,c,o=runtime; s.start(); c[0]=0.01; s.target(np.full(8,0.05),0)
    assert s.status=='aligned'
    assert np.all(np.abs(d.sent[-1]) <= s.caps * 0.01)  # Transition remains bounded.


def test_failed_stop_keeps_driver_for_cleanup(runtime):
    s,d,c,o=runtime; s.start()
    def fail(): raise RuntimeError('stop failure')
    d.stop=fail
    with pytest.raises(RuntimeError): s.stop()
    assert s.arm is d


def event(name, q, stamp):
    key = 'pose' if name.startswith('target_') else 'qpos'
    return {'type':'INPUT','id':name,'value':pa.array([{key:q}]),'metadata':{'timestamp':stamp}}


def run_ik(monkeypatch, events, sides=('right','left')):
    class Kin:
        def __init__(self,*args):
            self.setup=SimpleNamespace(sides=sides); self.pending=set(sides); self.synced=[]
        def set_target(self,s,q): self.pending.discard(s)
        def set_gripper(self,s,q): pass
        def ready(self): return not self.pending
        def sync(self,q): self.synced.append(q.copy())
        def update_measured_state(self,q): pass
        def solve(self): self.pending=set(sides); return np.zeros(16)
    outputs=[]; kin=Kin()
    class Node:
        def __iter__(self): return iter(events)
        def send_output(self,*args): outputs.append(args)
    monkeypatch.setattr(ik,'Kinematics',lambda *args:kin)
    monkeypatch.setattr(ik,'setup_from_args',lambda args:None)
    monkeypatch.setattr(ik,'ik_params_from_args',lambda args:None)
    monkeypatch.setattr(ik.dora,'Node',Node)
    monkeypatch.setattr(ik.time,'time_ns',lambda:1_000_000_000)
    ik._run(SimpleNamespace(require_feedback=True,input_timeout=0.5))
    return kin, [o for o in outputs if o[0].startswith('position_')]


def test_ik_requires_fresh_both_feedback_and_controllers(monkeypatch):
    events=[event('feedback_right',[0]*8,900_000_000),event('feedback_left',[0]*8,900_000_000),
            event('target_right',[0,0,0,1,0,0,0,0],800_000_000),event('target_left',[0,0,0,1,0,0,0,0],950_000_000)]
    kin,out=run_ik(monkeypatch,events)
    assert len(out)==2 and len(kin.synced)==1
    assert out[0][2]['timestamp']==800_000_000


@pytest.mark.parametrize('bad_input', ['feedback_left','target_left'])
def test_ik_rejects_stale_side(monkeypatch,bad_input):
    events=[event('feedback_right',[0]*8,900_000_000),event('feedback_left',[0]*8,900_000_000),
            event('target_right',[0,0,0,1,0,0,0,0],900_000_000),event('target_left',[0,0,0,1,0,0,0,0],900_000_000)]
    for e in events:
        if e['id']==bad_input: e['metadata']['timestamp']=100_000_000
    _,out=run_ik(monkeypatch,events); assert not out


def test_nominal_detector_does_not_claim_ik_1hz():
    detector=FrequencyDetector([{'id':'ik','inputs':{'tick':'dora/timer/secs/1'}}])
    assert detector.detect('ik/position_right') is None


def test_measured_frequencies_persist_per_episode(tmp_path):
    e=Episode();e.right_action_timestamps=[0,10_000_000,20_000_000];e.right_observation_timestamps=[0,50_000_000];e.camera_timestamps={'head_left':[0,33_000_000]}
    assert episode_frequencies(e)['action']['arms']['right']==100
    writer=DatasetWriter(tmp_path,'dataset',{});writer.finish_episode(e)
    result=yaml.safe_load((tmp_path/'dataset/metadata.yaml').read_text())
    assert result['episodes'][0]['measured_frequencies']['obs']['arms']['right']==20


def test_all_real_graphs_use_feedback_and_actual_sent_actions():
    for p in (ROOT/'dataflows').glob('*/*.yaml'):
        nodes=yaml.safe_load(p.read_text())['nodes']; byid={n['id']:n for n in nodes}
        for n in nodes:
            if not n['id'].startswith('follower-'): continue
            side=n['id'].split('-')[1]
            assert '--require-feedback' in byid['ik']['args']
            assert byid['ik']['inputs']['feedback_'+side]['source']==n['id']+'/state'
            assert byid['recorder']['inputs']['arm_'+side+'_action']==n['id']+'/action'

@pytest.mark.parametrize('ending', ['eof', 'stop', 'send_failure', 'timeout_fault'])
def test_follower_cleanup_with_pinned_dora_events(monkeypatch, ending):
    driver=Driver(); driver.fail_send=ending=='send_failure'
    fake_driver=SimpleNamespace(Config=lambda _:None,SingleArmDriver=lambda *args:driver)
    monkeypatch.setitem(sys.modules,'openarm_driver',fake_driver)
    main=importlib.import_module('dora_openarm.main')
    monkeypatch.setattr(main,'openarm_driver',fake_driver)
    events=[{'type':'INPUT','id':'command','value':pa.array(['start']),'metadata':{'timestamp':time.time_ns()}},
            {'type':'INPUT','id':'request_state','value':pa.array([0]),'metadata':{}}]
    if ending=='send_failure':
        events.append(event('move_position',[0]*8,time.time_ns()))
    if ending=='timeout_fault':
        events.append({'type':'ERROR','error':'Timeout event stream error: Receiver timed out'})
    if ending=='stop': events.append({'type':'STOP'})
    outputs=[]
    class Node:
        def next(self, timeout): return events.pop(0) if events else None
        def send_output(self,*args): outputs.append(args)
    monkeypatch.setattr(main.dora,'Node',Node)
    monkeypatch.setattr(sys,'argv',['dora-openarm','--side','right'])
    if ending=='send_failure':
        with pytest.raises(RuntimeError,match='injected'): main.main()
        assert any(o[0]=='safety_stop' for o in outputs)
    else:
        main.main()
    assert driver.stops==1


def test_historical_frequency_repair_reads_recorded_parquet(tmp_path):
    import importlib.util
    spec=importlib.util.spec_from_file_location('rates',ROOT/'scripts/measure_dataset_rates.py')
    rates=importlib.util.module_from_spec(spec);spec.loader.exec_module(rates)
    import pyarrow.parquet as pq
    (tmp_path/'metadata.yaml').write_text(yaml.safe_dump({'episodes':[{'id':'0'}],'frequencies':{'action':{'arms':{'right':1}}}}))
    dest=tmp_path/'episodes/0/action/arms/right';dest.mkdir(parents=True)
    pq.write_table(pa.table({'timestamp':pa.array([0,10_000_000,20_000_000],type=pa.timestamp('ns'))}),dest/'state.parquet')
    meta,report=rates.measure(tmp_path)
    assert report['frequencies']['action']['arms']['right']==100
    assert meta['frequencies']['action']['arms']['right']==1  # read-only until --update
