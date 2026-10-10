# Known limitations and fixes

## Fixed in the software update

- Added the missing Wi-Fi bimanual dataflow by reusing the existing USB bimanual chain and Wi-Fi WebXR settings.
- Added early launcher errors for missing dataflows/environments. Fresh clones still require `install.sh`; environments are not committed.
- Connected measured follower state to IK, requiring fresh active-side state and controller targets.
- Added finite-vector and timestamp checks, target/feedback watchdogs, tracking-error checks, elapsed-time command limits including the gripper, bimanual peer fault propagation and `finally` cleanup. Faults require manual restart.
- Recorded follower commands after limits rather than raw IK candidates.
- Removed misleading nominal IK action frequency inference. Added per-episode measured rates and a backup-preserving repair tool for old data.
- Added source-manifest regeneration/checking and automated software tests.

## Still requires physical acceptance

- Default timeouts, tracking tolerance and command-rate caps are candidate settings. They have software/fake-driver tests, not real-robot acceptance.
- Command-rate limiting does not guarantee measured physical velocity. Driver startup and stop trajectories are outside that limiter. Stop is not a physical emergency stop.
- Blocking CAN/driver calls can delay the event-loop watchdog. Python process failure, SIGKILL, power loss and bus failure require hardware-level protection.
- Gripper tracking error is excluded because driver units/signs need onsite verification. The command limiter assumes motor-angle radians.
- No task-level collision avoidance or automatic recovery is implemented. This Dora control path does not inherit ROS/MoveIt overlays. Use one controller per bus.
- Camera identities, CAN mapping, zero positions, mechanical limits and initial pose must be verified onsite.

## Reproducibility and data

- `requirements/constraints.txt` pins selected versions, not a complete lockfile. Historical requirements records are not reproducibility guarantees.
- Hardware imports and an IK benchmark do not validate bus/motor communication.
- The snapshot has no original top-level Git history; base revisions and publication changes are in PROVENANCE.md.
- Camera timer settings do not prove achieved FPS. The D455 stream depends on external sender/receiver/ROS bridge services and includes network delay. Streams are not hardware-synchronized.
- Metadata success/valid labels do not independently prove task success. The converter's validator can update input validity flags; preserve backups.
- Standard bimanual training uses both arms; single-arm debugging data is not that 16-dimensional layout.
- Software verification uses fake drivers and local compute only. No headset session, camera capture, motor commands or physical braking tests are included.
