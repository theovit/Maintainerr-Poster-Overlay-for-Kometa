# Maintainerr Poster Overlay for Kometa

This project automates the process of displaying **expiration overlays** on your Plex media based on **Maintainerr** deletion rules. It bridges the gap between Maintainerr and Kometa, ensuring your users know exactly when content is leaving.

It includes a robust **Asset Grabber** to ensure overlays are applied to clean posters (preventing "burned-in" loops) and a **Debounce Wrapper** to handle high-volume triggers from Sonarr/Radarr without overloading your system.

## ✨ Features

* **Dynamic Overlays:** Automatically generates Kometa config files to display "Expiring in X Days" or "Deletion: X Hours".
* **Asset Grabber:** Downloads clean posters from Plex (or upstream metadata providers) before applying overlays.
* **Smart Debounce:** The `trigger.sh` wrapper handles batch imports (e.g., Season Packs) by waiting for "silence" before running, preventing multiple concurrent executions.
* **Global & Specific Styles:** Define a universal look (font, alignment, size) and override specific urgency levels (Critical, Warning, Notice).
* **Dual-Mode Output:** Generates separate YAML files for Movies and Shows to satisfy Kometa's strict validation.
* **Script Chaining:** Built-in support for running external scripts (TSSK) within the pipeline.

# 🚀 Installation
Clone the repository:

    git clone https://github.com/theovit/Maintainerr-Poster-Overlay-for-Kometa.git
    cd Maintainerr-Poster-Overlay-for-Kometa
Install Dependencies:

    pip3 install -r requirements.txt
Configure: Copy the template and edit your settings.


    cp config.yaml.template config.yaml
    nano config.yaml
# ⚙️ Configuration
The config.yaml is the single source of truth for the Python scripts and the Bash wrapper.

### 1. Connection & Output
Define your connection details and where the Kometa files should be generated.


    connect:
      maintainerr_host: "192.168.1.100"
      maintainerr_port: 6246
      maintainerr_user: "admin"
      maintainerr_pass: "your#secure#password"
      plex_url: "http://192.168.1.100:32400"
      plex_token: "YOUR_PLEX_TOKEN"
    
    output:
      movies_path: "/path/to/kometa/config/overlays/maintainerr_overlays_movies.yaml"
      shows_path: "/path/to/kometa/config/overlays/maintainerr_overlays_shows.yaml"
### 2. Styles (Global vs. Specific)
This project uses a Defaults/Override model. Set your baseline look in global_defaults, and only specific changes in styles.

Global Defaults: Applied to everything (e.g., Bottom Right position, Font Size 60).

Styles (Critical/Warning/Notice): Override specific values (e.g., Change background color to Red for Critical).

### 3. Asset Grabber
Ensures you always apply overlays to clean artwork.

    assets:
      enabled: true
      path: "/path/to/kometa/config/assets" # Where to save clean posters
      grab_originals: true # Tries to find non-local URL to avoid existing overlays
### 4. Execution Settings
Controls the trigger.sh behavior.

    execution:
      wait_time: 300  # Seconds to wait for silence (Debounce)
      python_cmd: "python3"
# 🤖 Automation (Sonarr / Radarr)
To trigger this script automatically when new media is added (so it gets the "Monitor" overlay immediately), set up a Custom Script in your *arrs.

    Go to: Settings > Connect > + > Custom Script.
    Name: Kometa Sync.
    Triggers: Check On Import and On Upgrade.
    Path: Select the trigger.sh file.
    Save.


#### Cron job
    crontab -e
    0 0,8,16 * * * /path/to/Maintainerr-Poster-Overlay-for-Kometa/trigger.sh

### How the Wrapper Works
    Trigger: Sonarr calls trigger.sh.
    Update: The script updates a timestamp file to Now + 5 Minutes.
    Background: It launches a worker in the background and exits immediately (so Sonarr doesn't hang).
    Wait: The background worker waits until 5 minutes have passed with no new imports.
    Execute: Once silence is detected, it runs:
    asset_grabber.py
    TSSK Scripts (if configured)
    kometa_maintainerr_overlay_yaml.py
    Kometa
# 🔗 Integrating with Kometa
Add the generated overlay files to your main Kometa config.yml. Note that Movies and Shows must use their respective files.


    libraries:
      Movies:
        overlay_files:
          - file: config/overlays/maintainerr_overlays_movies.yaml

      TV Shows:
        overlay_files:
          - file: config/overlays/maintainerr_overlays_shows.yaml
# 🛠️ Manual Usage
### Run the full pipeline (Wait 5 mins + Sync):
`./trigger.sh`
### Run the full pipeline and WATCH logs live:
`./trigger.sh --watch`
### Run just the Overlay Generator (Immediate execution):
`python3 kometa_maintainerr_overlay_yaml.py`
### Run just the Asset Grabber (Immediate execution):
`python3 asset_grabber.py`