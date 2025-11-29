#!/bin/bash

# =======================================================
# 1. CONFIGURATION PARSER
# =======================================================
CONFIG_FILE="config.yaml"
# Get the directory where this script actually lives
BASE_DIR=$(dirname "$(realpath "$0")")

# We use python to parse the YAML and export variables to Bash.
# We also force paths to be absolute to avoid "File not found" errors
# if the script is run from a different directory (e.g. by Cron/Sonarr).
eval $(python3 -c "
import yaml, os, sys

def get_abs_path(base, path):
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return expanded
    return os.path.join(base, expanded)

try:
    config_path = os.path.join('$BASE_DIR', '$CONFIG_FILE')
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
        exec_conf = config.get('execution', {})
        
        # Settings
        print(f'WAIT_TIME=\"{exec_conf.get(\"wait_time\", 300)}\"')
        print(f'PYTHON_CMD=\"{exec_conf.get(\"python_cmd\", \"python3\")}\"')
        
        # Files (Force Absolute Paths)
        print(f'LOCK_FILE=\"{get_abs_path(\"$BASE_DIR\", exec_conf.get(\"lock_file\", \"/tmp/kometa_sync.lock\"))}\"')
        print(f'TIMER_FILE=\"{get_abs_path(\"$BASE_DIR\", exec_conf.get(\"timer_file\", \"/tmp/kometa_sync.timer\"))}\"')
        print(f'LOG_FILE=\"{get_abs_path(\"$BASE_DIR\", exec_conf.get(\"log_file\", \"/tmp/kometa_sync_wrapper.log\"))}\"')
        
        # Scripts (Force Absolute Paths)
        print(f'ASSET_SCRIPT=\"{get_abs_path(\"$BASE_DIR\", exec_conf.get(\"asset_grabber_path\", \"kometa_asset_grabber.py\"))}\"')
        print(f'OVERLAY_SCRIPT=\"{get_abs_path(\"$BASE_DIR\", exec_conf.get(\"overlay_generator_path\", \"kometa_maintainerr_overlay_yaml.py\"))}\"')
        
        # Kometa (Handle potentially just 'kometa.py' command vs file)
        k_path = exec_conf.get(\"kometa_path\", \"kometa.py\")
        if os.path.exists(os.path.join('$BASE_DIR', k_path)):
             print(f'KOMETA_SCRIPT=\"{os.path.join(\"$BASE_DIR\", k_path)}\"')
        else:
             print(f'KOMETA_SCRIPT=\"{k_path}\"')
             
        print(f'KOMETA_ARGS=\"{exec_conf.get(\"kometa_args\", \"--run\")}\"')

except Exception as e:
    # Fallback print to stderr so it doesn't break eval, but alerts user
    sys.stderr.write(f\"Error parsing config.yaml: {e}\\n\")
    sys.exit(1)
")

# =======================================================
# 2. SYSTEM PREP (Create Dirs & Fix Perms)
# =======================================================
ensure_environment() {
    # 1. Create directories if they don't exist (Fixes your error)
    for file_path in "$LOCK_FILE" "$TIMER_FILE" "$LOG_FILE"; do
        dir_name=$(dirname "$file_path")
        if [ ! -d "$dir_name" ]; then
            mkdir -p "$dir_name"
            # Try to open permissions so other users (Sonarr/Radarr) can write here too
            chmod 777 "$dir_name" 2>/dev/null
        fi
    done

    # 2. Create files if missing and ensure write access
    for file in "$LOCK_FILE" "$TIMER_FILE" "$LOG_FILE"; do
        if [ ! -f "$file" ]; then
            touch "$file"
        fi
        chmod 666 "$file" 2>/dev/null
    done
}

# Run prep immediately
ensure_environment

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
    
    # Switch to Base Dir so scripts find their config.yaml
    cd "$BASE_DIR" || exit 1

    # 1. Asset Grabber
    if [ -f "$ASSET_SCRIPT" ]; then
        echo "[$(date '+%H:%M:%S')] Step 1: Running Asset Grabber..." >> "$LOG_FILE"
        $PYTHON_CMD "$ASSET_SCRIPT" >> "$LOG_FILE" 2>&1
    else
        echo "[$(date '+%H:%M:%S')] Error: Asset script not found at $ASSET_SCRIPT" >> "$LOG_FILE"
    fi

    # 2. Overlay Generator
    if [ -f "$OVERLAY_SCRIPT" ]; then
        echo "[$(date '+%H:%M:%S')] Step 2: Running Overlay Generator..." >> "$LOG_FILE"
        $PYTHON_CMD "$OVERLAY_SCRIPT" >> "$LOG_FILE" 2>&1
    else
         echo "[$(date '+%H:%M:%S')] Error: Overlay script not found at $OVERLAY_SCRIPT" >> "$LOG_FILE"
    fi

    # 3. Kometa
    echo "[$(date '+%H:%M:%S')] Step 3: Running Kometa..." >> "$LOG_FILE"
    $PYTHON_CMD "$KOMETA_SCRIPT" $KOMETA_ARGS >> "$LOG_FILE" 2>&1

    echo "[$(date '+%H:%M:%S')] All tasks completed." >> "$LOG_FILE"
    exit 0
fi

# =======================================================
# MODE 2: THE TRIGGER (Called by Sonarr/Radarr/Cron)
# =======================================================

# 1. Update Timer
TARGET_TIME=$(($(date +%s) + $WAIT_TIME))
echo "$TARGET_TIME" > "$TIMER_FILE"

# 2. Log
echo "[$(date '+%H:%M:%S')] Trigger received from user: $(whoami). Timer set for +$WAIT_TIME seconds." >> "$LOG_FILE"

# 3. Launch Background Worker
export KOMETA_WORKER_MODE="true"
nohup "$0" > /dev/null 2>&1 &
#!/bin/bash

# =======================================================
# 1. CONFIGURATION PARSER
# =======================================================
CONFIG_FILE="config.yaml"
BASE_DIR=$(dirname "$(realpath "$0")")

# Dynamic Python Parser
# We force absolute paths here to avoid confusion.
eval $(python3 -c "
import yaml, os, sys

def get_abs_path(base, path):
    # If path is None/Empty, return empty
    if not path: return ''
    # Expand ~ to home directory
    expanded = os.path.expanduser(path)
    # If it is already absolute, return it. Otherwise join with Base.
    if os.path.isabs(expanded):
        return expanded
    return os.path.join(base, expanded)

try:
    config_path = os.path.join('$BASE_DIR', '$CONFIG_FILE')
    if not os.path.exists(config_path):
        print(f'echo \"[ERROR] Config not found at {config_path}\"; exit 1')
        sys.exit(0)

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
        exec_conf = config.get('execution', {})
        
        # Helper to print safe shell variables
        def set_var(name, val):
            print(f'{name}=\"{val}\"')

        set_var('WAIT_TIME', exec_conf.get('wait_time', 300))
        set_var('PYTHON_CMD', exec_conf.get('python_cmd', 'python3'))
        
        # Files
        set_var('LOCK_FILE', get_abs_path('$BASE_DIR', exec_conf.get('lock_file', '/tmp/kometa_sync.lock')))
        set_var('TIMER_FILE', get_abs_path('$BASE_DIR', exec_conf.get('timer_file', '/tmp/kometa_sync.timer')))
        set_var('LOG_FILE', get_abs_path('$BASE_DIR', exec_conf.get('log_file', '/tmp/kometa_sync_wrapper.log')))
        
        # Scripts
        set_var('ASSET_SCRIPT', get_abs_path('$BASE_DIR', exec_conf.get('asset_grabber_path', 'kometa_asset_grabber.py')))
        set_var('OVERLAY_SCRIPT', get_abs_path('$BASE_DIR', exec_conf.get('overlay_generator_path', 'kometa_maintainerr_overlay_yaml.py')))
        
        # Kometa
        k_path = exec_conf.get('kometa_path', 'kometa.py')
        # If it looks like a file in the base dir, make it absolute
        if os.path.exists(os.path.join('$BASE_DIR', k_path)):
             set_var('KOMETA_SCRIPT', os.path.join('$BASE_DIR', k_path))
        else:
             set_var('KOMETA_SCRIPT', k_path)
             
        set_var('KOMETA_ARGS', exec_conf.get('kometa_args', '--run'))

except Exception as e:
    print(f'echo \"[ERROR] Config Parsing Failed: {e}\"; exit 1')
")

# =======================================================
# 2. HELPER: ENSURE DIRECTORIES
# =======================================================
ensure_file_dir() {
    file_path="$1"
    dir_name=$(dirname "$file_path")
    
    # create directory if missing
    if [ ! -d "$dir_name" ]; then
        mkdir -p "$dir_name"
        chmod 777 "$dir_name" 2>/dev/null
    fi
    
    # ensure file exists
    if [ ! -f "$file_path" ]; then
        touch "$file_path" 2>/dev/null
        chmod 666 "$file_path" 2>/dev/null
    fi
}

# =======================================================
# MODE 1: THE WORKER (Background Process)
# =======================================================
if [ "$KOMETA_WORKER_MODE" == "true" ]; then
    ensure_file_dir "$LOCK_FILE"
    
    # Acquire Lock
    exec 200>"$LOCK_FILE"
    flock -n 200 || exit 0

    ensure_file_dir "$LOG_FILE"
    echo "[$(date '+%H:%M:%S')] Worker started. Monitoring timer..." >> "$LOG_FILE"

    while true; do
        ensure_file_dir "$TIMER_FILE"
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

    echo "[$(date '+%H:%M:%S')] Silence detected. Running workflows..." >> "$LOG_FILE"
    cd "$BASE_DIR" || exit 1

    # 1. Asset Grabber
    if [ -f "$ASSET_SCRIPT" ]; then
        echo "[$(date '+%H:%M:%S')] Step 1: Asset Grabber" >> "$LOG_FILE"
        $PYTHON_CMD "$ASSET_SCRIPT" >> "$LOG_FILE" 2>&1
    else
        echo "[$(date '+%H:%M:%S')] [ERROR] Asset script missing: $ASSET_SCRIPT" >> "$LOG_FILE"
    fi

    # 2. Overlay Generator
    if [ -f "$OVERLAY_SCRIPT" ]; then
        echo "[$(date '+%H:%M:%S')] Step 2: Overlay Generator" >> "$LOG_FILE"
        $PYTHON_CMD "$OVERLAY_SCRIPT" >> "$LOG_FILE" 2>&1
    else
        echo "[$(date '+%H:%M:%S')] [ERROR] Overlay script missing: $OVERLAY_SCRIPT" >> "$LOG_FILE"
    fi

    # 3. Kometa
    echo "[$(date '+%H:%M:%S')] Step 3: Kometa" >> "$LOG_FILE"
    $PYTHON_CMD "$KOMETA_SCRIPT" $KOMETA_ARGS >> "$LOG_FILE" 2>&1

    echo "[$(date '+%H:%M:%S')] All tasks completed." >> "$LOG_FILE"
    exit 0
fi

# =======================================================
# MODE 2: THE TRIGGER
# =======================================================

# Explicitly verify/create directories before writing
ensure_file_dir "$TIMER_FILE"
ensure_file_dir "$LOG_FILE"
ensure_file_dir "$LOCK_FILE"

# Update Timer
TARGET_TIME=$(($(date +%s) + $WAIT_TIME))
echo "$TARGET_TIME" > "$TIMER_FILE"

# Log Trigger
echo "[$(date '+%H:%M:%S')] Trigger received from user: $(whoami). Timer extended." >> "$LOG_FILE"

# Launch Worker
export KOMETA_WORKER_MODE="true"
nohup "$0" > /dev/null 2>&1 &

exit 0
exit 0