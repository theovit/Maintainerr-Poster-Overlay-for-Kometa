# Maintainerr Poster Overlay for Kometa

## Commands

### Run
```bash
# Full pipeline (debounced, watches logs automatically)
./trigger.sh

# Run immediately (skip debounce timer)
./trigger.sh --now

# Individual modules
python3 kometa_maintainerr_overlay_yaml.py
python3 returning_series_manager.py
python3 asset-grabber.py
```

### Install
```bash
chmod +x install.sh
./install.sh
```

### Setup (manual)
```bash
cp config.yaml.template config.yaml
# Edit config.yaml with your settings
# Install deps via install.sh (requirements.txt no longer exists)
```

## Architecture

Three Python scripts + one Bash orchestrator, all configured via a single `config.yaml`.

**Pipeline order (trigger.sh):**
1. `asset-grabber.py` — Downloads clean posters from Plex before overlays are applied
2. External scripts (optional) — Any scripts defined in root-level `scripts:` config key (e.g. TSSK)
3. `kometa_maintainerr_overlay_yaml.py` — Generates Kometa overlay YAML from Maintainerr collections
4. `returning_series_manager.py` — Manages stub files and "RETURNING" overlays for upcoming shows
5. Kometa — Applies the generated overlays to Plex

**Data flow:**
- Maintainerr → overlay generator reads collections via HTTP API → writes `maintainerr_overlays_movies.yaml` + `maintainerr_overlays_shows.yaml`
- Sonarr → returning series manager reads series via HTTP API → creates stub `.mp4` files on disk → writes `returning_overlays.yaml`
- Kometa reads the generated YAML files and applies overlays to Plex library items

**Debounce mechanism (`trigger.sh`):**
The script runs in two modes: Trigger Mode (writes a target timestamp to a timer file, spawns a background worker, then tails logs) and Worker Mode (`KOMETA_WORKER_MODE=true`, acquires a flock lock, polls the timer file until silence, then runs the pipeline). This handles batch imports (e.g., season packs) without duplicate runs.

## Key Files

| File | Purpose |
|---|---|
| `config.yaml.template` | Master config template — copy to `config.yaml` |
| `kometa_maintainerr_overlay_yaml.py` | Reads Maintainerr collections, generates urgency-tiered overlay YAML for movies and shows |
| `returning_series_manager.py` | Scans Sonarr for empty continuing/upcoming series, creates stub files, labels shows in Plex, generates returning overlay YAML |
| `asset-grabber.py` | Downloads original (pre-overlay) posters from Plex for Kometa asset directory; detects WebP vs JPEG from Content-Type header |
| `trigger.sh` | Debounce wrapper — orchestrates the full pipeline with locking |
| `install.sh` | Interactive installer — checks dependencies, creates venv, runs config wizard |
| `blank.mp4` | Template stub file used by returning_series_manager (S00E99 special format) |

## Environment / Config

All config lives in `config.yaml` (never committed — use `config.yaml.template`).

Key sections:
- `connect.maintainerr` — host, port, user, pass
- `connect.plex` — url, token
- `connect.sonarr_instances[]` — name, url, api_key, path_mapping (sonarr_base_path + local_base_path)
- `connect.radarr_instances[]` — name, url, api_key, library_path (defined but not yet used by scripts)
- `output` — movies_path, shows_path, returning_path (all Kometa overlay file destinations)
- `triggers` — critical_days, warning_days, notice_days, use_maintainerr_limit
- `global_defaults` + `styles` — font, colors, positioning for each urgency level
- `assets` — enabled, path, grab_originals, libraries
- `returning` — generate_overlay, template_file, stub_suffix, overlay_style
- `execution` — wait_time, python_cmd, lock_file, timer_file, log_file, kometa_path/args
- `scripts[]` — root-level list of `{name, path, args, enabled}` for external scripts (replaces `tssk.scripts`)

**Path mapping:** `sonarr_instances` requires both `sonarr_base_path` (path as Sonarr sees it) and `local_base_path` (path as this script sees it) to handle remote/container setups.

## Known Gotchas

- Stub files must be named `{title} - S00E99{stub_suffix}` so Plex detects them as Season 0 specials and scans them.
- Plex label `series-returning-lock` is added to stub shows; removed automatically when real media appears.
- `trigger.sh` uses `flock` — only one worker runs at a time. Permission errors on timer/lock files mean they were previously created by root; delete them from the project `tmp/` directory.
- Font paths in generated YAML are relative to Kometa's working directory, not this script's location.
- Log files are opened in `mode='w'` (overwrite each run), not append.
- `asset-grabber.py` requires `PlexAPI` — it is a hard import (no try/except), so missing it crashes the script.
- `tssk.enabled` config key is deprecated and no longer read — external scripts are now controlled via the root-level `scripts:` list.
- On the production seedbox: no sudo, no Docker. Kometa runs continuously as a background process; `trigger.sh` triggers a `--run` pass, it does not start Kometa.
