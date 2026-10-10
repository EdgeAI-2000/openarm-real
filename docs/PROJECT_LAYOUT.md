# Project layout and migration / 目录与迁移

[English README](../README.md) · [中文说明](../README.zh-CN.md)

The source tree separates reusable libraries, executable nodes, workflow configuration, task metadata and runtime files. USB is the default workflow. Root entrypoints remain `install.sh`, `run.sh` and `convert.sh`.

项目按库、节点、流程配置、任务模板和运行文件组织。USB 仍是默认流程，根目录三个入口命令保持可用。

## Directory responsibilities / 目录职责

| Directory | Contents / 内容 |
| --- | --- |
| `packages/` | Reusable control/model packages; upstream source layout and licenses preserved / 可复用控制与模型包，保留上游内部结构和许可证 |
| `nodes/` | Seven Dora node packages, including camera, WebXR, IK, follower, UI, recorder and quitter / 七个 Dora 节点包 |
| `dataflows/usb/` | `check`, `right`, `left`, `bimanual`, plus D455 check/bimanual / USB 直连流程 |
| `dataflows/wifi/` | Optional check/right/left/bimanual configurations / 可选无线流程 |
| `metadata/` | Task and equipment templates selected by the dataflows / 任务和设备模板 |
| `config/` | IK constraints, camera view settings and local TLS folder / IK 约束与画面配置，TLS 文件仅保留本地 |
| `requirements/` | Version constraints and historical snapshots / 依赖约束与历史环境记录 |
| `scripts/` | IK benchmark, probe, dataset checks and manifest utilities / IK、诊断、数据检查和清单工具 |
| `tests/` | Cross-package fake-driver tests / 跨组件假驱动测试 |
| `docs/` | Deployment, limitations, validation and provenance / 部署、限制、验证和来源 |
| `data/raw/` | Recorded OpenArm datasets, ignored by Git / 原始数据，不上传 |
| `data/lerobot/` | Converted datasets, ignored by Git / 转换数据，不上传 |
| `runtime/` | Generated environment records and logs, ignored by Git / 运行环境记录和日志，不上传 |
| `artifacts/` | Local diagrams and generated deliverables, ignored by Git / 本地流程图和生成文件，不上传 |

## Old to new paths / 旧路径对应

| Previous path | Current path |
| --- | --- |
| `openarm_control/` | `packages/openarm_control/` |
| `openarm_mujoco/` | `packages/openarm_mujoco/` |
| `dora-openarm-data-collection/nodes/` | `nodes/` |
| `dora-openarm-data-collection/dataflow-jetson-*-usb-stereo.yaml` | `dataflows/usb/*.yaml` |
| `dora-openarm-data-collection/dataflow-jetson-*.yaml` | `dataflows/wifi/*.yaml` |
| `dora-openarm-data-collection/metadata_real*.yaml` | `metadata/*.yaml` |
| `preflight.py`, `probe.py`, `probe.sh` | `scripts/` |
| `constraints.txt` | `requirements/constraints.txt` |
| `requirements-*.txt` | `requirements/snapshots/*.txt` |
| `dora-openarm-data-collection/real_data/` | `data/raw/` |
| `lerobot_data/` | `data/lerobot/` |
| `output/` | `artifacts/` |

Examples: `metadata_real_stereo.yaml` becomes `metadata/bimanual-stereo.yaml`; the four-camera USB graph becomes `dataflows/usb/bimanual.yaml`.

## Existing installation / 已有安装

Moving editable packages changes their filesystem paths. Reinstall the editable packages after migration; do not copy or rename a virtual environment to another machine. Keep a source backup and preserve local task/camera settings and recordings.

移动源码后，已有 editable 安装需要重新绑定新路径。迁移前保留源码备份、本地任务和相机设置；不要将虚拟环境直接复制到另一台机器。

```bash
bash install.sh core
bash install.sh hardware
.venv/bin/python scripts/preflight.py
```

Hardware installation only imports the bindings; it does not connect to motors. Dataset conversion retains its separate `.venv-dataset` environment. After moving data, update any external scripts that refer to old dataset paths. Compatibility links on the existing Jetson preserve old library and data paths; fresh clones use the clean layout above.

数据目录迁移后，外部脚本应改用新路径。现有 Jetson 会保留旧库与数据路径的兼容链接；新克隆的仓库采用上述清晰结构。

The installer now writes fresh environment reports under `runtime/requirements/`. Files under `requirements/snapshots/` remain historical references and are not complete lockfiles.

安装器将新环境记录写入 `runtime/requirements/`，避免覆盖仓库中的历史快照；历史快照不等于完整锁定文件。
