# TODO

## High
- [ ] returning_series_tba overlay style — currently inherits returning_series style; may want distinct color/text to visually separate "no date" from "returning with date"

## Medium
- [ ] install.sh JSON injection vulnerability (passwords with special chars passed via python -c)
- [ ] Tune Kometa api_call_delay — 0.1s crashes Plex web UI, 0.5s is stable but slow; find the minimum safe value

## Long-term
- [ ] Docker image / compose file for containerized deployment
- [ ] Web UI or status page showing overlay counts and stub status
- [ ] Radarr integration in returning_series_manager (upcoming movies)
