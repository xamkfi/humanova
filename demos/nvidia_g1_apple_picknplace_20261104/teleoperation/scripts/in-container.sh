#!/usr/bin/env bash
set -euo pipefail
source /demo/config.env
cd /workspaces/isaaclab_arena

# Serialize all simulation sessions. Re-enter under flock so file checks and
# recorder startup happen while the lock is held.
case "${1:-}" in
    teleop|record|replay)
        if [[ "${HUMANOVA_SIM_LOCK_HELD:-0}" != 1 ]]; then
            exec flock --nonblock --conflict-exit-code 75 /tmp/humanova-simulation.lock \
                env HUMANOVA_SIM_LOCK_HELD=1 bash "$0" "$@"
        fi
        ;;
esac

case "${1:-}" in
    cloudxr)
        # A second launcher must not remove a running runtime's IPC socket.
        exec flock --nonblock --conflict-exit-code 75 /tmp/humanova-cloudxr.lock \
            /isaac-sim/python.sh -m isaacteleop.cloudxr \
            --cloudxr-install-dir "$HOME/.cloudxr"
        ;;
    teleop|record)
        runtime_dir="$HOME/.cloudxr/run"
        if [[ ! -f "$runtime_dir/cloudxr.env" || ! -S "$runtime_dir/ipc_cloudxr" || \
              ! -f "$runtime_dir/runtime_started" ]]; then
            echo 'CloudXR is not ready. Run ./demo.sh cloudxr in terminal 1 and keep it open.' >&2
            exit 1
        fi
        # The lock is held only by the foreground CloudXR launcher.
        if flock --nonblock /tmp/humanova-cloudxr.lock true; then
            echo 'CloudXR has stopped; restart ./demo.sh cloudxr in terminal 1.' >&2
            exit 1
        fi
        source "$runtime_dir/cloudxr.env"
        options=(--viz kit --device "$PHYSICS_DEVICE")
        if [[ "$1" == record ]]; then
            dataset_file="${2:?Missing dataset file}"
            if [[ -e "$dataset_file" || -L "$dataset_file" ]]; then
                echo "Recording already exists: $dataset_file. Choose a new --dataset-file." >&2
                exit 1
            fi
            mkdir -p -- "$(dirname -- "$dataset_file")"
            exec /isaac-sim/python.sh isaaclab_arena/scripts/imitation_learning/record_demos.py \
                "${options[@]}" --enable_cameras --dataset_file "$dataset_file" \
                --num_demos "${3:?Missing demonstration count}" \
                --num_success_steps "${4:?Missing success step count}" \
                --disable_full_sim_buffer_reset \
                "$TASK_NAME" --object "$TASK_OBJECT" --destination "$TASK_DESTINATION" \
                --teleop_device "$TELEOP_DEVICE"
        fi
        if [[ "$ENABLE_CAMERAS" == 1 ]]; then
            options+=(--enable_cameras)
        fi
        exec /isaac-sim/python.sh isaaclab_arena/scripts/imitation_learning/teleop.py \
            "${options[@]}" "$TASK_NAME" --object "$TASK_OBJECT" \
            --destination "$TASK_DESTINATION" --teleop_device "$TELEOP_DEVICE"
        ;;
    replay)
        dataset_file="${2:?Missing dataset file}"
        if [[ ! -f "$dataset_file" ]]; then
            echo "Recorded dataset not found: $dataset_file" >&2
            exit 1
        fi
        exec /isaac-sim/python.sh isaaclab_arena/scripts/imitation_learning/replay_demos.py \
            --viz kit --device "$PHYSICS_DEVICE" --dataset_file "$dataset_file" \
            "$TASK_NAME" --object "$TASK_OBJECT" --destination "$TASK_DESTINATION"
        ;;
    shell)
        exec bash -i
        ;;
    *)
        echo 'Expected cloudxr, teleop, record, replay, or shell.' >&2
        exit 2
        ;;
esac
