#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
mode="${1:-check}"
usage() {
    echo 'Usage: bash run.sh check|right|left|bimanual [wifi|usb-stereo] [standard|d455]' >&2
    echo 'd455 is supported for check/bimanual with usb-stereo; standard is the default.' >&2
}
case "$mode" in check|right|left|bimanual) ;; *) usage; exit 2;; esac
transport="${2:-wifi}"
camera_version="${3:-standard}"
if (( $# > 3 )); then usage; exit 2; fi
case "$camera_version" in standard|d455) ;; *) usage; exit 2;; esac
case "$transport" in
    wifi) dataflow="dataflow-jetson-${mode}.yaml" ;;
    usb-stereo)
        dataflow="dataflow-jetson-${mode}-usb-stereo.yaml"
        ;;
    *) usage; exit 2 ;;
esac
camera_suffix=''
if [[ "$camera_version" == d455 ]]; then
    if [[ "$transport" != usb-stereo || ( "$mode" != check && "$mode" != bimanual ) ]]; then
        usage
        exit 2
    fi
    camera_suffix='-d455'
    dataflow="dataflow-jetson-${mode}-usb-stereo-d455.yaml"
fi
source .venv/bin/activate
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONUNBUFFERED=1
export NAME="jetson-${mode}-${transport}${camera_suffix}-$(date -u +%Y%m%d-%H%M%S)-$$"
if [[ "$transport" == wifi ]]; then
    [[ -s config/tls/server.crt && -s config/tls/server.key ]] || { echo 'Generate TLS files first; see README.md.' >&2; exit 1; }
fi
if [[ "$mode" != check ]]; then
    python -c 'import openarm_driver, openarm_can'
    echo 'REAL ROBOT MODE: UI Arm Start enables motors and may move to the initial pose.'
    echo 'Software Stop is not an emergency stop. Keep a physical emergency stop available.'
fi
if [[ "$transport" == usb-stereo ]]; then
    command -v adb >/dev/null || { echo "Install ADB first: sudo apt install adb" >&2; exit 1; }
    camera_device="${STEREO_CAMERA_DEVICE:-/dev/camera_head_stereo}"
    if [[ ! -e "$camera_device" && -e /dev/v4l/by-id/usb-Technologies__Inc._ZED-M-video-index0 ]]; then
        camera_device=/dev/v4l/by-id/usb-Technologies__Inc._ZED-M-video-index0
    fi
    [[ -e "$camera_device" ]] || { echo "Missing stereo camera: $camera_device" >&2; exit 1; }
    export STEREO_CAMERA_DEVICE="$camera_device"

    wrist_left_device="${WRIST_CAMERA_LEFT_DEVICE:-/dev/camera_wrist_left}"
    wrist_right_device="${WRIST_CAMERA_RIGHT_DEVICE:-/dev/camera_wrist_right}"
    wrist_left_by_path=/dev/v4l/by-path/platform-3610000.usb-usb-0:4.4:1.0-video-index0
    wrist_right_by_path=/dev/v4l/by-path/platform-3610000.usb-usb-0:4.3:1.0-video-index0
    if [[ ! -e "$wrist_left_device" && -e "$wrist_left_by_path" ]]; then
        wrist_left_device="$wrist_left_by_path"
    fi
    if [[ ! -e "$wrist_right_device" && -e "$wrist_right_by_path" ]]; then
        wrist_right_device="$wrist_right_by_path"
    fi
    [[ -e "$wrist_left_device" ]] || { echo "Missing left gripper camera: $wrist_left_device" >&2; exit 1; }
    [[ -e "$wrist_right_device" ]] || { echo "Missing right gripper camera: $wrist_right_device" >&2; exit 1; }
    if [[ "$(realpath "$wrist_left_device")" == "$(realpath "$wrist_right_device")" ]]; then
        echo 'Left and right gripper camera paths resolve to the same device.' >&2
        exit 1
    fi
    export WRIST_CAMERA_LEFT_DEVICE="$wrist_left_device"
    export WRIST_CAMERA_RIGHT_DEVICE="$wrist_right_device"
    echo "Cameras: head=$STEREO_CAMERA_DEVICE left-gripper=$WRIST_CAMERA_LEFT_DEVICE right-gripper=$WRIST_CAMERA_RIGHT_DEVICE"
    adb -d get-state 2>/dev/null | grep -qx device || {
        echo 'No authorized Quest USB device. Enable Developer Mode, reconnect the data cable, and accept USB debugging.' >&2
        exit 1
    }
    adb -d reverse tcp:8443 tcp:8443
    usb_launcher_pid=''
    cleanup_usb() {
        if [[ -n "$usb_launcher_pid" ]]; then
            kill "$usb_launcher_pid" 2>/dev/null || true
        fi
        adb -d reverse --remove tcp:8443 >/dev/null 2>&1 || true
    }
    trap cleanup_usb EXIT
    (
        ready=no
        for _ in $(seq 1 100); do
            if curl -fsS --max-time 1 http://127.0.0.1:8443/ >/dev/null 2>&1; then
                ready=yes
                break
            fi
            sleep 0.2
        done
        if [[ "$ready" != yes ]]; then
            echo 'Quest USB launcher: WebXR server did not become ready.' >&2
            exit 1
        fi

        wake_timeout="${QUEST_USB_WAKE_TIMEOUT:-0}"
        if [[ ! "$wake_timeout" =~ ^[0-9]+$ ]]; then
            echo 'Quest USB launcher: QUEST_USB_WAKE_TIMEOUT must be a non-negative integer.' >&2
            exit 1
        fi
        echo 'Quest USB launcher: put on and wake the headset; waiting before opening OpenArm.'
        wake_deadline=$((SECONDS + wake_timeout))
        until adb -d shell dumpsys power 2>/dev/null | grep -q 'mWakefulness=Awake'; do
            if (( wake_timeout > 0 && SECONDS >= wake_deadline )); then
                echo "Quest USB launcher: headset did not wake within ${wake_timeout}s; the dataflow is still running." >&2
                exit 1
            fi
            sleep 0.5
        done

        quest_url='http://localhost:8443/?usb_autostart=1'
        adb -d shell am start \
            -a android.intent.action.VIEW \
            -n com.oculus.vrshell/.MainActivity \
            -d systemux://browser \
            -e uri "$quest_url"
        sleep "${QUEST_USB_AUTOSTART_DELAY:-4}"
        if ! adb -d shell input keyevent KEYCODE_DPAD_CENTER; then
            echo 'Quest USB launcher: automatic Start failed; press Start once in the headset.' >&2
        else
            echo "Quest USB launcher: opened ${quest_url} and sent WebXR Start."
        fi
    ) &
    usb_launcher_pid=$!
    echo 'Mode: USB stereo; keep the Quest awake/on-head and its OpenArm page will launch automatically over the cable.'
else
    echo "Mode: Wi-Fi; Quest: https://192.168.5.70:8443/"
fi
echo 'Collection UI: http://127.0.0.1:8000/'
if [[ "$mode" != check ]]; then
    echo "OpenArm dataset: dora-openarm-data-collection/real_data/$NAME/"
fi
if [[ "$transport" == usb-stereo ]]; then
    if [[ "$camera_version" == d455 ]]; then
        echo 'Camera version: D455 (head stereo + both wrists + network D455; 5 streams)'
    else
        echo 'Camera version: standard (head stereo + both wrists; 4 streams)'
    fi
    echo 'Camera monitor: http://127.0.0.1:8000/monitor (use /monitor on the SSH-forwarded UI)'
fi
cd dora-openarm-data-collection
if [[ "$transport" == usb-stereo ]]; then
    dora run "$dataflow"
else
    exec dora run "$dataflow"
fi
