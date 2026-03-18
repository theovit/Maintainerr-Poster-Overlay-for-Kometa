# TODO

## High
- [ ] `install.sh` still references `requirements.txt` (pip install -r) but the file was deleted — installer will break on fresh installs; needs to either inline the deps or recreate the file
- [ ] `tssk: enabled: true` in live `config.yaml` is now orphaned — new `trigger.sh` reads root-level `scripts:` list and ignores `tssk.enabled`; the config template should be updated and the key removed/documented as deprecated

## Medium
- [ ] `asset-grabber.py` still calls `item.seasons()` for every TV show on every run to discover season list — cache season counts/indices locally (e.g. a small JSON file) so fully-seeded shows make zero Plex API calls; important on shared box where minimizing requests is a priority
- [ ] `asset-grabber.py` hard-imports `plexapi` (no try/except) — crashes the whole pipeline if PlexAPI isn't installed; should match the graceful pattern in `returning_series_manager.py`
- [ ] `install.sh` config wizard builds raw JSON via shell string interpolation — passwords with `"`, `$`, or `\` will silently corrupt the config write
- [ ] Radarr instances (Movies + Anime Movies) are running but not integrated — `returning_series_manager.py` is Sonarr-only; no "returning" stubs for movies
- [ ] `stub_suffix` in live config is `"- kometa-overlay-lock.mp4"`, which produces filenames like `Title - S00E99- kometa-overlay-lock.mp4` (double dash) — cosmetic but worth cleaning up
- [ ] Add `--dry-run` flag to `returning_series_manager.py` to preview stub create/delete actions without making changes

## Low
- [ ] `trigger.sh` `--watch` flag mentioned in README but not implemented (auto-watch is always on) — remove from README or implement as no-op alias
- [ ] README connection section still shows `library_path` but actual config uses `path_mapping.sonarr_base_path` / `local_base_path` — docs out of sync
- [ ] `asset-grabber.py` uses `connect.plex_url` / `connect.plex_token` flat keys; `returning_series_manager.py` uses `connect.plex.url` / `connect.plex.token` nested keys — inconsistent config schema; asset grabber will silently fail if template defaults are used

## Long-term
- [ ] Docker image / compose file for containerized deployment
- [ ] Web UI or status page showing overlay counts and stub status
- [ ] Radarr integration in returning_series_manager (currently Sonarr-only)
