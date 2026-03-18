# Maintainerr Poster Overlay for Kometa
Project inspired by [Maintainerr Poster Overlay](https://gitlab.com/jakeC207/maintainerr-poster-overlay "Maintainerr Poster Overlay")

This project automates the process of displaying **expiration overlays** on your Plex media based on **Maintainerr** deletion rules. It bridges the gap between Maintainerr and Kometa, ensuring your users know exactly when content is leaving. It is meant for seedboxes with limited rights but should work on any system that has python.

It also includes a **Returning Series Manager** that integrates with Sonarr to create "dummy" files for upcoming shows, ensuring they appear in Plex (and get overlays) even before the first episode airs.

## ✨ Features

* **Dynamic Overlays:** Automatically generates Kometa config files to display "Expiring in X Days" or "Deletion: X Hours".
* **Returning Series Manager:** Scans Sonarr for continuing/upcoming series with no files on disk (including Maintainerr-unmonitored shows). Creates stub files, labels shows in Plex, and generates three overlay tiers: `NO EPISODES YET`, `RETURNS APR 20` (when a date is known), or `TBA` (no known date).
* **Auto Re-Monitor:** When a returning show's first real episode drops, the script automatically sets the series back to fully monitored in Sonarr so you can rewatch from the beginning.
* **Asset Grabber:** Downloads clean posters from Plex (or upstream metadata providers) before applying overlays to prevent "burned-in" loops.
* **Smart Debounce:** The `trigger.sh` wrapper handles batch imports (e.g., Season Packs) by waiting for "silence" before running, preventing multiple concurrent executions.
* **Global & Specific Styles:** Define a universal look (font, alignment, size) and override specific urgency levels (Critical, Warning, Notice, Returning).
* **Dual-Mode Output:** Generates separate YAML files for Movies and Shows to satisfy Kometa's strict validation.
* **Script Chaining:** Built-in support for running any external scripts (Python or shell) as part of the pipeline.

# 🚀 Installation
Clone the repository:

    git clone https://github.com/theovit/Maintainerr-Poster-Overlay-for-Kometa.git
    cd Maintainerr-Poster-Overlay-for-Kometa

Run the interactive installer (recommended):

    chmod +x install.sh
    ./install.sh

Or manual setup:

    pip3 install requests PyYAML PlexAPI
    cp config.yaml.template config.yaml
    nano config.yaml
    chmod +x trigger.sh

# ⚙️ Configuration
The `config.yaml` is the single source of truth. Below is a breakdown of the key sections.

### 1. Connection
Define your connection details for Maintainerr, Plex, and your *arrs.

```connect:
  maintainerr:
    maintainerr_host: "192.168.1.100"
    maintainerr_port: 6246
    maintainerr_user: "admin"
    maintainerr_pass: "your#secure#password"
	
  plex:
    url: "http://192.168.1.100:32400"
    token: "YOUR_PLEX_TOKEN"

  sonarr_instances:
    - name: "Sonarr - Anime"
      url: "http://192.168.1.50:8989"
      api_key: "API_KEY_HERE"
      path_mapping:
        sonarr_base_path: "/data/anime"         # path as Sonarr sees it
        local_base_path: "/mnt/user/media/anime" # path as this script sees it

    - name: "Sonarr - TV"
      url: "http://192.168.1.50:8990"
      api_key: "API_KEY_HERE"
      path_mapping:
        sonarr_base_path: "/data/tv"
        local_base_path: "/mnt/user/media/tv"

  radarr_instances:
    - name: "Radarr - 4K"
      url: "http://192.168.1.50:7878"
      api_key: "API_KEY_HERE"
      library_path: "/mnt/user/media/movies_4k"

    - name: "Radarr - 1080p"
      url: "http://192.168.1.50:7879"
      api_key: "API_KEY_HERE"
      library_path: "/mnt/user/media/movies"```

### 2. Output Paths
Where the generated Kometa YAML files will be saved.

    output:
      movies_path: "/path/to/kometa/config/overlays/maintainerr_overlays_movies.yaml"
      shows_path: "/path/to/kometa/config/overlays/maintainerr_overlays_shows.yaml"
      returning_path: "/path/to/kometa/config/overlays/returning_overlays.yaml"
      returning_dates_path: "/path/to/kometa/config/overlays/returning_dates_overlays.yaml"

### 3. Triggers
Define the thresholds (in days) for each urgency level.

    triggers:
      critical_days: 3   # Less than 3 days = Critical (Red)
      warning_days: 7    # Less than 7 days = Warning (Orange)
      notice_days: 14    # Less than 14 days = Notice (Grey)
      
      # If true, items get the "Monitor" style as soon as they enter the Maintainerr collection
      use_maintainerr_limit: true

### 2. Styles (Global vs. Specific)
This project uses a Defaults/Override model. Set your baseline look in global_defaults, and only specific changes in styles.

Global Defaults: Applied to everything (e.g., Bottom Right position, Font Size 60).

Styles (Critical/Warning/Notice): Override specific values (e.g., Change background color to Red for Critical).

### 5. Asset Grabber
Ensures you always apply overlays to clean artwork.

    assets:
      enabled: true
      path: "/path/to/kometa/config/assets"
      grab_originals: true # Tries to find non-local URL to avoid existing overlays
      libraries:
        - "Movies"
        - "TV Shows"

### 6. External Scripts
Run other Python scripts (e.g. TSSK) as part of this pipeline.

    scripts:
      - name: "TSSK TV Shows"
        path: "/path/to/TSSK/TSSK.py"
        enabled: true
      - name: "TSSK Anime"
        path: "/path/to/TSSK_Anime/TSSK.py"
        enabled: true

### 7. Execution & Paths
Configure the wrapper behavior and file locations.

    execution:
      wait_time: 300  # Debounce wait time (seconds)
      python_cmd: "python3"
      
      # wrapper logs/locks
      lock_file: "/tmp/kometa_sync.lock"
      log_file: "/tmp/kometa_sync_wrapper.log"
      
      # script filenames (if renamed)
      asset_grabber_path: "asset-grabber.py"
      overlay_generator_path: "kometa_maintainerr_overlay_yaml.py"
      
      # Kometa Location
      kometa_path: "/path/to/kometa.py"
      kometa_args: "--run-overlays"  # overlay-only pass; full --run stays on background Kometa's schedule

### 8. Returning Series Manager
Configures the dummy file creation for upcoming shows.

    returning:
      generate_overlay: true
      template_file: "/path/to/assets/blank.mp4" 
      stub_suffix: " - kometa-overlay-lock.mp4"
      
      overlay_style:
        text: "NO EPISODES YET"
        back_color: "#0077CCFF" # Blue

      # Overlay for shows with a known return date (e.g. "RETURNS APR 20")
      returning_dates:
        enabled: true
        path: "/path/to/kometa/config/overlays/returning_dates_overlays.yaml"
        text_format: "RETURNS {date}"
        group: "TSSK_text"   # must match TSSK's overlay group so this overrides it
        weight: 15           # higher than TSSK returning (10), lower than new season soon (25)

      # Overlay for shows with no known return date (e.g. "TBA")
      tba_overlay:
        enabled: true
        path: "/path/to/kometa/config/overlays/returning_tba_overlays.yaml"
        text: "TBA"
        group: "TSSK_text"
        weight: 12

# 🤖 Automation (Sonarr / Radarr)
To trigger this script automatically when new media is added:

1.  Go to: **Settings > Connect > + > Custom Script**.
2.  Name: **Kometa Sync**.
3.  Triggers: Check **On File Import** and **On File Upgrade**.
4.  Path: Select the `trigger.sh` file.
5.  Save.

#### Cron job
Since Maintainerr runs on a schedule, you should also run this script periodically.

    crontab -e
    # Run at Midnight, 8am, and 4pm
    0 0,8,16 * * * /path/to/Maintainerr-Poster-Overlay-for-Kometa/trigger.sh >> /path/to/cron_output.log 2>&1

# 🔗 Integrating with Kometa
Add the generated overlay files to your main Kometa `config.yml`.

    libraries:
      Movies:
        overlay_files:
          - file: config/overlays/maintainerr_overlays_movies.yaml

      TV Shows:
        overlay_files:
          - file: config/overlays/maintainerr_overlays_shows.yaml
          - file: config/overlays/returning_overlays.yaml
          - file: config/overlays/returning_dates_overlays.yaml
          - file: config/overlays/returning_tba_overlays.yaml

# 🛠️ Manual Usage
### Run the full pipeline (Wait 5 mins + Sync):
`./trigger.sh`

### Run immediately (Skip debounce timer):
`./trigger.sh --now`

### Run individual modules:
* **Overlay Generator:** `python3 kometa_maintainerr_overlay_yaml.py`
* **Returning Series:** `python3 returning_series_manager.py`
* **Asset Grabber:** `python3 asset-grabber.py`
