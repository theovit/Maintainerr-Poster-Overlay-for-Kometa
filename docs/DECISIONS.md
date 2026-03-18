# Decisions

## Stub files named S00E99 (Season 0, Episode 99)
**Date:** 2026-03-17
**Decision:** Stub files use the naming convention `{title} - S00E99{stub_suffix}` (Season 0, Episode 99 special).
**Why:** Plex requires a recognizable episode filename to scan a file into the library. Season 0 specials are the least intrusive placement — they don't affect "next episode" logic for the main series and are easy to mark as watched so they stay out of "Continue Watching".
**Alternatives considered:** Using S01E00 (would interfere with actual Season 1 tracking) or a generic filename (Plex wouldn't scan it as an episode).
**Consequences:** Stub episodes appear under "Specials" in Plex. The episode must be marked watched explicitly; `returning_series_manager.py` handles this via PlexAPI.

## Log files overwrite on each run (mode='w')
**Date:** 2026-03-17
**Decision:** All log files are opened with `mode='w'` (overwrite), not `mode='a'` (append).
**Why:** Append logs grow unboundedly; overwrite keeps logs focused on the most recent run, which is what matters for debugging. Git history shows this was deliberately reverted from append mode.
**Alternatives considered:** Append with rotation — more complex, adds a dependency.
**Consequences:** Previous run logs are lost. Users who want history should redirect trigger.sh output to a separate dated log file.

## Debounce via timer file polling (not sleep)
**Date:** 2026-03-17
**Decision:** `trigger.sh` implements debounce by writing a target Unix timestamp to a file; the background worker polls the file every ≤10 seconds rather than sleeping for the full wait period.
**Why:** Each new trigger (e.g., Sonarr firing for each file in a season pack) resets the target time forward. Polling lets the worker detect a reset and keep waiting, while a fixed sleep would either expire too early or require killing and restarting the worker process.
**Alternatives considered:** inotify/signal-based approach — more complex and less portable.
**Consequences:** Worker wakes up every 10 seconds; minimal CPU cost. Timer file must be writable by the triggering user.

## Single config.yaml for all scripts
**Date:** 2026-03-17
**Decision:** All three Python scripts share one `config.yaml` file.
**Why:** Reduces duplication and means connection details (Plex, Sonarr) only need to be entered once.
**Alternatives considered:** Per-script config files — simpler isolation but tedious to maintain.
**Consequences:** Config file is large and has sections irrelevant to each individual script. Scripts silently skip sections they don't need.

## Path mapping for Sonarr (sonarr_base_path / local_base_path)
**Date:** 2026-03-17
**Decision:** Sonarr instances require explicit path mapping configuration rather than assuming paths are the same.
**Why:** Common setup has Sonarr in a container with different mount paths than the script host. Without mapping, stub file creation would fail silently or write to wrong paths.
**Alternatives considered:** Auto-detect via comparing paths — too fragile and environment-specific.
**Consequences:** Users with identical Sonarr/local paths still need to configure both fields with the same value.

## Generic scripts system replacing TSSK-specific integration
**Date:** 2026-03-17
**Decision:** `trigger.sh` step 2 was refactored from a TSSK-specific runner (single `tssk.scripts[]` array, `tssk.enabled` flag) to a generic script runner that reads a root-level `scripts:` list of `{name, path, args, enabled}` objects.
**Why:** TSSK was just one use case. The pipeline already needed to run multiple external scripts (two TSSK instances for TV and Anime), and users might want to run other pre-overlay scripts. The generic system handles per-script enable/disable, named logging, custom args, and both Python and shell scripts.
**Alternatives considered:** Keeping TSSK-specific with a second config key for non-TSSK scripts — more config complexity for no gain.
**Consequences:** Old `tssk.enabled` config key is now ignored. Existing configs must move script entries to root-level `scripts:` list. The `config.yaml.template` needs updating.

## WebP content-type detection in asset-grabber
**Date:** 2026-03-17
**Decision:** `asset-grabber.py` now detects the actual `Content-Type` header from Plex's image response and saves as `.webp` if Plex returns `image/webp`, rather than always saving as `.jpg`.
**Why:** Plex sometimes serves WebP images. Saving a WebP file with a `.jpg` extension causes Kometa to load a corrupt/unreadable image. The skip-check was also updated to look for either extension so already-downloaded WebP files aren't re-fetched.
**Alternatives considered:** Force-convert all images to JPEG — adds a Pillow dependency and processing overhead.
**Consequences:** Asset directories may contain a mix of `.jpg` and `.webp` files. Kometa must support WebP (it does as of recent versions).
