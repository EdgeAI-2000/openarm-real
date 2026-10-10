# Software repair results — 2026-10-10

The repair restores the deployment environments and implements the software fixes described in KNOWN_LIMITATIONS.md. USB stereo is the default transport; Wi-Fi is an explicit optional transport.

## Verification

- Local and Jetson test suites: 80 passed, plus 2 pytest subtests. Fake drivers cover stale/invalid targets, loss of controller or feedback, tracking error, elapsed-time limits, driver exceptions, EOF/STOP cleanup and feedback-aware IK.
- Actual Dora 0.5 runtime with a fake driver: 9 command messages followed by `controller target timeout` and a driver stop. No CAN device or camera is connected by that test.
- Jetson core/hardware/conversion environments restored; dependency checks and hardware import checks passed without constructing a motor driver.
- Jetson IK benchmark: 100 small-target solves, median about 12.1 ms and p95 about 12.3 ms. This is an isolated compute benchmark, not a real-time control guarantee.
- The Jetson USB check dataflow (no follower nodes) ran for 6 seconds with the configured cameras and exited successfully. It did not launch the Quest browser or verify an active headset session.
- Quest 3 was visible as an authorized USB device. Head and both wrist camera paths were present.
- Existing 40-episode raw dataset passed modality/time-overlap preflight after frequency-metadata repair. A copy of the original metadata was saved first. Image/trajectory files and converted LeRobot data were not changed.

## Historical recorded rates

Rates are computed from original source timestamps across the recorded episodes, not inferred from configuration timers:

| Stream | Mean recorded rate |
| --- | ---: |
| Right/left actions | about 69.2 Hz |
| Right/left joint observations | about 20.0 Hz |
| Head left/right images | about 29.9 FPS |
| Wrist left/right images | about 10.0 FPS |

The 30 FPS converted dataset is a resampled representation; it does not prove 30 independent wrist images per second. Improving wrist capture rate requires separate capture/performance investigation.

## Physical scope

No robot follower was launched on the Jetson and no motor-enable or movement command was issued. Guard thresholds, actual braking behavior, camera orientation, headset comfort and CAN mapping still need onsite validation. The retained optional Wi-Fi path requires the operating account to have access to its local TLS key; USB does not use those credentials.

## Directory migration verification

The reorganized tree preserves root install/run/convert commands and the default USB transport. Package imports were rebound to the new editable source locations. All 10 workflow graphs and project documentation links pass the layout checker; the 80-test suite and local IK benchmark pass after migration. Existing raw/converted data and local metadata are preserved, with compatibility links for old data/library paths.
