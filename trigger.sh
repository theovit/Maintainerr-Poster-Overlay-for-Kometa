#!/bin/bash

# =======================================================
# 1. CONFIGURATION PARSER
# =======================================================
CONFIG_FILE="config.yaml"
BASE_DIR=$(dirname "$(realpath "$0")")

# We use python to parse the YAML and export the variables to Bash.
# This ensures we don't need extra tools like 'yq'.
eval $(python3 -c "
import yaml, os, sys
try:
    with open('$BASE_DIR/$CONFIG_FILE', 'r') as f:
        config = yaml.safe_load(f)
        exec_conf = config.get('execution', {})
        
        # Define defaults if missing in yaml
        print(f'WAIT_TIME=\"{exec_conf.get(\"wait_time\", 300)}\"')
        print(f'PYTHON_CMD=\"{exec_conf.get(\"python_cmd\", \"python3\")}\"')
        print(f'LOCK_FILE=\"{exec_conf.get(\"lock_file\", \"/tmp/kometa_sync.lock\")}\"')
        print(f'TIMER_FILE=\"{exec_conf.get(\"timer_file\", \"/tmp/kometa_sync.timer\")}\"')
        print(f'LOG_FILE=\"{exec_conf.get(\"log_file\", \"/tmp/kometa_sync_wrapper.log\")}\"')
        
        # Paths
        print(f'ASSET_SCRIPT=\"{exec_conf.get(\"asset_grabber_path\", \"kometa_asset_grabber.py\")}\"')
        print(f'OVERLAY_SCRIPT=\"{exec_conf.get(\"overlay_generator_path\", \"kometa_maintainerr_overlay_yaml.py\")}\"')
        print(f'KOMETA_SCRIPT=\"{exec_conf.get(\"kometa_path\", \"kometa.py\")}\"')
        print(f'KOMETA_ARGS=\"{exec_conf.get(\"kometa_args\", \"--run\")}\"')

except Exception as e:
    print(f'echo \"Error parsing config.yaml: {e}\"; exit 1')
")

# =======================================================
# 2. PERMISSION HELPER
# =======================================================
ensure_permissions() {
    for file in "$LOCK_FILE" "$TIMER_FILE" "$LOG_FILE"; do
        if [ -f "$file" ]; then
            chmod 666 "$file" 2>/dev/null
        fi
    done
}

# =======================================================
# MODE 1: THE WORKER (Background Process)
# Executed only when KOMETA_WORKER_MODE is set to "true"
# =======================================================
if [ "$KOMETA_WORKER_MODE" == "true" ]; then
    # Try to acquire the exclusive lock.
    exec 200>"$LOCK_FILE"
    flock -n 200 || exit 0

    echo "[$(date '+%H:%M:%S')] Worker started. Monitoring timer..." >> "$LOG_FILE"

    while true; do
        CURRENT_TARGET=$(cat "$TIMER_FILE")
        if [ -z "$CURRENT_TARGET" ]; then CURRENT_TARGET=$(date +%s); fi

        CURRENT_TIME=$(date +%s)
        SLEEP_NEEDED=$(($CURRENT_TARGET - $CURRENT_TIME))

        if [ "$SLEEP_NEEDED" -le 0 ]; then
            break
        else
            sleep "$SLEEP_NEEDED"
        fi
    done

    # --- RUN SCRIPTS ---
    echo "[$(date '+%H:%M:%S')] Silence detected ($WAIT_TIME sec passed). Running workflows..." >> "$LOG_FILE"
    
    # Ensure we are in the script directory
    cd "$BASE_DIR" || exit 1

    # 1. Asset Grabber
    if [ -f "$ASSET_SCRIPT" ]; then
        echo "[$(date '+%H:%M:%S')] Step 1: Running Asset Grabber ($ASSET_SCRIPT)..." >> "$LOG_FILE"
        $PYTHON_CMD "$ASSET_SCRIPT" >> "$LOG_FILE" 2>&1
    else
        echo "[$(date '+%H:%M:%S')] Error: Asset script not found at $ASSET_SCRIPT" >> "$LOG_FILE"
    fi

    # 2. Overlay Generator
    if [ -f "$OVERLAY_SCRIPT" ]; then
        echo "[$(date '+%H:%M:%S')] Step 2: Running Overlay Generator ($OVERLAY_SCRIPT)..." >> "$LOG_FILE"
        $PYTHON_CMD "$OVERLAY_SCRIPT" >> "$LOG_FILE" 2>&1
    else
         echo "[$(date '+%H:%M:%S')] Error: Overlay script not found at $OVERLAY_SCRIPT" >> "$LOG_FILE"
    fi

    # 3. Kometa
    # We check if the path exists OR if it's a command in the path (like just 'kometa')
    if [ -f "$KOMETA_SCRIPT" ] || command -v "$KOMETA_SCRIPT" >/dev/null 2>&1; then
        echo "[$(date '+%H:%M:%S')] Step 3: Running Kometa ($KOMETA_SCRIPT $KOMETA_ARGS)..." >> "$LOG_FILE"
        $PYTHON_CMD "$KOMETA_SCRIPT" $KOMETA_ARGS >> "$LOG_FILE" 2>&1
    else
        echo "[$(date '+%H:%M:%S')] Error: Kometa script not found at $KOMETA_SCRIPT" >> "$LOG_FILE"
    fi

    echo "[$(date '+%H:%M:%S')] All tasks completed." >> "$LOG_FILE"
    ensure_permissions
    exit 0
fi

# =======================================================
# MODE 2: THE TRIGGER (Called by Sonarr/Radarr/Cron)
# =======================================================

# 1. Update Timer
TARGET_TIME=$(($(date +%s) + $WAIT_TIME))
echo "$TARGET_TIME" > "$TIMER_FILE"

# 2. Ensure Files & Perms
if [ ! -f "$LOG_FILE" ]; then touch "$LOG_FILE"; fi
if [ ! -f "$LOCK_FILE" ]; then touch "$LOCK_FILE"; fi
ensure_permissions

# 3. Log
echo "[$(date '+%H:%M:%S')] Trigger received from user: $(whoami). Timer set for +$WAIT_TIME seconds." >> "$LOG_FILE"

# 4. Launch Background Worker
export KOMETA_WORKER_MODE="true"
nohup "$0" > /dev/null 2>&1 &

exit 0