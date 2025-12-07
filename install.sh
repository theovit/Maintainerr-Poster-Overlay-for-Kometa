#!/bin/bash

# ============================================================
# Maintainerr Poster Overlay - Interactive Installer
# ============================================================

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Cross-platform sed
sed_i() {
    if [[ "$OSTYPE" == "darwin"* ]]; then sed -i '' "$@"; else sed -i "$@"; fi
}

# Package Installer
install_sys_pkg() {
    PKG=$1
    if command -v apt-get &> /dev/null; then sudo apt-get update && sudo apt-get install -y $PKG
    elif command -v dnf &> /dev/null; then sudo dnf install -y $PKG
    elif command -v yum &> /dev/null; then sudo yum install -y $PKG
    elif command -v apk &> /dev/null; then sudo apk add $PKG
    elif command -v pacman &> /dev/null; then sudo pacman -S --noconfirm $PKG
    else echo -e "${RED}Manual install required for: $PKG${NC}"; exit 1; fi
}

echo -e "${BLUE}=== Phase 1: System Check ===${NC}"

# 1. Python Check
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}Installing Python 3...${NC}"; install_sys_pkg "python3"
else
    echo -e "${GREEN}Python 3 found.$(python3 --version)${NC}"
fi

# 2. Venv Module Check
if ! python3 -m venv test_env_chk &> /dev/null; then
    echo -e "${YELLOW}Installing Python Venv...${NC}"
    if command -v apt-get &> /dev/null; then install_sys_pkg "python3-venv python3-pip"
    else install_sys_pkg "python3-pip"; fi
else
    rm -rf test_env_chk
    echo -e "${GREEN}Venv module ready.${NC}"
fi

echo -e "${BLUE}=== Phase 2: Setup ===${NC}"

# 3. Create Venv
if [ ! -d "venv" ]; then
    echo -e "${BLUE}Creating virtual environment...${NC}"
    python3 -m venv venv || { echo -e "${RED}Venv creation failed.${NC}"; exit 1; }
fi

# 4. Install Requirements
echo -e "${BLUE}Installing dependencies...${NC}"
./venv/bin/pip install --upgrade pip > /dev/null
./venv/bin/pip install -r requirements.txt > /dev/null || { echo -e "${RED}Pip install failed.${NC}"; exit 1; }
echo -e "${GREEN}Dependencies installed.${NC}"

# 5. Config Setup
if [ ! -f "config.yaml" ]; then cp config.yaml.template config.yaml; fi

echo -e "${BLUE}=== Phase 3: Configuration Wizard ===${NC}"
echo -e "${CYAN}Press Enter to accept defaults [shown in brackets].${NC}"

# --- JSON BUILDER START ---
JSON_PAYLOAD="{"

# ----------------------------------------
# SECTION A: CONNECT
# ----------------------------------------
echo -e "\n${BLUE}--- [1/4] Connections ---${NC}"

# Maintainerr
echo -e "${YELLOW}> Maintainerr${NC}"
read -r -p "  Host IP/URL [192.168.1.100]: " M_HOST; M_HOST=${M_HOST:-192.168.1.100}
read -r -p "  Port [6246]: " M_PORT; M_PORT=${M_PORT:-6246}
read -r -p "  User [admin]: " M_USER; M_USER=${M_USER:-admin}
read -r -p "  Password: " M_PASS

JSON_PAYLOAD+="\"maintainerr\": {\"host\": \"$M_HOST\", \"port\": $M_PORT, \"user\": \"$M_USER\", \"pass\": \"$M_PASS\"},"

# Plex
echo -e "${YELLOW}> Plex${NC}"
read -r -p "  Plex URL [http://192.168.1.100:32400]: " P_URL; P_URL=${P_URL:-http://192.168.1.100:32400}
read -r -p "  Plex Token: " P_TOKEN

JSON_PAYLOAD+="\"plex\": {\"url\": \"$P_URL\", \"token\": \"$P_TOKEN\"},"

# Sonarr Loop
echo -e "${YELLOW}> Sonarr Instances${NC}"
echo -e "  (We will ask for each instance one by one. Say 'n' when finished.)"
SONARR_LIST="["
while true; do
    read -r -p "  Add a Sonarr Instance? (y/n) [n]: " ADD_SONARR
    if [[ ! "$ADD_SONARR" =~ ^[Yy]$ ]]; then break; fi
    read -r -p "    Name (e.g. 'Anime'): " S_NAME
    read -r -p "    URL (e.g. http://192.168.1.50:8989): " S_URL
    read -r -p "    API Key: " S_KEY
    read -r -p "    Library Path (e.g. /mnt/media/anime): " S_PATH
    SONARR_LIST+="{\"name\": \"$S_NAME\", \"url\": \"$S_URL\", \"api_key\": \"$S_KEY\", \"library_path\": \"$S_PATH\"},"
done
SONARR_LIST="${SONARR_LIST%,}]"
JSON_PAYLOAD+="\"sonarr\": $SONARR_LIST,"

# Radarr Loop
echo -e "${YELLOW}> Radarr Instances${NC}"
RADARR_LIST="["
while true; do
    read -r -p "  Add a Radarr Instance? (y/n) [n]: " ADD_RADARR
    if [[ ! "$ADD_RADARR" =~ ^[Yy]$ ]]; then break; fi
    read -r -p "    Name (e.g. '4K Movies'): " R_NAME
    read -r -p "    URL (e.g. http://192.168.1.50:7878): " R_URL
    read -r -p "    API Key: " R_KEY
    read -r -p "    Library Path (e.g. /mnt/media/movies): " R_PATH
    RADARR_LIST+="{\"name\": \"$R_NAME\", \"url\": \"$R_URL\", \"api_key\": \"$R_KEY\", \"library_path\": \"$R_PATH\"},"
done
RADARR_LIST="${RADARR_LIST%,}]"
JSON_PAYLOAD+="\"radarr\": $RADARR_LIST,"


# ----------------------------------------
# SECTION B: FEATURES (TOGGLES)
# ----------------------------------------
echo -e "\n${BLUE}--- [2/4] Features Enabled ---${NC}"

# Asset Grabber
echo -e "${YELLOW}> Asset Grabber${NC}"
echo -e "  Downloads clean posters from Plex/TMDB before applying overlays."
read -r -p "  Enable Asset Grabber? (y/n) [y]: " IN_ASSETS
if [[ "$IN_ASSETS" =~ ^[Nn]$ ]]; then ASSET_BOOL="false"; else ASSET_BOOL="true"; fi

# Returning Series
echo -e "\n${YELLOW}> Returning Series Manager${NC}"
echo -e "  Creates dummy files for upcoming shows so they appear in Plex."
read -r -p "  Enable Returning Series Manager? (y/n) [y]: " IN_RET
if [[ "$IN_RET" =~ ^[Nn]$ ]]; then RET_BOOL="false"; else RET_BOOL="true"; fi

# TSSK
echo -e "\n${YELLOW}> TSSK (Task Scripts)${NC}"
echo -e "  Run external Python scripts as part of this pipeline."
read -r -p "  Enable TSSK? (y/n) [n]: " IN_TSSK
if [[ "$IN_TSSK" =~ ^[Yy]$ ]]; then TSSK_BOOL="true"; else TSSK_BOOL="false"; fi

# Limit
echo -e "\n${YELLOW}> Maintainerr Trigger${NC}"
echo -e "  [y] Immediate: Show overlay as soon as item is in collection."
echo -e "  [n] Late: Only show overlay when Warning threshold is hit."
read -r -p "  Use Collection Limit as Trigger? (y/n) [y]: " IN_LIMIT
if [[ "$IN_LIMIT" =~ ^[Nn]$ ]]; then LIMIT_BOOL="false"; else LIMIT_BOOL="true"; fi


# ----------------------------------------
# SECTION C: PATHS (DYNAMIC)
# ----------------------------------------
echo -e "\n${BLUE}--- [3/4] File Paths ---${NC}"
echo -e "We will use your Kometa Root to guess the other paths."

# 1. Get Root
read -r -p "Kometa Config Root (e.g. /config): " K_ROOT
K_ROOT=${K_ROOT:-/config}
# Strip trailing slash just in case
K_ROOT=${K_ROOT%/}

# 2. Standard Overlays (Always needed)
DEF_MOV="$K_ROOT/overlays/maintainerr_movies.yaml"
DEF_TV="$K_ROOT/overlays/maintainerr_shows.yaml"

echo -e "${CYAN}Standard Overlays:${NC}"
read -r -p "  Movies Path [$DEF_MOV]: " OUT_MOV; OUT_MOV=${OUT_MOV:-$DEF_MOV}
read -r -p "  Shows Path  [$DEF_TV]: " OUT_TV; OUT_TV=${OUT_TV:-$DEF_TV}

# 3. Assets (Conditional)
OUT_AST=""
if [ "$ASSET_BOOL" == "true" ]; then
    DEF_AST="$K_ROOT/assets"
    echo -e "${CYAN}Assets:${NC}"
    read -r -p "  Download Path [$DEF_AST]: " OUT_AST; OUT_AST=${OUT_AST:-$DEF_AST}
fi

# 4. Returning Series (Conditional)
OUT_RET=""
RET_TEMP=""
if [ "$RET_BOOL" == "true" ]; then
    DEF_RET="$K_ROOT/overlays/returning_series.yaml"
    DEF_TEMP="$K_ROOT/assets/blank.mp4"
    
    echo -e "${CYAN}Returning Series:${NC}"
    read -r -p "  Overlay Path    [$DEF_RET]: " OUT_RET; OUT_RET=${OUT_RET:-$DEF_RET}
    read -r -p "  Blank Template  [$DEF_TEMP]: " RET_TEMP; RET_TEMP=${RET_TEMP:-$DEF_TEMP}
fi

# 5. TSSK Scripts (Conditional Loop)
TSSK_LIST="[]"
if [ "$TSSK_BOOL" == "true" ]; then
    echo -e "${CYAN}TSSK Scripts:${NC}"
    echo -e "  Add full paths to python scripts you want to run."
    TSSK_LIST="["
    while true; do
        read -r -p "  Add a Script Path? (y/n) [y]: " ADD_SCRIPT
        if [[ "$ADD_SCRIPT" =~ ^[Nn]$ ]]; then break; fi
        
        read -r -p "    Path: " SCRIPT_PATH
        TSSK_LIST+="\"$SCRIPT_PATH\","
    done
    TSSK_LIST="${TSSK_LIST%,}]"
fi

JSON_PAYLOAD+="\"paths\": {\"movies\": \"$OUT_MOV\", \"shows\": \"$OUT_TV\", \"returning\": \"$OUT_RET\", \"assets\": \"$OUT_AST\", \"ret_template\": \"$RET_TEMP\"},"
JSON_PAYLOAD+="\"tssk_scripts\": $TSSK_LIST,"


# ----------------------------------------
# SECTION D: TIMING
# ----------------------------------------
echo -e "\n${BLUE}--- [4/4] Timing ---${NC}"
read -r -p "Wait Time (seconds) before running [$300]: " EXEC_WAIT; EXEC_WAIT=${EXEC_WAIT:-300}
read -r -p "Critical Days (Red) [3]: " TRIG_CRIT; TRIG_CRIT=${TRIG_CRIT:-3}
read -r -p "Warning Days (Orange) [7]: " TRIG_WARN; TRIG_WARN=${TRIG_WARN:-7}

JSON_PAYLOAD+="\"behavior\": {\"wait\": $EXEC_WAIT, \"crit\": $TRIG_CRIT, \"warn\": $TRIG_WARN, \"assets_enabled\": $ASSET_BOOL, \"returning_enabled\": $RET_BOOL, \"tssk_enabled\": $TSSK_BOOL, \"use_limit\": $LIMIT_BOOL}}"

# --- PYTHON WRITER ---
echo -e "\n${BLUE}Saving configuration...${NC}"

./venv/bin/python3 - <<END_PYTHON
import yaml, json, os

try:
    data = json.loads('$JSON_PAYLOAD')
except Exception as e:
    print(f"JSON Error: {e}"); exit(1)

config_path = 'config.yaml'
with open(config_path, 'r') as f:
    config = yaml.safe_load(f)

# 1. Update Connect
c = config.get('connect', {})
c['maintainerr'].update({
    'maintainerr_host': data['maintainerr']['host'],
    'maintainerr_port': data['maintainerr']['port'],
    'maintainerr_user': data['maintainerr']['user']
})
if data['maintainerr']['pass']: c['maintainerr']['maintainerr_pass'] = data['maintainerr']['pass']
c['plex']['plex_url'] = data['plex']['url']
if data['plex']['token']: c['plex']['plex_token'] = data['plex']['token']
if data['sonarr']: c['sonarr_instances'] = data['sonarr']
if data['radarr']: c['radarr_instances'] = data['radarr']
config['connect'] = c

# 2. Update Paths
config['output'] = config.get('output', {})
config['output']['movies_path'] = data['paths']['movies']
config['output']['shows_path'] = data['paths']['shows']
if data['paths']['returning']:
    config['output']['returning_path'] = data['paths']['returning']

# 3. Assets
config['assets'] = config.get('assets', {})
config['assets']['enabled'] = data['behavior']['assets_enabled']
if data['paths']['assets']:
    config['assets']['path'] = data['paths']['assets']

# 4. Returning Series
config['returning'] = config.get('returning', {})
config['returning']['generate_overlay'] = data['behavior']['returning_enabled']
if data['paths']['ret_template']:
    config['returning']['template_file'] = data['paths']['ret_template']

# 5. TSSK
config['tssk'] = config.get('tssk', {})
config['tssk']['enabled'] = data['behavior']['tssk_enabled']
if data['tssk_scripts']:
    config['tssk']['scripts'] = data['tssk_scripts']
elif 'scripts' not in config['tssk']:
    config['tssk']['scripts'] = []

# 6. Behavior
config['execution'] = config.get('execution', {})
config['execution']['wait_time'] = data['behavior']['wait']
config['triggers'] = config.get('triggers', {})
config['triggers']['critical_days'] = data['behavior']['crit']
config['triggers']['warning_days'] = data['behavior']['warn']
config['triggers']['use_maintainerr_limit'] = data['behavior']['use_limit']

with open(config_path, 'w') as f:
    yaml.dump(config, f, sort_keys=False)
END_PYTHON

# 6. Final Path Linking
VENV_PYTHON=$(readlink -f ./venv/bin/python3)
echo -e "${BLUE}Linking environment...${NC}"
sed_i "s|python_cmd: \"python3\"|python_cmd: \"$VENV_PYTHON\"|g" config.yaml
sed_i "s|python_cmd: \"python3\"|python_cmd: \"$VENV_PYTHON\"|g" config.yaml
sed_i "s|eval \$(python3 -c|eval \$($VENV_PYTHON -c|g" trigger.sh

# 7. Permissions
chmod +x trigger.sh
chmod +x install.sh

echo -e "------------------------------------------------------------"
echo -e "${GREEN}Installation & Configuration Complete!${NC}"
echo -e "------------------------------------------------------------"
echo -e "Run manually: ${YELLOW}./trigger.sh${NC}"
echo -e "Cron (8h):    ${YELLOW}0 */8 * * * $(pwd)/trigger.sh >> $(pwd)/cron.log 2>&1${NC}"
echo -e "------------------------------------------------------------"