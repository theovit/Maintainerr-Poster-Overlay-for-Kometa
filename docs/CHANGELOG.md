# Changelog

## [Unreleased]

## [0.6.0] — 2026-03-17
### Added
- Generic external scripts system in `trigger.sh`: step 2 now runs any list of scripts defined in root-level `scripts:` config key, with per-script `name`, `path`, `args`, and `enabled` fields; supports both Python and shell scripts, each run in their own subshell so `cd` changes don't bleed between scripts
- Smart asset skip in `asset-grabber.py`: checks for both `.jpg` and `.webp` before re-downloading so existing WebP assets aren't redundantly fetched
- WebP content-type detection in `asset-grabber.py`: inspects `Content-Type` response header and saves as `.webp` when Plex serves WebP, preventing corrupt image files from mismatched extensions

### Removed
- `requirements.txt` — dependencies are now managed via `install.sh` venv setup

### Changed
- `trigger.sh` TSSK-specific runner replaced by generic scripts runner; `tssk.enabled` config key is no longer read

## [0.5.0] — 2026-03-17
### Added
- Interactive installation script (`install.sh`) with guided configuration wizard
- Auto-detects Python 3 and installs system packages across apt/dnf/yum/apk/pacman
- Creates virtualenv and patches `trigger.sh` + `config.yaml` to use it

## [0.4.0] — prior
### Changed
- Stub files renamed from arbitrary format to `S00E99` to ensure Plex detects them as Season 0 specials
- Overhauled documentation and README
- Logging mode reverted to overwrite (`mode='w'`) from append

## [0.3.0] — prior
### Added
- Multi-instance Sonarr support in `returning_series_manager.py`
- Path mapping (`sonarr_base_path` / `local_base_path`) for remote Sonarr setups
- Sonarr media management settings enforcement (Create Empty Folders, no Delete Empty Folders)
- File logging support for returning series manager

## [0.2.0] — prior
### Added
- `returning_series_manager.py` — stub file creation and "RETURNING" overlay generation
- Plex label (`series-returning-lock`) management and automatic cleanup when real media arrives
- Stub episode marked as watched in Plex via PlexAPI

## [0.1.0] — prior
### Added
- `kometa_maintainerr_overlay_yaml.py` — Maintainerr collection → Kometa overlay YAML generation
- Urgency tiers: Critical, Warning, Notice, Monitor
- `asset-grabber.py` — Plex poster downloader for clean pre-overlay assets
- `trigger.sh` — debounce wrapper with flock locking and auto-tail logging
- `config.yaml.template` — single config for all scripts
