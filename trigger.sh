#!/bin/bash

# =======================================================
# 1. CONFIGURATION PARSER
# =======================================================
CONFIG_FILE="config.yaml"
BASE_DIR=$(dirname "$(realpath "$0")")

eval $(python3 -c "
import yaml, os, sys

def get_abs_path(base, path):
    if not path: return ''
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded): return expanded
    return os.path.join(base, expanded)

try:
    config_path = os.path.join('$BASE_DIR', '$CONFIG_FILE')
    if not os.path.exists(config_path):
        print(f'echo \"[ERROR] Config not found at {config_path}\"; exit 1')
        sys.exit(0)

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
        exec_conf = config.get('execution', {})
        
        def set_var(name, val): print(f'{name}=\"{val}\"')

        set_var('WAIT_TIME', exec_conf.get('wait_time', 300))
        
        # Force Python to be unbuffered (-u) so logs show up instantly in --watch
        py_cmd = exec_conf.get('python_cmd', 'python3')
        if ' -u' not in py_cmd: py_cmd += ' -u'
        set_var('PYTHON_CMD', py_cmd)
        
        set_var('LOCK_FILE', get_abs_path('$BASE_DIR', exec_conf.get('lock_file', '/tmp/kometa_sync.lock')))
        set_var('TIMER_FILE', get_abs_path('$BASE_DIR', exec_conf.get('timer_file', '/tmp/kometa_sync.timer')))
        set_var('LOG_FILE', get_abs_path('$BASE_DIR', exec_conf.get('log_file', '/tmp/kometa_sync_wrapper.log')))
        
        set_var('ASSET_SCRIPT', get_abs_path('$BASE_DIR', exec_conf.get('asset_grabber_path', 'kometa_asset_grabber.py')))
        set_var('OVERLAY_SCRIPT', get_abs_path('$BASE_DIR', exec_conf.get('overlay_generator_path', 'kometa_maintainerr_overlay_yaml.py')))
        
        k_path = exec_conf.get('kometa_path', 'kometa.py')
        if os.path.exists(os.path.join('$BASE_DIR', k_path)):
             set_var('KOMETA_SCRIPT', os.path.join('$BASE_DIR', k_path))
        else:
             set_var('KOMETA_SCRIPT', k_path)
        set_var('KOMETA_ARGS', exec_conf.get('kometa_args', '--run'))

except Exception as e:
    sys.stderr.write(f\"Error parsing config.yaml: {e}\\n\")
    sys.exit(1)
")

# =======================================================
# 2. SYSTEM PREP
# =======================================================
ensure_file_dir() {
    file_path="$1"
    dir_name=$(dirname "$file_path")
    if [ ! -d "$dir_name" ]; then mkdir -p "$dir_name"; chmod 777 "$dir_name" 2>/dev/null; fi
    if [ ! -f "$file_path" ]; then touch "$file_path"; fi
    chmod 666 "$file_path" 2>/dev/null
}

ensure_file_dir "$LOCK_FILE"
ensure_file_dir "$TIMER_FILE"
ensure_file_dir "$LOG_FILE"

# =======================================================
# MODE 1: THE WORKER (Background Process)
# =======================================================
if [ "$KOMETA_WORKER_MODE" == "true" ]; then
    exec 2>>"$LOG_FILE"
    exec 200>"$LOCK_FILE"
    flock -n 200 || exit 0

    echo "[$(date '+%H:%M:%S')] Worker started. Monitoring timer..." >> "$LOG_FILE"

    while true; do
        # Strip whitespace to prevent math errors
        CURRENT_TARGET=$(cat "$TIMER_FILE" | tr -d '[:space:]')
        if [ -z "$CURRENT_TARGET" ]; then CURRENT_TARGET=$(date +%s); fi

        CURRENT_TIME=$(date +%s)
        SLEEP_NEEDED=$(($CURRENT_TARGET - $CURRENT_TIME))

        if [ "$SLEEP_NEEDED" -le 0 ]; then
            break
        else
            if [ "$SLEEP_NEEDED" -gt 10 ]; then SLEEP_NEEDED=10; fi
            sleep "$SLEEP_NEEDED"
        fi
    done

    echo "[$(date '+%H:%M:%S')] Silence detected. Running workflows..." >> "$LOG_FILE"
    cd "$BASE_DIR" || { echo "[ERROR] Could not cd to $BASE_DIR" >> "$LOG_FILE"; exit 1; }

    # 1. Asset Grabber
    if [ -f "$ASSET_SCRIPT" ]; then
        echo "[$(date '+%H:%M:%S')] Step 1: Asset Grabber" >> "$LOG_FILE"
        $PYTHON_CMD "$ASSET_SCRIPT" >> "$LOG_FILE" 2>&1
    else
        echo "[$(date '+%H:%M:%S')] [ERROR] Missing Script: $ASSET_SCRIPT" >> "$LOG_FILE"
    fi

    # 2. Overlay Generator
    if [ -f "$OVERLAY_SCRIPT" ]; then
        echo "[$(date '+%H:%M:%S')] Step 2: Overlay Generator" >> "$LOG_FILE"
        $PYTHON_CMD "$OVERLAY_SCRIPT" >> "$LOG_FILE" 2>&1
    else
        echo "[$(date '+%H:%M:%S')] [ERROR] Missing Script: $OVERLAY_SCRIPT" >> "$LOG_FILE"
    fi

    # 3. Kometa
    # Switch to Kometa directory if possible to handle relative config paths
    KOMETA_DIR=$(dirname "$KOMETA_SCRIPT")
    if [ -d "$KOMETA_DIR" ] && [ "$KOMETA_DIR" != "." ]; then
        echo "[$(date '+%H:%M:%S')] Step 3: Running Kometa (Switching to $KOMETA_DIR)..." >> "$LOG_FILE"
        cd "$KOMETA_DIR"
        $PYTHON_CMD "$(basename "$KOMETA_SCRIPT")" $KOMETA_ARGS >> "$LOG_FILE" 2>&1
    else
        echo "[$(date '+%H:%M:%S')] Step 3: Running Kometa..." >> "$LOG_FILE"
        $PYTHON_CMD "$KOMETA_SCRIPT" $KOMETA_ARGS >> "$LOG_FILE" 2>&1
    fi

    echo "[$(date '+%H:%M:%S')] All tasks completed." >> "$LOG_FILE"
    exit 0
fi

# =======================================================
# MODE 2: THE TRIGGER
# =======================================================
TARGET_TIME=$(($(date +%s) + $WAIT_TIME))
echo "$TARGET_TIME" > "$TIMER_FILE"

echo "[$(date '+%H:%M:%S')] Trigger received. Timer set to +$WAIT_TIME sec." >> "$LOG_FILE"
echo "-----------------------------------------------------"
echo " Kometa Sync Triggered!"
echo "-----------------------------------------------------"
echo " The script is now waiting $WAIT_TIME seconds for other imports."
echo " Logs are being written to: $LOG_FILE"

# Launch Background Worker
export KOMETA_WORKER_MODE="true"
nohup "$0" >> "$LOG_FILE" 2>&1 &

# Handle --watch flag
if [[ "$1" == "--watch" ]]; then
    echo " Watching logs now (Ctrl+C to exit view)..."
    echo "-----------------------------------------------------"
    tail -f "$LOG_FILE"
fi

exit 0