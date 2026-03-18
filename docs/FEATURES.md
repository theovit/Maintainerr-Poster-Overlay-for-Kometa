# Features

## Overlay Generation (Maintainerr → Kometa)
- [stable] Reads all Maintainerr collections via HTTP API and computes time-remaining per item
- [stable] Groups items into urgency tiers: Critical, Warning, Notice, Monitor
- [stable] Generates separate Kometa overlay YAML files for movies and shows
- [stable] Urgency thresholds configurable via `triggers` config section
- [stable] `use_maintainerr_limit` option: show overlay as soon as item enters any Maintainerr collection
- [stable] Global defaults + per-urgency style overrides (font, color, position, text template)
- [stable] Font path passthrough — if not found locally, passes path to Kometa for resolution
- [stable] Dual-mode ID resolution: tries tmdbId/tvdbId fields, then plexData.guids, then main guid string

## Returning Series Manager
- [stable] Scans all configured Sonarr instances for monitored shows with status `continuing` or `upcoming`
- [stable] Creates stub `.mp4` files (S00E99 format) for shows with no episodes on disk
- [stable] Enforces Sonarr media management settings (Create Empty Folders = true, Delete Empty Folders = false)
- [stable] Adds `series-returning-lock` Plex label to stub shows
- [stable] Marks stub episode as watched in Plex so it doesn't appear in "Continue Watching"
- [stable] Cleans up stub files and removes Plex label when real media is detected
- [stable] Generates `returning_overlays.yaml` for Kometa with configurable overlay style
- [stable] Path mapping support for remote Sonarr / local script setups
- [stable] Multi-instance Sonarr support

## Asset Grabber
- [stable] Connects to Plex and downloads posters for all items in configured libraries
- [stable] Saves posters to Kometa asset directory using exact disk folder names for correct matching
- [stable] Downloads season posters (Season00.jpg, Season01.jpg, etc.) for TV shows
- [stable] `grab_originals` mode: prefers metadata-provider images (TMDb/TVDb) over local/overlaid ones
- [stable] Smart skip: checks for both `.jpg` and `.webp` versions before re-downloading
- [stable] Content-type detection: saves as `.webp` when Plex serves WebP instead of JPEG

## Pipeline Orchestration (trigger.sh)
- [stable] Debounce mechanism: waits for configurable silence period before running (handles season pack imports)
- [stable] Single-instance locking via `flock` — prevents concurrent pipeline runs
- [stable] Auto-tails logs after triggering (stops when worker finishes)
- [stable] `--now` / `--skip-wait` flag to bypass debounce and run immediately
- [stable] Permission error detection on timer/lock files with actionable fix message
- [stable] Config-driven: all paths and settings read from `config.yaml` at runtime
- [stable] Generic external scripts system: runs arbitrary scripts (Python or shell) as step 2, with per-script name/path/args/enabled control

## Installation
- [stable] Interactive installer (`install.sh`) with guided config wizard
- [stable] Auto-detects and installs Python 3 and venv across apt/dnf/yum/apk/pacman
- [stable] Creates virtualenv and installs all pip dependencies
- [stable] Patches `trigger.sh` and `config.yaml` to use venv Python path
