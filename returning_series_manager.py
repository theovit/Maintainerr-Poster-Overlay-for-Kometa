import os
import sys
import yaml
import requests
import logging
import shutil
import argparse

# =======================================================
# CONFIGURATION & CONSTANTS
# =======================================================
DEFAULT_CONFIG_PATH = 'config.yaml'
VIDEO_EXTENSIONS = ('.mkv', '.mp4', '.avi', '.m4v', '.mov', '.wmv')
PLEX_LABEL_NAME = 'series-returning-lock'

# Attempt to import plexapi
try:
    from plexapi.server import PlexServer
    PLEX_AVAILABLE = True
except ImportError:
    PLEX_AVAILABLE = False

def load_config():
    """Loads the YAML configuration file."""
    try:
        with open(DEFAULT_CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"CRITICAL: {DEFAULT_CONFIG_PATH} not found.")
        sys.exit(1)

def setup_logging(level_str, log_file_path=None):
    """
    Sets up logging to Console AND File.
    """
    level = getattr(logging, level_str.upper(), logging.INFO)
    
    # Reset handlers
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.handlers = []

    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file_path:
        try:
            # Mode 'w' overwrites/wipes the log each run.
            file_handler = logging.FileHandler(log_file_path, mode='w', encoding='utf-8')
            handlers.append(file_handler)
        except Exception as e:
            print(f"[WARN] Could not create log file at '{log_file_path}': {e}")

    logging.basicConfig(
        format='%(asctime)s - %(levelname)s - %(message)s',
        level=level,
        handlers=handlers
    )

def get_sonarr_headers(api_key):
    return {
        "X-Api-Key": api_key,
        "Content-Type": "application/json"
    }

def ensure_sonarr_settings(instance_name, base_url, api_key):
    """
    Enforces: Create Empty Series Folders = True | Delete Empty Folders = False
    """
    try:
        headers = get_sonarr_headers(api_key)
        config_url = f"{base_url.rstrip('/')}/api/v3/config/mediamanagement"
        
        response = requests.get(config_url, headers=headers)
        response.raise_for_status()
        config_data = response.json()
        
        create_empty = config_data.get('createEmptySeriesFolders', False)
        delete_empty = config_data.get('deleteEmptyFolders', False)
        
        # We want: Create=True, Delete=False
        if not create_empty or delete_empty:
            logging.info(f"[{instance_name}] Updating Media Management settings...")
            
            if not create_empty:
                config_data['createEmptySeriesFolders'] = True
                logging.info(f"  > Set 'Create Empty Series Folders' to True")
            
            if delete_empty:
                config_data['deleteEmptyFolders'] = False
                logging.info(f"  > Set 'Delete Empty Folders' to False")
            
            config_id = config_data.get('id', 1)
            put_url = f"{config_url}/{config_id}"
            
            update_response = requests.put(put_url, json=config_data, headers=headers)
            update_response.raise_for_status()
            logging.info(f"[{instance_name}] Settings updated successfully.")
        else:
            logging.debug(f"[{instance_name}] Media Management settings already correct.")

    except requests.exceptions.RequestException as e:
        logging.error(f"[{instance_name}] Failed to update Sonarr settings: {e}")

def get_sonarr_series(instance_name, base_url, api_key):
    """Fetches all series from Sonarr."""
    try:
        url = f"{base_url.rstrip('/')}/api/v3/series"
        logging.info(f"[{instance_name}] Connecting to Sonarr at {url}")
        response = requests.get(url, headers=get_sonarr_headers(api_key))
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"[{instance_name}] Error connecting to Sonarr: {e}")
        return []

def has_real_media(show_path, stub_suffix):
    """
    Returns True if any video file (other than stub) exists.
    Exits immediately upon finding the first valid file for efficiency.
    """
    if not os.path.exists(show_path):
        return False
    for root, _, files in os.walk(show_path):
        for file in files:
            # Check if the file is a video and not a stub
            if file.lower().endswith(VIDEO_EXTENSIONS) and not file.endswith(stub_suffix):
                logging.debug(f"  > Found real media: {os.path.join(root, file)}")
                return True
    return False

def find_plex_show(plex, tmdb_id=None, tvdb_id=None, title=None):
    """Finds a show in Plex using GUIDs for precision, with title as fallback."""
    if not plex:
        return None

    # --- GUID Search (Priority) ---
    guid_map = {}
    if tmdb_id: guid_map[f"tmdb://{tmdb_id}"] = "TMDb"
    if tvdb_id: guid_map[f"tvdb://{tvdb_id}"] = "TVDb"

    if guid_map:
        for library in plex.library.sections():
            if library.type == 'show':
                for guid_str, id_type in guid_map.items():
                    try:
                        results = library.search(guid=guid_str)
                        if results:
                            logging.debug(f"  > Plex: Found '{results[0].title}' via GUID '{guid_str}'")
                            return results[0]
                    except Exception:
                        # Some Plex versions might error on invalid GUID searches
                        logging.debug(f"  > Plex: Could not perform GUID search for '{guid_str}' in '{library.title}'")
    
    # --- Title Search (Fallback) ---
    if title:
        logging.debug(f"  > Plex: GUID search failed. Falling back to title search for '{title}'")
        try:
            results = plex.search(title, mediatype='show')
            # If we have IDs, try to find the best match from title results
            if results and guid_map:
                for show in results:
                    show_guids = [g.id for g in show.guids]
                    if any(g in show_guids for g in guid_map.keys()):
                        logging.debug(f"  > Plex: Matched '{show.title}' via GUID after title search.")
                        return show
            elif results:
                logging.warning(f"  > Plex: Found show '{results[0].title}' by title only. Match may not be 100% accurate.")
                return results[0]
        except Exception as e:
            logging.error(f"  > Plex title search error: {e}")

    return None

def remonitor_sonarr_series(instance_name, base_url, api_key, show, dry_run=False):
    """Sets a series and all its episodes to monitored in Sonarr."""
    title = show.get('title', 'Unknown')
    series_id = show.get('id')

    if not series_id:
        logging.warning(f"  > [{instance_name}] Cannot re-monitor '{title}': missing Sonarr series ID.")
        return

    if dry_run:
        logging.info(f"  [DRY RUN] Would re-monitor all episodes for '{title}' in Sonarr.")
        return

    headers = {**get_sonarr_headers(api_key), "Content-Type": "application/json"}
    api_base = f"{base_url.rstrip('/')}/api/v3"

    # 1. Set series itself to monitored
    try:
        series_data = dict(show)
        series_data['monitored'] = True
        resp = requests.put(f"{api_base}/series/{series_id}", json=series_data, headers=headers)
        resp.raise_for_status()
        logging.info(f"  > [{instance_name}] Series '{title}' set to monitored.")
    except Exception as e:
        logging.error(f"  > [{instance_name}] Failed to re-monitor series '{title}': {e}")
        return

    # 2. Get all episode IDs
    try:
        resp = requests.get(f"{api_base}/episode", params={"seriesId": series_id}, headers=headers)
        resp.raise_for_status()
        episode_ids = [ep['id'] for ep in resp.json()]
    except Exception as e:
        logging.error(f"  > [{instance_name}] Failed to fetch episodes for '{title}': {e}")
        return

    # 3. Monitor all episodes
    if episode_ids:
        try:
            resp = requests.put(f"{api_base}/episode/monitor",
                                json={"episodeIds": episode_ids, "monitored": True},
                                headers=headers)
            resp.raise_for_status()
            logging.info(f"  > [{instance_name}] Monitored {len(episode_ids)} episodes for '{title}'.")
        except Exception as e:
            logging.error(f"  > [{instance_name}] Failed to monitor episodes for '{title}': {e}")


def cleanup_real_media(plex, show_path, stub_suffix, tmdb_id=None, tvdb_id=None, title=None, dry_run=False):
    """Deletes stub files and removes Plex labels for shows with real media."""
    if dry_run:
        logging.info(f"[DRY RUN] '{title}' has real media. Would remove stub and label.")
        return

    logging.info(f"Cleanup: '{title}' has real media. Removing stub and label.")

    # 1. Delete stub file(s)
    stubs_found = 0
    if os.path.exists(show_path):
        for root, _, files in os.walk(show_path):
            for file in files:
                if file.endswith(stub_suffix):
                    try:
                        stub_path = os.path.join(root, file)
                        os.remove(stub_path)
                        stubs_found += 1
                        logging.info(f"  > Cleanup: Deleted stub file at '{stub_path}'")
                    except OSError as e:
                        logging.error(f"  > Cleanup: Failed to delete stub '{stub_path}': {e}")
    if stubs_found == 0:
        logging.debug("  > Cleanup: No stub files found to delete.")

    # 2. Remove Plex Label
    remove_plex_label(plex, tmdb_id, tvdb_id, title)

def process_plex_label(plex, tmdb_id=None, tvdb_id=None, title=None, stub_suffix=None, dry_run=False):
    """Labels show in Plex and marks stub episode as watched."""
    if not plex: return

    found_show = find_plex_show(plex, tmdb_id=tmdb_id, tvdb_id=tvdb_id, title=title)

    if found_show:
        # 1. Add Label (if missing)
        current_labels = [l.tag for l in found_show.labels]
        if PLEX_LABEL_NAME not in current_labels:
            if dry_run:
                logging.info(f"  [DRY RUN] Would add label '{PLEX_LABEL_NAME}' to '{found_show.title}'")
            else:
                logging.info(f"  > Plex: Adding label '{PLEX_LABEL_NAME}' to '{found_show.title}'")
                found_show.addLabel(PLEX_LABEL_NAME)
        else:
            logging.debug(f"  > Plex: Label already exists on '{found_show.title}'")

        # 2. Mark Stub Episode as Watched
        # Run this even if label exists, in case the stub was just scanned.
        found_stub = False
        for episode in found_show.episodes():
            # Check S00 specials first, as it's most likely our stub
            if episode.seasonNumber == 0:
                for media in episode.media:
                    for part in media.parts:
                        if part.file and part.file.endswith(stub_suffix):
                            found_stub = True
                            if not episode.isWatched:
                                if dry_run:
                                    logging.info(f"  [DRY RUN] Would mark stub episode '{episode.title}' as watched.")
                                else:
                                    logging.info(f"  > Plex: Marking stub episode '{episode.title}' as watched.")
                                    episode.markWatched()
                            else:
                                logging.debug(f"  > Plex: Stub episode '{episode.title}' already watched.")
                            return  # Exit after finding and processing stub

        if not found_stub:
            logging.debug(f"  > Plex: Stub file for '{found_show.title}' not found in Plex yet.")
    else:
        id_str = f"TMDb:{tmdb_id}" if tmdb_id else f"TVDb:{tvdb_id}"
        logging.warning(f"  > Plex: Could not find show '{title}' ({id_str}).")

def remove_plex_label(plex, tmdb_id=None, tvdb_id=None, title=None, dry_run=False):
    """Removes the specific lock label from a show in Plex."""
    if not plex: return

    found_show = find_plex_show(plex, tmdb_id=tmdb_id, tvdb_id=tvdb_id, title=title)

    if found_show:
        current_labels = [l.tag for l in found_show.labels]
        if PLEX_LABEL_NAME in current_labels:
            if dry_run:
                logging.info(f"  [DRY RUN] Would remove Plex label from '{found_show.title}'")
            else:
                logging.info(f"  > Cleanup: Removing Plex label for '{found_show.title}'")
                found_show.removeLabel(PLEX_LABEL_NAME)
        else:
            logging.debug(f"  > Cleanup: Plex label not found on '{found_show.title}', nothing to do.")
    else:
        id_str = f"TMDb:{tmdb_id}" if tmdb_id else f"TVDb:{tvdb_id}"
        logging.warning(f"  > Cleanup: Could not find Plex show '{title}' ({id_str}) to remove label.")

def create_stub_file(show_path, show_title, template_file, stub_suffix, dry_run=False):
    """Creates the dummy file if missing."""
    safe_title = "".join([c for c in show_title if c.isalpha() or c.isdigit() or c in ' .-_']).strip()

    # NEW: Force S00E99 format so Plex detects it as a special
    stub_filename = f"{safe_title} - S00E99{stub_suffix}"

    stub_path = os.path.join(show_path, stub_filename)

    if os.path.exists(stub_path):
        return True

    if dry_run:
        logging.info(f"  [DRY RUN] Would create stub: {stub_path}")
        return True

    if not os.path.exists(show_path):
        try:
            os.makedirs(show_path)
            logging.info(f"  > Created missing folder: {show_path}")
        except OSError as e:
            logging.error(f"  > Failed to create folder: {e}")
            return False

    try:
        if template_file and os.path.exists(template_file):
            shutil.copy(template_file, stub_path)
            logging.info(f"  > Stub created (from template): {stub_path}")
        else:
            with open(stub_path, 'wb') as f:
                f.write(b'\0' * 1024)
            logging.warning(f"  > Stub created (empty file): {stub_path}")
        return True
    except Exception as e:
        logging.error(f"  > Failed to create stub file: {e}")
        return False

def merge_styles(global_defaults, specific_style):
    if not specific_style:
        return global_defaults.copy()
    final_style = global_defaults.copy()
    for key, value in specific_style.items():
        if value is not None:
            final_style[key] = value
    return final_style

def validate_font(style_dict):
    font_path = style_dict.get('font')
    if font_path:
        if os.path.exists(font_path):
            return style_dict
        if not os.path.exists(font_path):
            logging.warning(f"  [WARN] Font file not found at: {font_path}")
            logging.warning("  [WARN] Removing font setting to use Kometa default.")
            del style_dict['font']
    return style_dict

def process_sonarr_instance(instance, plex_server, config_settings, dry_run=False):
    """
    Processes a single Sonarr instance.
    Returns three buckets:
      'dated'        — stubs (0 eps) with a known nextAiring date
      'undated'      — stubs (0 eps) with no nextAiring date
      'with_eps_tba' — shows that have real episodes but no nextAiring date
    """
    name = instance.get('name', 'Unknown')
    url = instance.get('url')
    api_key = instance.get('api_key')
    
    # Path mapping is now crucial for remote Sonarr/local Plex setups
    path_mapping = instance.get('path_mapping', {})
    sonarr_base_path = path_mapping.get('sonarr_base_path')
    local_base_path = path_mapping.get('local_base_path')

    if not all([url, api_key, sonarr_base_path, local_base_path]):
        logging.error(f"[{name}] Skipping: Missing url, api_key, or path_mapping settings.")
        return {'dated':{'tmdb_ids':[],'tvdb_ids':[]},'undated':{'tmdb_ids':[],'tvdb_ids':[]},'with_eps_tba':{'tmdb_ids':[],'tvdb_ids':[]}}

    ensure_sonarr_settings(name, url, api_key)

    template_file = config_settings['template_file']
    stub_suffix = config_settings['stub_suffix']
    remonitor_on_first_episode = config_settings.get('remonitor_on_first_episode', True)

    series_list = get_sonarr_series(name, url, api_key)
    instance_ids = {
        'dated':        {'tmdb_ids': [], 'tvdb_ids': []},
        'undated':      {'tmdb_ids': [], 'tvdb_ids': []},
        'with_eps_tba': {'tmdb_ids': [], 'tvdb_ids': []},
    }

    logging.info(f"[{name}] Scanning {len(series_list)} shows...")

    for show in series_list:
        status = show.get('status', '').lower()

        if status not in ['continuing', 'upcoming']:
            continue
            
        title = show.get('title')
        tmdb_id = show.get('tmdbId')
        tvdb_id = show.get('tvdbId')
        sonarr_path = show.get('path', '')
        
        # Determine if the show has real files using Sonarr's stats
        stats = show.get('statistics', {})
        has_files = stats.get('episodeFileCount', 0) > 0

        # --- Path Mapping ---
        if not sonarr_path.startswith(sonarr_base_path):
            logging.warning(f"  > [{name}] Show '{title}' path '{sonarr_path}' does not match sonarr_base_path '{sonarr_base_path}'. Skipping.")
            continue
        
        relative_path = os.path.relpath(sonarr_path, sonarr_base_path)
        local_show_path = os.path.join(local_base_path, relative_path)
        logging.debug(f"  > Path mapping: '{sonarr_path}' -> '{local_show_path}'")

        if has_files:
            # This show has files — clean up stub/label and optionally re-monitor all episodes
            cleanup_real_media(plex_server, local_show_path, stub_suffix, tmdb_id, tvdb_id, title, dry_run)
            if remonitor_on_first_episode:
                remonitor_sonarr_series(name, url, api_key, show, dry_run)
            # Track shows with real episodes but no known return date for TBA overlay
            if not show.get('nextAiring'):
                if not tmdb_id and not tvdb_id:
                    continue
                bucket = 'with_eps_tba'
                if tmdb_id: instance_ids[bucket]['tmdb_ids'].append(tmdb_id)
                if tvdb_id: instance_ids[bucket]['tvdb_ids'].append(tvdb_id)
        else:
            # This show has NO files, so it's a candidate for the overlay
            if not tmdb_id and not tvdb_id:
                logging.warning(f"[{name}] Show '{title}' is missing both TMDb and TVDb IDs. Cannot process for overlay.")
                continue

            logging.info(f"[{name}] Processing: {title} (TMDb: {tmdb_id}, TVDb: {tvdb_id}) | Status: {status}")

            # 1. Create Stub File
            create_stub_file(local_show_path, title, template_file, stub_suffix, dry_run)

            # 2. Process Plex Label & Watched Status
            if plex_server:
                process_plex_label(plex_server, tmdb_id, tvdb_id, title, stub_suffix, dry_run)
            
            # 3. Split: dated (known return date) vs undated (no date yet)
            bucket = 'dated' if show.get('nextAiring') else 'undated'
            if tmdb_id: instance_ids[bucket]['tmdb_ids'].append(tmdb_id)
            if tvdb_id: instance_ids[bucket]['tvdb_ids'].append(tvdb_id)

    d=instance_ids['dated']; u=instance_ids['undated']; t=instance_ids['with_eps_tba']
    logging.info(f"[{name}] Stubs dated: {len(d['tmdb_ids'])+len(d['tvdb_ids'])}, "
                 f"undated: {len(u['tmdb_ids'])+len(u['tvdb_ids'])}, "
                 f"with-eps TBA: {len(t['tmdb_ids'])+len(t['tvdb_ids'])}")
    return instance_ids

def format_air_date(date_str, date_format="%b %-d"):
    """Format a Sonarr ISO datetime string for display. Appends year if not current year."""
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        fmt = date_format if dt.year == now.year else date_format + " %Y"
        return dt.strftime(fmt).upper()
    except Exception:
        return None


def generate_returning_date_overlays(sonarr_instances, date_overlay_cfg, dry_run=False):
    """
    Generates a Kometa overlay YAML for returning shows that have a known next air date
    in Sonarr. Groups shows by date and writes one overlay entry per date, using the
    TSSK group/weight system so it overrides the generic 'RETURNING' text only for
    shows where a date is known.
    """
    output_path = date_overlay_cfg.get('path')
    if not output_path:
        logging.warning("date_overlay.path not set — skipping returning date overlays.")
        return

    text_format  = date_overlay_cfg.get('text_format', 'RETURNS {date}')
    date_format  = date_overlay_cfg.get('date_format', '%b %-d')
    group        = date_overlay_cfg.get('group', 'TSSK_text')
    weight       = date_overlay_cfg.get('weight', 15)

    # Build per-date groups: { "APR 8": {'tvdb_ids': [...], 'tmdb_ids': [...]} }
    date_groups = {}

    for instance in sonarr_instances:
        name    = instance.get('name', 'Unknown')
        url     = instance.get('url')
        api_key = instance.get('api_key')
        if not url or not api_key:
            continue

        for show in get_sonarr_series(name, url, api_key):
            if show.get('status', '').lower() not in ['continuing', 'upcoming']:
                continue

            next_airing = show.get('nextAiring')
            if not next_airing:
                continue  # No known date — TSSK handles with generic "RETURNING"

            date_label = format_air_date(next_airing, date_format)
            if not date_label:
                continue

            bucket = date_groups.setdefault(date_label, {'tvdb_ids': [], 'tmdb_ids': []})
            if show.get('tvdbId'):
                bucket['tvdb_ids'].append(show['tvdbId'])
            if show.get('tmdbId'):
                bucket['tmdb_ids'].append(show['tmdbId'])

    if not date_groups:
        logging.info("No returning shows with known air dates found — skipping date overlay.")
        return

    logging.info(f"Generating returning date overlays for {len(date_groups)} date group(s)...")

    # Build overlay YAML entries — one per unique date
    overlays_dict = {}
    for date_label, ids in sorted(date_groups.items()):
        text      = text_format.replace('{date}', date_label)
        safe_key  = "returning_date_" + date_label.replace(' ', '_').replace(',', '').replace('/', '_')

        overlay_cfg = {'name': f'text({text})', 'group': group, 'weight': weight}

        # Apply any extra style keys from date_overlay config (font, colors, positioning)
        for key in ('font', 'font_size', 'font_color', 'back_color', 'back_radius',
                    'back_padding', 'back_width', 'back_height',
                    'horizontal_align', 'horizontal_offset',
                    'vertical_align', 'vertical_offset'):
            val = date_overlay_cfg.get(key)
            if val is not None:
                overlay_cfg[key] = val

        entry = {'overlay': overlay_cfg}
        tvdb = sorted(set(ids['tvdb_ids']))
        tmdb = sorted(set(ids['tmdb_ids']))
        if tvdb:
            entry['tvdb_show'] = tvdb
        if tmdb:
            entry['tmdb_show'] = tmdb

        overlays_dict[safe_key] = entry
        logging.info(f"  > {text}: {len(tvdb)} TVDb + {len(tmdb)} TMDb shows")

    if dry_run:
        logging.info(f"[DRY RUN] Would write {len(overlays_dict)} date overlay entries to {output_path}")
        return

    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.dump({'overlays': overlays_dict}, f, sort_keys=False, indent=2, allow_unicode=True)
        logging.info(f"Written returning date overlays to: {output_path}")
    except Exception as e:
        logging.error(f"Failed to write returning date overlay YAML: {e}")


def main():
    parser = argparse.ArgumentParser(description='Returning Series Manager')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview stub create/delete and Plex actions without making any changes')
    args = parser.parse_args()
    dry_run = args.dry_run

    # 1. Basic Setup (Console)
    setup_logging('INFO')
    if dry_run:
        logging.info("*** DRY RUN MODE — no changes will be made ***")
    logging.info("Starting Returning Series Manager (Multi-Instance)...")
    config = load_config()
    
    # 2. Parse Config
    returning_cfg = config.get('returning', {})
    output_cfg = config.get('output', {})
    global_defaults = config.get('global_defaults', {})
    connect_cfg = config.get('connect', {})
    
    plex_cfg = connect_cfg.get('plex', {})
    plex_url = plex_cfg.get('url') or connect_cfg.get('plex_url')
    plex_token = plex_cfg.get('token') or connect_cfg.get('plex_token')

    sonarr_instances = connect_cfg.get('sonarr_instances', [])
    
    # 3. Setup File Logging (Mode 'w')
    log_level = returning_cfg.get('log_level', 'INFO')
    log_file_path = returning_cfg.get('log_file', 'returning_series_manager.log')
    setup_logging(log_level, log_file_path)

    config_settings = {
        'template_file': returning_cfg.get('template_file'),
        'stub_suffix': returning_cfg.get('stub_suffix', '- kometa-overlay-lock.mp4')
    }

    generate_overlay = returning_cfg.get('generate_overlay', False)
    overlay_output_path = output_cfg.get('returning_path')
    overlay_override = returning_cfg.get('overlay_style', {})
    date_overlay_cfg = returning_cfg.get('date_overlay', {})
    generate_date_overlay = date_overlay_cfg.get('enabled', False)

    if not sonarr_instances:
        logging.critical("No 'sonarr_instances' found under 'connect:' in config.yaml.")
        sys.exit(1)

    # 4. Connect Plex
    plex_server = None
    if plex_url and plex_token and PLEX_AVAILABLE:
        try:
            plex_server = PlexServer(plex_url, plex_token)
            logging.info(f"Connected to Plex: {plex_server.friendlyName}")
        except Exception as e:
            logging.error(f"Failed to connect to Plex: {e}")

    # 5. PROCESS INSTANCES
    master = {
        'dated':        {'tmdb_ids': [], 'tvdb_ids': []},
        'undated':      {'tmdb_ids': [], 'tvdb_ids': []},
        'with_eps_tba': {'tmdb_ids': [], 'tvdb_ids': []},
    }
    for instance in sonarr_instances:
        logging.info(f"--- Starting Instance: {instance.get('name')} ---")
        res = process_sonarr_instance(instance, plex_server, config_settings, dry_run)
        for b in ('dated', 'undated', 'with_eps_tba'):
            master[b]['tmdb_ids'].extend(res[b]['tmdb_ids'])
            master[b]['tvdb_ids'].extend(res[b]['tvdb_ids'])
        logging.info(f"--- Instance {instance.get('name')} finished ---")
    def dedup(ids): return sorted(list(set(ids)))
    dated_tmdb        = dedup(master['dated']['tmdb_ids'])
    dated_tvdb        = dedup(master['dated']['tvdb_ids'])
    undated_tmdb      = dedup(master['undated']['tmdb_ids'])
    undated_tvdb      = dedup(master['undated']['tvdb_ids'])
    with_eps_tba_tmdb = dedup(master['with_eps_tba']['tmdb_ids'])
    with_eps_tba_tvdb = dedup(master['with_eps_tba']['tvdb_ids'])
    logging.info(f"Stubs dated: {len(dated_tmdb)+len(dated_tvdb)}, "
                 f"undated: {len(undated_tmdb)+len(undated_tvdb)}, "
                 f"with-eps TBA: {len(with_eps_tba_tmdb)+len(with_eps_tba_tvdb)}")

    # 7. Generate YAML
    if generate_overlay:
        if not overlay_output_path:
            logging.error("returning_path missing")
        else:
            tba_text = returning_cfg.get("tba_text", "T B A")
            # Base style: global_defaults + overlay_style.
            # overlay_style defines the NO EPISODES YET secondary strip (TSSK_stub, offset 160).
            fs = validate_font(merge_styles(global_defaults, overlay_override))
            ov_text = fs.get("text", "NO EPISODES YET")

            # fs_stub = fs plus any optional stub_dated_overlay_style overrides.
            # If stub_dated_overlay_style is absent, fs_stub == fs (overlay_style is already correct).
            stub_dated_override = returning_cfg.get('stub_dated_overlay_style', {})
            fs_stub = validate_font(merge_styles(fs, stub_dated_override))

            # Style for TBA (shows with real eps, no next air date). Inherits from fs.
            tba_override = returning_cfg.get('tba_style', {})
            fs_tba = validate_font(merge_styles(fs, tba_override))

            # Keys that belong to the backdrop entry, not the text overlay.
            # back_color/back_radius/back_padding create a tight bounding-box behind text in Kometa
            # (the "blocky" look) — background is handled entirely by the separate backdrop overlay.
            _BD_KEYS = {'text', 'backdrop_color', 'backdrop_height', 'backdrop_width',
                        'backdrop_group', 'backdrop_weight', 'backdrop_vertical_offset',
                        'back_color', 'back_radius', 'back_padding'}

            def mk_text(text, style, tm, tv):
                s = {k: v for k, v in style.items() if k not in _BD_KEYS and v is not None}
                o = {"overlay": {"name": f"text({text})"}}
                o["overlay"].update(s)
                o["tmdb_show"] = tm
                o["tvdb_show"] = tv
                return o

            def mk_backdrop(style, tm, tv):
                bd_color = style.get("backdrop_color")
                if not bd_color:
                    return None
                o = {"overlay": {
                    "name": "backdrop",
                    "back_color": bd_color,
                    "back_height": style.get("backdrop_height", 90),
                    "back_width": style.get("backdrop_width", 950),
                    "horizontal_align": style.get("horizontal_align", "center"),
                    "horizontal_offset": style.get("horizontal_offset", 0),
                    "vertical_align": style.get("vertical_align", "bottom"),
                    "vertical_offset": style.get("backdrop_vertical_offset", 20),
                    "group": style.get("backdrop_group", "TSSK_backdrop"),
                    "weight": style.get("backdrop_weight", 12),
                }}
                o["tmdb_show"] = tm
                o["tvdb_show"] = tv
                return o

            # ALL stubs (0 eps, dated or undated) get the secondary "NO EPISODES YET" strip
            # in TSSK_stub group at the higher vertical position.
            all_stub_tmdb = dedup(dated_tmdb + undated_tmdb)
            all_stub_tvdb = dedup(dated_tvdb + undated_tvdb)

            # TBA (bottom strip, TSSK_text group) applies to TWO cases:
            #   - Undated stubs (0 eps, no date)  → pairs with NO EPISODES YET strip above
            #   - Shows with real eps but no date → stands alone, beats TSSK RETURNING (wt 10)
            # Dated stubs are excluded: the date overlay (weight 15) occupies that slot instead.
            tba_tmdb = dedup(undated_tmdb + with_eps_tba_tmdb)
            tba_tvdb = dedup(undated_tvdb + with_eps_tba_tvdb)

            kd = {"overlays": {}}

            # Build entries only for non-empty show lists
            entries = []
            if all_stub_tmdb or all_stub_tvdb:
                # Secondary strip: "NO EPISODES YET" at offset 160 in its own group.
                # Renders additively alongside the bottom label (TBA or date) from the other group.
                entries.append(("returning_series_stub", ov_text,  fs_stub, all_stub_tmdb, all_stub_tvdb))
            if tba_tmdb or tba_tvdb:
                entries.append(("returning_series_tba",  tba_text, fs_tba,  tba_tmdb,      tba_tvdb))

            for key, text, style, tm, tv in entries:
                bd = mk_backdrop(style, tm, tv)
                if bd:
                    kd["overlays"][f"backdrop_{key}"] = bd
                kd["overlays"][key] = mk_text(text, style, tm, tv)

            if dry_run:
                logging.info(f"[DRY RUN] Would write {len(kd['overlays'])} overlay entries to {overlay_output_path}")
            else:
                try:
                    os.makedirs(os.path.dirname(overlay_output_path), exist_ok=True)
                    with open(overlay_output_path, "w", encoding="utf-8") as f:
                        yaml.dump(kd, f, sort_keys=False, indent=2, allow_unicode=True)
                    logging.info(f"Wrote overlay YAML to {overlay_output_path}")
                except Exception as e:
                    logging.error(f"Failed to write YAML: {e}")

    if generate_date_overlay:
        generate_returning_date_overlays(sonarr_instances, date_overlay_cfg, dry_run)

    logging.info("Returning Series Manager completed.")

if __name__ == "__main__":
    main()