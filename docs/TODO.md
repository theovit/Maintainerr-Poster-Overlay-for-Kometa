# TODO

## High
- [ ] Debug why trigger.sh doesn't fire from Sonarr/Radarr custom script webhooks — investigate env, path, permissions
- [ ] Re-monitor series in Sonarr when first real episode appears — call Sonarr PUT /api/v3/series to set monitored=true + all episodes monitored when cleanup_real_media runs
- [ ] Release date overlays — when Sonarr has a `nextAiring` date, show it in the returning overlay instead of generic "RETURNING"; evaluate TSSK fork vs custom approach

## Medium
- [ ] Cache season list in asset-grabber to minimize Plex API calls (currently calls item.seasons() per show)
- [ ] install.sh JSON injection vulnerability (passwords with special chars passed via python -c)

## Long-term
- [ ] Docker image / compose file for containerized deployment
- [ ] Web UI or status page showing overlay counts and stub status
- [ ] Radarr integration in returning_series_manager (upcoming movies)
