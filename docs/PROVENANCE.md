# Source provenance

## Snapshot

The initial public release was prepared on 2026-10-10 from an existing OpenArm real-robot deployment. It is a new Git repository containing the current files, not an import of upstream Git history or an official upstream release.

The original packaging manifest was dated 2026-09-12. Before publication, its 311 recorded file hashes were checked: 13 files differed and 1 file was missing. That old manifest was therefore replaced by a fresh `MANIFEST.json` covering this publication. The root manifest excludes its own hash to avoid a self-reference.

## Upstream base revisions

These revisions are copied from the original packaging record; local modifications exist on top of them.

| Component | Recorded base commit |
| --- | --- |
| `openarm_control` | `2f1ee56ef2bf1272329b213a1f0b0768b9d07f2b` |
| `openarm_mujoco` | `a8c979629f2591ad035d99d338ce114969e6cddc` |
| `dora-openarm-webxr` | `9f06915fc2daa79b8342127e222313f6a9f53694` |
| `dora-openarm-kinematics` | `357eb4f0a43a0af5e92aceb7148d04c67163d13c` |
| `dora-openarm` | `d988dd24537d670f07b6d6e85e0cdd25f0b05b82` |
| `dora-openarm-quitter` | `990c2d409b07470df6d715e14b3c1d8227a594ec` |
| `dora-openarm-data-collection-ui` | `e67118f80ddcd266124b642768c5693e8fe27f65` |
| `dora-openarm-dataset-recorder` | `5bf69e2ee24d758d0660dc8a75c37e0fe4522c63` |

The local stereo/wrist/overhead camera integration has no separate upstream revision recorded. The dataset converter is installed separately at commit `a69fe37384e26bb5c3059de4a52cd6e871727011`.

## Deployment modifications already present

- Explicit UI motor start rather than automatic startup.
- USB ADB transport and Quest wake/launch handling.
- Four-camera stereo/wrist recording, headset panels and read-only monitor.
- Optional network D455 JPEG reception and five-camera dataflows.
- Side-specific IK/dataflows and seven-joint velocity configuration.
- OpenArm dataset preflight, conversion wrapper and LeRobot verification.
- DIG task metadata templates.

## Changes made for publication

- Added repository overview, deployment guide, known limitations, root Apache-2.0 license, attribution and `.gitignore`.
- Replaced the stale manifest with current source hashes and provenance.
- Replaced machine-specific editable dependency paths with repository-relative paths in historical requirements records.
- Replaced operator identity and overhead-camera serial/host metadata with example values.
- Excluded recordings, converted datasets, output files, virtual environments, caches, generated package metadata, Git histories and TLS material.
- Preserved control logic, model assets and original component license/copyright notices. The missing Wi-Fi bimanual dataflow was not reconstructed.

The source machine's files were not modified during the initial publication. The later repair update was applied separately with a source backup.

## Software repair update (2026-10-10)

Added the missing Wi-Fi bimanual graph, feedback-aware IK, follower guards and cleanup, actual-command recording, measured episode frequencies, historical frequency repair, source-manifest maintenance and hardware-free tests/CI. Control wrappers/dataflows are modified relative to the initial publication. Physical startup/stop remains the responsibility of the installed driver.

## Directory and documentation update

Split the project overview into complete English and Chinese READMEs. Moved reusable packages to `packages/`, Dora nodes to `nodes/`, workflows to transport-specific `dataflows/` directories, task templates to `metadata/`, utility entrypoints to `scripts/`, and dependency records to `requirements/`. New recordings/conversions use `data/raw/` and `data/lerobot/`. Root install/run/convert entrypoints remain available. Upstream package internals and licenses are retained.
