# Architecture

## Overview

A set of Python scripts that bridge **Maintainerr** (media deletion scheduler) and **Kometa** (Plex metadata/overlay manager). The system generates Kometa-compatible YAML overlay files and manages stub media files, then triggers a Kometa run to apply the results to Plex.

## Server Environment (Production)

The reference deployment runs on a shared seedbox (Debian 11, no sudo, no Docker socket access):

| Component | Location |
|---|---|
| Scripts | `~/scripts/Maintainerr-Poster-Overlay-for-Kometa/` |
| Kometa | `~/scripts/kometa/` (v2.2.2) |
| Media | `/home32/northmainave/media/` (15TB mount) |
| Plex | Running as user process |
| Sonarr | 2 instances: TV Shows + Anime |
| Radarr | 2 instances: Movies + Anime Movies |
| Python | pyenv 3.13.5 for Kometa; system Python 3.9 otherwise |
| Cron | `trigger.sh` runs at 4am daily |

Kometa runs continuously (`--log-requests`) as a persistent process — it is not started/stopped by the pipeline. `trigger.sh` triggers an immediate `--run` pass on top of the normal schedule.

## Components

### `kometa_maintainerr_overlay_yaml.py`
Reads all Maintainerr collections via REST API, computes time-remaining for each item, classifies items into urgency tiers (Critical / Warning / Notice / Monitor), and writes two Kometa overlay YAML files (movies and shows). Groups items by `{time_string}|{urgency}` to produce one overlay definition per time bucket.

### `returning_series_manager.py`
Connects to one or more Sonarr instances, finds monitored shows that are `continuing` or `upcoming`, and:
1. **Stub management** — shows with zero episode files get a stub `.mp4` (`{title} - S00E99{stub_suffix}`) in the show folder, a `series-returning-lock` Plex label, and the episode marked as watched
2. **Cleanup** — shows that now *have* files get their stub deleted, Plex label removed, and (optionally) all episodes re-monitored in Sonarr (`remonitor_on_first_episode`)
3. **Overlay generation** — writes `returning_overlays.yaml` using a three-bucket classification:
   - `dated` — zero-ep stubs with a known `nextAiring` date → "NO EPISODES YET" strip only (date overlay handles the bottom label)
   - `undated` — zero-ep stubs with no date → "NO EPISODES YET" + "T B A" strips
   - `with_eps_tba` — shows with files but no `nextAiring` → "T B A" strip only (overrides TSSK "RETURNING")
4. **Date overlays** — optionally writes `returning_dates_overlays.yaml` with one "RETURNS {date}" entry per unique air date, using the `TSSK_text` group/weight system

Overlay strips use separate Kometa groups (`TSSK_stub` / `TSSK_text`) so two labels can render simultaneously on the same poster without group-exclusion conflicts.

Currently Sonarr-only. Radarr instances exist on the server but are not yet integrated.

### `asset-grabber.py`
Iterates all items in configured Plex libraries, finds the best "original" poster URL (preferring metadata-provider images over local/overlaid ones), and downloads them to the Kometa asset directory using the exact on-disk folder name for each item. Detects WebP responses from Plex and saves with the correct extension. Skips items where either a `.jpg` or `.webp` already exists.

### `trigger.sh`
Bash orchestrator with two execution modes:
- **Trigger mode** (default): writes a future timestamp to a timer file, spawns a background worker, tails the log
- **Worker mode** (`KOMETA_WORKER_MODE=true`): acquires an exclusive `flock` lock, polls the timer file until silence, then runs the full pipeline in order

Reads all configuration at startup via an embedded Python snippet that parses `config.yaml`.

**Pipeline steps:**
1. Asset Grabber
2. Generic external scripts (root-level `scripts:` list — runs TSSK and anything else configured)
3. Maintainerr overlay generator
4. Returning series manager
5. Kometa

### `install.sh`
One-shot interactive installer. Prompts for all connection details and paths, writes them into `config.yaml` via Python/YAML, patches `trigger.sh` to use the venv Python binary.

## Data Flow

```
Sonarr API ──────────────────────────────────────────────────────┐
                                                                  ▼
                                                    returning_series_manager.py
                                                    ├── creates stub .mp4 files on disk
                                                    ├── labels shows in Plex via PlexAPI
                                                    └── writes returning_overlays.yaml
                                                                  │
Maintainerr API ──────────────────────────────────────────────── │
                                                                  ▼
                                               kometa_maintainerr_overlay_yaml.py
                                               └── writes maintainerr_overlays_movies.yaml
                                                                  │  maintainerr_overlays_shows.yaml
                                                                  │
Plex API ─────────────────────────────────────────────────────── │
                                                                  ▼
                                                         asset-grabber.py
                                                         └── downloads poster.jpg / SeasonXX.jpg
                                                                  │
                                                    External scripts (TSSK, etc.)
                                                                  │
                                                                  ▼
                                                              Kometa
                                                              └── applies overlays → Plex
```

## Key Design Patterns

**Defaults/Override Style System:** `global_defaults` in config defines the base overlay appearance. Each urgency level in `styles` can override individual fields (null = inherit global). Scripts merge them with `merge_styles()`.

**External ID Resolution:** Items in Maintainerr may have IDs in multiple places (top-level `tmdbId`/`tvdbId`, `plexData.guids[]`, or `plexData.guid` string). The overlay generator tries each source in priority order.

**Flock-based Single Instance:** `trigger.sh` opens `$LOCK_FILE` as fd 200 and calls `flock -n 200`. If a worker is already running, new worker invocations exit immediately (`exit 0`), but the timer file gets updated so the running worker keeps waiting.

**Generic Script Runner:** Step 2 reads a root-level `scripts:` list from `config.yaml`. Each entry is `{name, path, args, enabled}`. Scripts run in subshells so working-directory changes are isolated. Supports `.py` (runs via `$PYTHON_CMD`) and any other file (runs directly).

## External Dependencies

| Service | Used by | Protocol |
|---|---|---|
| Maintainerr | `kometa_maintainerr_overlay_yaml.py` | HTTP REST (`/api/collections`, `/api/collections/media/{id}/content/1`) |
| Plex | `asset-grabber.py`, `returning_series_manager.py` | PlexAPI (Python library over HTTP) |
| Sonarr | `returning_series_manager.py` | HTTP REST (`/api/v3/series`, `/api/v3/config/mediamanagement`) |
| Radarr | *(not yet integrated)* | HTTP REST |
| Kometa | invoked by `trigger.sh` | CLI subprocess |

## Config Schema (config.yaml)

```
connect:
  maintainerr:       host, port, user, pass
  plex:              url, token
  sonarr_instances:  [{name, url, api_key, path_mapping: {sonarr_base_path, local_base_path}}]
  radarr_instances:  [{name, url, api_key, library_path}]   ← defined but not yet used by scripts
output:              movies_path, shows_path, returning_path
triggers:            critical_days, warning_days, notice_days, use_maintainerr_limit
global_defaults:     text, font, font_size, font_color, back_color, back_radius, back_padding,
                     horizontal_align, vertical_align, horizontal_offset, vertical_offset
styles:              critical/warning/notice/monitor (same keys, null = inherit)
assets:              enabled, path, grab_originals, libraries[]
returning:           generate_overlay, tba_text, template_file, stub_suffix, remonitor_on_first_episode,
                     log_level, overlay_style{}, tba_style{},
                     date_overlay{enabled, path, text_format, date_format, group, weight, font_*, ...}
execution:           wait_time, python_cmd, lock_file, timer_file, log_file,
                     asset_grabber_path, overlay_generator_path, kometa_path, kometa_args
scripts:             [{name, path, args, enabled}]   ← root-level; replaces tssk.scripts
tssk:                enabled   ← deprecated, no longer read by trigger.sh
```
