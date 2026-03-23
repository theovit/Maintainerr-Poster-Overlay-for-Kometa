# Maintainerr Poster Overlay for Kometa
Project inspired by [Maintainerr Poster Overlay](https://gitlab.com/jakeC207/maintainerr-poster-overlay "Maintainerr Poster Overlay")

This project automates the process of displaying **expiration overlays** on your Plex media based on **Maintainerr** deletion rules. It bridges the gap between Maintainerr and Kometa, ensuring your users know exactly when content is leaving. It is meant for seedboxes with limited rights but should work on any system that has Python.

It also includes a **Returning Series Manager** that integrates with Sonarr to create stub files for upcoming shows, ensuring they appear in Plex (and get overlays) even before the first episode airs.

## ✨ Features

* **Dynamic Overlays:** Automatically generates Kometa overlay YAML files displaying "Expiring in X Days" or "Deletion: X Hours" at configurable urgency tiers.
* **Returning Series Manager:** Scans Sonarr for continuing/upcoming series with no files on disk (including Maintainerr-unmonitored shows). Creates stub files, labels shows in Plex, and generates stacked overlay strips: `NO EPISODES YET` above a primary label of either `RETURNS APR 20` (known date) or `T B A` (no known date).
* **Auto Re-Monitor:** When a returning show's first real episode drops, the script automatically sets the series back to fully monitored in Sonarr so you can rewatch from the beginning.
* **Asset Grabber:** Downloads clean posters from Plex (or upstream metadata providers) before applying overlays to prevent "burned-in" loops.
* **Smart Debounce:** The `trigger.sh` wrapper handles batch imports (e.g., season packs) by waiting for silence before running, preventing duplicate executions.
* **Global & Specific Styles:** Define a universal look (font, alignment, size) and override per urgency level (Critical, Warning, Notice, Monitor).
* **Dual-Mode Output:** Generates separate YAML files for Movies and Shows to satisfy Kometa's strict validation.
* **Script Chaining:** Built-in support for running any external scripts (Python or shell) as part of the pipeline.

# 🚀 Installation

Clone the repository:

```bash
git clone https://github.com/theovit/Maintainerr-Poster-Overlay-for-Kometa.git
cd Maintainerr-Poster-Overlay-for-Kometa
```

Run the interactive installer (recommended):

```bash
chmod +x install.sh
./install.sh
```

Or manual setup:

```bash
pip3 install requests PyYAML PlexAPI
cp config.yaml.template config.yaml
nano config.yaml
chmod +x trigger.sh
```

# ⚙️ Configuration

The `config.yaml` is the single source of truth. Below is a breakdown of the key sections. Copy `config.yaml.template` to get started — it contains all keys with comments.

### 1. Connection

Define your connection details for Maintainerr, Plex, and your *arrs.

```yaml
connect:
  maintainerr:
    maintainerr_host: "192.168.1.100"
    maintainerr_port: 6246
    maintainerr_user: "admin"
    maintainerr_pass: "your#secure#password"

  plex:
    url: "http://192.168.1.100:32400"
    token: "YOUR_PLEX_TOKEN"

  sonarr_instances:
    - name: "Sonarr - TV"
      url: "http://192.168.1.50:8989"
      api_key: "API_KEY_HERE"
      path_mapping:
        sonarr_base_path: "/data/tv"          # path as Sonarr sees it
        local_base_path: "/mnt/user/media/tv" # path as this script sees it

  radarr_instances:
    - name: "Radarr - Movies"
      url: "http://192.168.1.50:7878"
      api_key: "API_KEY_HERE"
      library_path: "/mnt/user/media/movies"  # defined but not yet used by scripts
```

### 2. Output Paths

Where the generated Kometa YAML files will be saved.

```yaml
output:
  movies_path: "/path/to/kometa/config/overlays/maintainerr_overlays_movies.yaml"
  shows_path: "/path/to/kometa/config/overlays/maintainerr_overlays_shows.yaml"
  returning_path: "/path/to/kometa/config/overlays/returning_overlays.yaml"
```

### 3. Triggers

Define the thresholds (in days) for each urgency level.

```yaml
triggers:
  critical_days: 3    # Less than 3 days = Critical (Red)
  warning_days: 7     # Less than 7 days = Warning (Orange)
  notice_days: 14     # Less than 14 days = Notice (Grey)

  # If true, items get the "Monitor" style as soon as they enter the Maintainerr collection
  use_maintainerr_limit: true
```

### 4. Styles (Global vs. Specific)

This project uses a Defaults/Override model. Set your baseline look in `global_defaults`, and only override what differs per urgency level in `styles`.

- **`global_defaults`** — Applied to everything (font, alignment, size, position).
- **`styles` (critical / warning / notice / monitor)** — Override individual values (e.g., change background color to Red for Critical). Set any field to `~` to inherit from global.

### 5. Asset Grabber

Ensures you always apply overlays to clean artwork.

```yaml
assets:
  enabled: true
  path: "/path/to/kometa/config/assets"
  grab_originals: true  # prefers upstream metadata provider images over local/overlaid ones
  libraries:
    - "Movies"
    - "TV Shows"
```

### 6. External Scripts

Run other Python or shell scripts (e.g. TSSK) as part of the pipeline.

```yaml
scripts:
  - name: "TSSK TV Shows"
    path: "/path/to/TSSK/TSSK.py"
    enabled: true
  - name: "TSSK Anime"
    path: "/path/to/TSSK_Anime/TSSK.py"
    enabled: true
```

### 7. Execution & Paths

Configure the wrapper behavior and file locations.

```yaml
execution:
  wait_time: 300        # debounce wait time in seconds
  python_cmd: "python3"

  lock_file: "/tmp/kometa_sync.lock"
  timer_file: "/tmp/kometa_sync.timer"
  log_file: "/tmp/kometa_sync_wrapper.log"

  asset_grabber_path: "asset-grabber.py"
  overlay_generator_path: "kometa_maintainerr_overlay_yaml.py"

  kometa_path: "/path/to/kometa.py"
  kometa_args: "--run-overlays"  # overlay-only pass; full --run stays on background Kometa's schedule
```

### 8. Returning Series Manager

Configures stub file creation and overlay generation for upcoming shows.

```yaml
returning:
  generate_overlay: true
  tba_text: "T B A"         # label for shows with real episodes but no known next air date
  template_file: "/path/to/assets/blank.mp4"
  stub_suffix: " - kometa-overlay-lock.mp4"
  remonitor_on_first_episode: true  # re-enables Sonarr monitoring when first real file appears
  libraries:
    - "TV Shows"
    - "Anime"

  # Secondary strip: "NO EPISODES YET" for shows with zero episode files
  overlay_style:
    text: "NO EPISODES YET"
    group: "TSSK_stub"
    weight: 20
    backdrop_color: "#1c2333"
    backdrop_height: 90
    backdrop_vertical_offset: 130
    font_color: "#7ec8e3"
    vertical_offset: 145      # = backdrop_offset + height/2 - font_size/2 + 5 (baseline nudge)

  # Primary bottom strip: "T B A" for undated stubs and shows with no known return date
  tba_style:
    group: "TSSK_text"
    weight: 12                # beats TSSK RETURNING (weight 10)
    backdrop_group: "TSSK_backdrop"
    backdrop_color: "#001f3f"
    backdrop_vertical_offset: 20
    font_color: "#ff9000"
    vertical_offset: 35

  # Date overlay: "RETURNS APR 20" for shows with a known nextAiring date in Sonarr
  date_overlay:
    enabled: true
    path: "/path/to/kometa/config/overlays/returning_dates_overlays.yaml"
    text_format: "RETURNS {date}"
    date_format: "%b %-d"
    group: "TSSK_text"
    weight: 15                # higher than TSSK returning (10), lower than new season soon (25)
    font_color: "#ff9000"
    vertical_offset: 55
```

# 🤖 Automation (Sonarr / Radarr)

To trigger this script automatically when new media is added:

1. Go to: **Settings → Connect → + → Custom Script**
2. Name: **Kometa Sync**
3. Triggers: Check **On File Import** and **On File Upgrade**
4. Path: Select the `trigger.sh` file
5. Save

#### Cron job

Since Maintainerr runs on a schedule, you should also run this script periodically.

```bash
crontab -e
# Run at 4am daily
0 4 * * * /path/to/Maintainerr-Poster-Overlay-for-Kometa/trigger.sh >> /path/to/cron_output.log 2>&1
```

# 🔗 Integrating with Kometa

Add the generated overlay files to your main Kometa `config.yml`. Load the date overlay file **after** your TSSK returning overlay file so it can override the generic "RETURNING" label for shows with a known date.

```yaml
libraries:
  Movies:
    overlay_files:
      - file: config/overlays/maintainerr_overlays_movies.yaml

  TV Shows:
    overlay_files:
      - file: config/overlays/maintainerr_overlays_shows.yaml
      - file: config/overlays/returning_overlays.yaml          # NO EPISODES YET + TBA strips
      - file: config/overlays/returning_dates_overlays.yaml    # RETURNS APR 20 (load after TSSK)
```

# 🛠️ Manual Usage

```bash
# Full pipeline with debounce
./trigger.sh

# Run immediately (skip debounce timer)
./trigger.sh --now

# Individual modules
python3 kometa_maintainerr_overlay_yaml.py
python3 returning_series_manager.py
python3 asset-grabber.py

# Dry run (returning series — preview only, no changes)
python3 returning_series_manager.py --dry-run
```
