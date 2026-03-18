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
        
        # --- EXPORT BASIC VARS ---
        def set_var(name, val): print(f'{name}=\"{val}\"')

        set_var('WAIT_TIME', exec_conf.get('wait_time', 300))
        
        py_cmd = exec_conf.get('python_cmd', 'python3')
        if ' -u' not in py_cmd: py_cmd += ' -u'
        set_var('PYTHON_CMD', py_cmd)
        
        set_var('LOCK_FILE', get_abs_path('$BASE_DIR', exec_conf.get('lock_file', '/tmp/kometa_sync.lock')))
        set_var('TIMER_FILE', get_abs_path('$BASE_DIR', exec_conf.get('timer_file', '/tmp/kometa_sync.timer')))
        set_var('LOG_FILE', get_abs_path('$BASE_DIR', exec_conf.get('log_file', '/tmp/kometa_sync_wrapper.log')))
        
        set_var('ASSET_SCRIPT', get_abs_path('$BASE_DIR', exec_conf.get('asset_grabber_path', 'kometa_asset_grabber.py')))
        set_var('OVERLAY_SCRIPT', get_abs_path('$BASE_DIR', exec_conf.get('overlay_generator_path', 'kometa_maintainerr_overlay_yaml.py')))
        set_var('RETURNING_SCRIPT', get_abs_path('$BASE_DIR', 'returning_series_manager.py'))

        k_path = exec_conf.get('kometa_path', 'kometa.py')
        if os.path.exists(os.path.join('$BASE_DIR', k_path)):
             set_var('KOMETA_SCRIPT', os.path.join('$BASE_DIR', k_path))
        else:
             set_var('KOMETA_SCRIPT', k_path)
        set_var('KOMETA_ARGS', exec_conf.get('kometa_args', '--run'))

        # --- FIX: PARSE SCRIPTS CORRECTLY ---
        # 1. Look in root 'scripts' (where your config has them) OR 'tssk.scripts'
        script_list = config.get('scripts', [])
        if not script_list:
            script_list = config.get('tssk', {}).get('scripts', [])

        paths = []
        names = []
        args = []

        # 2. Handle the list of objects
        for s in script_list:
            # If entry is a dict {name: ..., path: ...}
            if isinstance(s, dict):
                if not s.get('enabled', True): continue
                p = get_abs_path('$BASE_DIR', s.get('path', ''))
                if p:
                    paths.append(p)
                    names.append(s.get('name', os.path.basename(p)))
                    args.append(s.get('args', ''))
            # If entry is just a string path
            elif isinstance(s, str):
                p = get_abs_path('$BASE_DIR', s)
                if p:
                    paths.append(p)
                    names.append(os.path.basename(p))
                    args.append('')

        p_str = ' '.join(['\"' + x + '\"' for x in paths])
        n_str = ' '.join(['\"' + x + '\"' for x in names])
        a_str = ' '.join(['\"' + x + '\"' for x in args])

        print(f'SCRIPT_PATHS=({p_str})')
        print(f'SCRIPT_NAMES=({n_str})')
        print(f'SCRIPT_ARGS=({a_str})')

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
    
    # Switch to script dir
    cd "$BASE_DIR" || { echo "[ERROR] Could not cd to $BASE_DIR" >> "$LOG_FILE"; exit 1; }



    # --------------------------------
    # 1. Asset Grabber
    # --------------------------------
    if [ -f "$ASSET_SCRIPT" ]; then
        echo "[$(date '+%H:%M:%S')] Step 1: Asset Grabber" >> "$LOG_FILE"
        $PYTHON_CMD "$ASSET_SCRIPT" >> "$LOG_FILE" 2>&1
    else
        echo "[$(date '+%H:%M:%S')] [ERROR] Missing Script: $ASSET_SCRIPT" >> "$LOG_FILE"
    fi

    # --------------------------------
    # Step 2: Custom Scripts (Subshell Method)
    # --------------------------------
    SCRIPT_COUNT=${#SCRIPT_PATHS[@]}
    if [ "$SCRIPT_COUNT" -gt 0 ]; then
        echo "Step 2: Found $SCRIPT_COUNT Configured Scripts"
        
        for i in "${!SCRIPT_PATHS[@]}"; do
            NAME="${SCRIPT_NAMES[$i]}"
            SCRIPT="${SCRIPT_PATHS[$i]}"
            ARGS="${SCRIPT_ARGS[$i]}"
            NUM=$((i+1))

            if [ -f "$SCRIPT" ]; then
                S_DIR=$(dirname "$SCRIPT")
                S_FILE=$(basename "$SCRIPT")
                
                echo " > [$NUM/$SCRIPT_COUNT] Running: $NAME"
                echo "   (Path: $SCRIPT)"
                
                # --- SUBSHELL EXECUTION START ---
                # We use ( ... ) to create a subshell. 
                # Changes to 'cd' inside here DO NOT affect the main loop.
                (
                    cd "$S_DIR" || exit 1
                    if [[ "$SCRIPT" == *.py ]]; then
                        $PYTHON_CMD "$S_FILE" $ARGS
                    else
                        "./$S_FILE" $ARGS
                    fi
                )
                # --- SUBSHELL EXECUTION END ---
                
                echo " > [$NUM/$SCRIPT_COUNT] Completed."
            else
                echo " > [$NUM/$SCRIPT_COUNT] [ERROR] File not found: $SCRIPT"
            fi
        done
    else
        echo "Step 2: No scripts to run."
    fi


    # --------------------------------
    # 3. Maintainerr Overlay Generator
    # --------------------------------
    if [ -f "$OVERLAY_SCRIPT" ]; then
        echo "[$(date '+%H:%M:%S')] Step 3: Maintainerr Overlay Generator" >> "$LOG_FILE"
        $PYTHON_CMD "$OVERLAY_SCRIPT" >> "$LOG_FILE" 2>&1
    else
        echo "[$(date '+%H:%M:%S')] [ERROR] Missing Script: $OVERLAY_SCRIPT" >> "$LOG_FILE"
    fi

    # --------------------------------
    # 4. Returning Series Manager
    # --------------------------------
    if [ -f "$RETURNING_SCRIPT" ]; then
        echo "[$(date '+%H:%M:%S')] Step 4: Returning Series Manager" >> "$LOG_FILE"
        $PYTHON_CMD "$RETURNING_SCRIPT" >> "$LOG_FILE" 2>&1
    else
        echo "[$(date '+%H:%M:%S')] [WARN] Returning Series Script not found at $RETURNING_SCRIPT" >> "$LOG_FILE"
    fi


    # --------------------------------
    # 5. Kometa
    # --------------------------------
    KOMETA_DIR=$(dirname "$KOMETA_SCRIPT")
    if [ -d "$KOMETA_DIR" ] && [ "$KOMETA_DIR" != "." ]; then
        echo "[$(date '+%H:%M:%S')] Step 5: Running Kometa (Switching to $KOMETA_DIR)..." >> "$LOG_FILE"
        cd "$KOMETA_DIR"
        $PYTHON_CMD "$(basename "$KOMETA_SCRIPT")" $KOMETA_ARGS >> "$LOG_FILE" 2>&1
    else
        echo "[$(date '+%H:%M:%S')] Step 5: Running Kometa..." >> "$LOG_FILE"
        $PYTHON_CMD "$KOMETA_SCRIPT" $KOMETA_ARGS >> "$LOG_FILE" 2>&1
    fi

    echo "[$(date '+%H:%M:%S')] All tasks completed." >> "$LOG_FILE"
    exit 0
fi


# =======================================================
# MODE 2: THE TRIGGER
# =======================================================

# PARSE ARGUMENTS
FORCE_RUN=false
SHOW_HELP=false

for arg in "$@"; do
    case $arg in
        --now|--skip-wait)
            FORCE_RUN=true
            ;;
        --help|-h)
            SHOW_HELP=true
            ;;
    esac
done

# DISPLAY HELP
if [ "$SHOW_HELP" = true ]; then
    echo "Kometa Sync Trigger Wrapper"
    echo "==========================="
    echo "Usage: ./trigger.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --now, --skip-wait   Skip the debounce timer ($WAIT_TIME sec) and run immediately."
    echo "  --help, -h           Show this help message."
    echo ""
    echo "Note: Logs are displayed automatically by default."
    exit 0
fi

# EXECUTE TRIGGER LOGIC - WITH PERMISSION CHECK
if [ "$FORCE_RUN" = true ]; then
    TARGET_TIME=$(date +%s)
    
    # Attempt update, fail if permission denied
    if ! echo "$TARGET_TIME" > "$TIMER_FILE"; then
        echo "[ERROR] Failed to update timer file at $TIMER_FILE."
        echo "[ERROR] This is usually a permission issue if the script was previously run by root."
        echo "[FIX]   Run: sudo rm $TIMER_FILE"
        exit 1
    fi
    
    echo "[$(date '+%H:%M:%S')] Trigger received with --now. Starting immediately." >> "$LOG_FILE"
    echo "-----------------------------------------------------"
    echo " Kometa Sync Triggered (IMMEDIATE)!"
    echo "-----------------------------------------------------"
else
    TARGET_TIME=$(($(date +%s) + $WAIT_TIME))
    
    # Attempt update, fail if permission denied
    if ! echo "$TARGET_TIME" > "$TIMER_FILE"; then
        echo "[ERROR] Failed to update timer file at $TIMER_FILE."
        echo "[ERROR] This is usually a permission issue if the script was previously run by root."
        echo "[FIX]   Run: sudo rm $TIMER_FILE"
        exit 1
    fi

    echo "[$(date '+%H:%M:%S')] Trigger received from user: $(whoami). Timer set to +$WAIT_TIME sec." >> "$LOG_FILE"
    echo "-----------------------------------------------------"
    echo " Kometa Sync Triggered!"
    echo "-----------------------------------------------------"
    echo " The script is now waiting $WAIT_TIME seconds for other imports."
fi

echo " Logs are being written to: $LOG_FILE"

# Launch Background Worker
export KOMETA_WORKER_MODE="true"
nohup "$0" >> "$LOG_FILE" 2>&1 &
WORKER_PID=$!

# AUTO-WATCH: Always tail the log
echo " Watching logs now (Ctrl+C to stop watching, process will continue in background)..."
echo "-----------------------------------------------------"
# Try to tail using the PID to stop automatically when done (gnu tail feature)
# If that fails, standard tail will just run until Ctrl+C
tail -f "$LOG_FILE" --pid=$WORKER_PID 2>/dev/null || tail -f "$LOG_FILE"

exit 0