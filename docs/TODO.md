# TODO

## High

## Medium
- [ ] `install.sh` config wizard builds raw JSON via shell string interpolation — passwords with `"`, `$`, or `\` will silently corrupt the config write
- [ ] Radarr instances (Movies + Anime Movies) are running but not integrated — `returning_series_manager.py` is Sonarr-only; no "returning" stubs for movies
- [ ] Add `--dry-run` flag to `returning_series_manager.py` to preview stub create/delete actions without making changes

## Low
- [ ] `trigger.sh` `--watch` flag mentioned in README but not implemented (auto-watch is always on) — remove from README or implement as no-op alias
- [ ] README connection section still shows `library_path` but actual config uses `path_mapping.sonarr_base_path` / `local_base_path` — docs out of sync

## Long-term
- [ ] Docker image / compose file for containerized deployment
- [ ] Web UI or status page showing overlay counts and stub status
- [ ] Radarr integration in returning_series_manager (currently Sonarr-only)
