# Memory

## Seedbox constraints
No sudo access, no Docker socket access. Cannot install system packages, manage systemd units, or run privileged commands. Everything runs as user `northmainave`. Plan features accordingly — no Docker deployment, no systemd service files.

## Kometa runs continuously
Kometa is running as a persistent background process (`--log-requests`), not started/stopped by the pipeline. `trigger.sh` triggers an immediate `--run` pass; it does not start Kometa. Don't add "start Kometa" logic to the pipeline.

## Python environment on server
System Python is 3.9. Kometa (and the overlay scripts via `execution.python_cmd`) uses pyenv 3.13.5 at `/home/northmainave/.pyenv/shims/python3`. The `config.yaml` `python_cmd` must point to the pyenv shim, not `/usr/bin/python3`.

## Timer and lock files are in the project tmp/ directory
In the live deployment, `lock_file` and `timer_file` are configured under `~/scripts/Maintainerr-Poster-Overlay-for-Kometa/tmp/`, not `/tmp/`. If these get owned by root (e.g. after a sudo run), delete them: `rm ~/scripts/Maintainerr-Poster-Overlay-for-Kometa/tmp/kometa_sync.*`

## `scripts:` key is at root level in live config
The live `config.yaml` has the `scripts:` list at root level (not nested under `tssk:`), which is what the updated `trigger.sh` expects. The `tssk: enabled: true` key above it is now a no-op. Don't move scripts back under `tssk:`.

## Plex doesn't scan stub immediately
After `returning_series_manager.py` creates a stub file, Plex may not scan it right away. The script checks whether the stub episode appears in Plex and silently skips the "mark watched" step if it hasn't been scanned yet. The label will still be added. On the next run, both will be applied.

## Seedbox home directory has two paths
`/home/northmainave` is a symlink to `/home32/northmainave`. Sonarr (and other apps) resolve paths through the symlink, so they report paths starting with `/home/northmainave/`. The actual filesystem path starts with `/home32/northmainave/`. In `config.yaml`, `path_mapping.sonarr_base_path` must use `/home/northmainave/...` (what Sonarr reports) and `path_mapping.local_base_path` must use `/home32/northmainave/...` (real path). Mixing these up causes all shows to be skipped with "path does not match sonarr_base_path" warnings.

## config.yaml sonarr_instances uses path_mapping, not library_path
The old format had a flat `library_path` key per instance. The current format uses `path_mapping: {sonarr_base_path: ..., local_base_path: ...}`. Both scripts and the template now use `path_mapping`. If upgrading from an old config, migrate manually or re-run `install.sh`.

## Font paths are Kometa-relative, not script-relative
Font paths in the generated YAML are passed through to Kometa as-is. Kometa resolves them relative to its own working directory. The scripts warn if the font isn't found locally but still write the path — this is intentional, as Kometa may resolve it correctly even when the script can't.

## PlexAPI GUID search compatibility
`find_plex_show()` in `returning_series_manager.py` wraps GUID-based Plex searches in try/except because some Plex versions raise exceptions on GUID searches. Falls back to title search automatically.

## Sonarr episodeFileCount is the reliable "has files" check
The script uses `statistics.episodeFileCount > 0` from Sonarr's series response rather than walking the filesystem, for efficiency. The filesystem walk (`has_real_media()`) exists as a utility function but is not called in the main loop.

## Kometa is forked — poster_upload_delay patch must survive updates
Kometa's `modules/library.py` and `modules/config.py` have been manually patched to add a `poster_upload_delay` setting. This throttles poster uploads to Plex to prevent connection pool exhaustion crashing the web UI. When Kometa updates, re-apply these changes:

**`modules/config.py`** — add in two places, alongside `item_refresh_delay`:
```python
# ~line 493 (general settings)
"poster_upload_delay": check_for_attribute(self.data, "poster_upload_delay", parent="settings", var_type="int", default=0),
# ~line 914 (per-library params)
params["poster_upload_delay"] = check_for_attribute(lib, "poster_upload_delay", parent="settings", var_type="int", default=self.general["poster_upload_delay"], do_print=False, save=False)
```

**`modules/library.py`** — add `self.poster_upload_delay = params["poster_upload_delay"]` in `__init__`, then add after each `_upload_image` call in `upload_images`:
```python
if self.poster_upload_delay > 0: time.sleep(self.poster_upload_delay)
```

Set `poster_upload_delay: 2` (seconds) in Kometa's `config.yml` under `settings:`.

## Kometa optimize: false
`optimize: true` in Kometa's Plex config runs a DB optimization after every run — heavy enough to crash the Plex web UI. Kept as `false`. Don't re-enable it.

## Two Sonarr and two Radarr instances
TV Shows and Anime each have their own Sonarr instance. Movies and Anime Movies each have their own Radarr instance. The overlay scripts currently only integrate with Sonarr. Radarr instances are defined in `config.yaml` under `radarr_instances` but nothing reads that key yet.
