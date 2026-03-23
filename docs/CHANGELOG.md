# Changelog

## [Unreleased]
### Changed
- `returning_series_manager.py`: overlay logic is now fully additive. All stubs (0 eps) get a "NO EPISODES YET" secondary strip (`TSSK_stub` group, vertical_offset 145, independent of TSSK_text). Undated stubs additionally receive "T B A" at vertical_offset 35 in `TSSK_text` (pairing with NO EPISODES YET above it). Dated stubs pair with "RETURNS DATE" from the date overlay. Shows with real episodes and no air date get "T B A" alone. The old blocky text-box background (`back_color`/`back_radius`/`back_padding`) is removed from text overlays; background is now rendered exclusively via the separate backdrop overlay.
- Visual centering nudge (+5px): all text `vertical_offset` values corrected for font baseline rendering (`tba_style`: 30→35, `overlay_style`: 140→145, `date_overlay`: 50→55). TBA, NO EPISODES YET, and RETURNS DATE now share identical baseline math: `backdrop_vertical_offset + backdrop_height/2 - font_size/2 + 5`.
### Added
- `tba_style` config key: full style definition for the TBA bottom strip — group, weight, TSSK-matching backdrop (#001f3f), orange font (#ff9000), and vertical_offset 35.
- `overlay_style` is now the canonical definition for the NO EPISODES YET secondary strip (TSSK_stub group, vertical_offset 145). `stub_dated_overlay_style` is no longer needed and has been removed from config.
- `date_overlay` config section: generates `returning_dates_overlays.yaml` with per-date "RETURNS {date}" entries for shows with a known `nextAiring` in Sonarr; uses `TSSK_text` group at configurable weight (default 15, beats TSSK RETURNING at 10).
- `remonitor_on_first_episode`: when first real episode file appears during cleanup, all episodes in the series are re-monitored in Sonarr.
- `with_eps_tba` bucket: shows with real episodes but no known next air date are now tracked separately and receive the TBA overlay (superseding TSSK's generic "RETURNING" label).

## [0.7.0] — 2026-03-17
### Added
- `--dry-run` flag for `returning_series_manager.py`: previews stub creation/deletion and Plex label changes without making any modifications
- Season list caching in `asset-grabber.py`: skips Plex `item.seasons()` API calls when season count is unchanged and all poster files exist on disk; cache stored in `asset_season_cache.json`

### Fixed
- `install.sh` config wizard no longer corrupts `config.yaml` when passwords or paths contain `"`, `$`, or `\` — values now passed via environment variables to the Python writer instead of shell string interpolation
- Sonarr instances in `install.sh` wizard now collect `sonarr_base_path` + `local_base_path` (`path_mapping`) instead of single `library_path`, matching actual config format
- `returning_series_manager.py` Plex connection no longer silently skipped when config uses flat plex keys (`plex_url`/`plex_token`) — added fallback for both key formats

### Changed
- README updated: corrected Plex config keys, Sonarr `path_mapping` format, install instructions, scripts section, and removed unimplemented `--watch` flag reference

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
