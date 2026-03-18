import os
import sys
import yaml
import requests
import logging
import shutil

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

def cleanup_real_media(plex, show_path, stub_suffix, tmdb_id=None, tvdb_id=None, title=None):
    """Deletes stub files and removes Plex labels for shows with real media."""
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

def process_plex_label(plex, tmdb_id=None, tvdb_id=None, title=None, stub_suffix=None):
    """Labels show in Plex and marks stub episode as watched."""
    if not plex: return

    found_show = find_plex_show(plex, tmdb_id=tmdb_id, tvdb_id=tvdb_id, title=title)
    
    if found_show:
        # 1. Add Label (if missing)
        current_labels = [l.tag for l in found_show.labels]
        if PLEX_LABEL_NAME not in current_labels:
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
                                logging.info(f"  > Plex: Marking stub episode '{episode.title}' as watched.")
                                episode.markWatched()
                            else:
                                logging.debug(f"  > Plex: Stub episode '{episode.title}' already watched.")
                            return # Exit after finding and processing stub
        
        if not found_stub:
            logging.debug(f"  > Plex: Stub file for '{found_show.title}' not found in Plex yet.")
    else:
        id_str = f"TMDb:{tmdb_id}" if tmdb_id else f"TVDb:{tvdb_id}"
        logging.warning(f"  > Plex: Could not find show '{title}' ({id_str}).")

def remove_plex_label(plex, tmdb_id=None, tvdb_id=None, title=None):
    """Removes the specific lock label from a show in Plex."""
    if not plex: return

    found_show = find_plex_show(plex, tmdb_id=tmdb_id, tvdb_id=tvdb_id, title=title)

    if found_show:
        current_labels = [l.tag for l in found_show.labels]
        if PLEX_LABEL_NAME in current_labels:
            logging.info(f"  > Cleanup: Removing Plex label for '{found_show.title}'")
            found_show.removeLabel(PLEX_LABEL_NAME)
        else:
            logging.debug(f"  > Cleanup: Plex label not found on '{found_show.title}', nothing to do.")
    else:
        id_str = f"TMDb:{tmdb_id}" if tmdb_id else f"TVDb:{tvdb_id}"
        logging.warning(f"  > Cleanup: Could not find Plex show '{title}' ({id_str}) to remove label.")

def create_stub_file(show_path, show_title, template_file, stub_suffix):
    """Creates the dummy file if missing."""
    safe_title = "".join([c for c in show_title if c.isalpha() or c.isdigit() or c in ' .-_']).strip()
    
    # NEW: Force S00E99 format so Plex detects it as a special
    stub_filename = f"{safe_title} - S00E99{stub_suffix}"
    
    stub_path = os.path.join(show_path, stub_filename)

    if os.path.exists(stub_path):
        # logging.debug(f"  > Stub already exists: {stub_filename}")
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

def process_sonarr_instance(instance, plex_server, config_settings):
    """
    Processes a single Sonarr instance.
    Returns a dictionary with 'tmdb_ids' and 'tvdb_ids'.
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
        return {'tmdb_ids': [], 'tvdb_ids': []}

    ensure_sonarr_settings(name, url, api_key)

    template_file = config_settings['template_file']
    stub_suffix = config_settings['stub_suffix']

    series_list = get_sonarr_series(name, url, api_key)
    instance_ids = {'tmdb_ids': [], 'tvdb_ids': []}

    logging.info(f"[{name}] Scanning {len(series_list)} shows...")

    for show in series_list:
        status = show.get('status', '').lower()
        monitored = show.get('monitored', False)

        if not monitored or status not in ['continuing', 'upcoming']:
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
            # This show has files, so it's a candidate for cleanup
            cleanup_real_media(plex_server, local_show_path, stub_suffix, tmdb_id, tvdb_id, title)
        else:
            # This show has NO files, so it's a candidate for the overlay
            if not tmdb_id and not tvdb_id:
                logging.warning(f"[{name}] Show '{title}' is missing both TMDb and TVDb IDs. Cannot process for overlay.")
                continue

            logging.info(f"[{name}] Processing: {title} (TMDb: {tmdb_id}, TVDb: {tvdb_id}) | Status: {status}")
            
            # 1. Create Stub File
            create_stub_file(local_show_path, title, template_file, stub_suffix)
            
            # 2. Process Plex Label & Watched Status
            if plex_server:
                process_plex_label(plex_server, tmdb_id, tvdb_id, title, stub_suffix)
            
            # 3. Add to correct list for YAML generation
            if tmdb_id:
                instance_ids['tmdb_ids'].append(tmdb_id)
            if tvdb_id:
                instance_ids['tvdb_ids'].append(tvdb_id)

    logging.info(f"[{name}] Finished. TMDb IDs: {len(instance_ids['tmdb_ids'])}, TVDb IDs: {len(instance_ids['tvdb_ids'])}")
    return instance_ids

def main():
    # 1. Basic Setup (Console)
    setup_logging('INFO')
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
    master_ids = {'tmdb_ids': [], 'tvdb_ids': []}

    for instance in sonarr_instances:
        logging.info(f"--- Starting Instance: {instance.get('name')} ---")
        instance_result = process_sonarr_instance(instance, plex_server, config_settings)
        master_ids['tmdb_ids'].extend(instance_result['tmdb_ids'])
        master_ids['tvdb_ids'].extend(instance_result['tvdb_ids'])
        logging.info(f"--- Instance {instance.get('name')} finished ---")

    # 6. Deduplicate
    unique_tmdb_ids = sorted(list(set(master_ids['tmdb_ids'])))
    unique_tvdb_ids = sorted(list(set(master_ids['tvdb_ids'])))
    logging.info(f"Total Unique TMDb IDs: {len(unique_tmdb_ids)}")
    logging.info(f"Total Unique TVDb IDs: {len(unique_tvdb_ids)}")

    # 7. Generate YAML
    if generate_overlay:
        if not overlay_output_path:
            logging.error("Overlay generation enabled, but 'returning_path' is missing in 'output:' config.")
        else:
            yaml_key = "returning_series"
            
            # Build the overlay content
            overlay_content = {
                "overlay": { "name": "Returning Series" } # Default name
            }

            if not unique_tmdb_ids and not unique_tvdb_ids:
                logging.info("No empty returning series found. Clearing overlay.")
                # Still create the file, but with empty lists
                overlay_content["tmdb_show"] = []
                overlay_content["tvdb_show"] = []
            else:
                logging.info(f"Generating Overlay for {len(unique_tmdb_ids)} TMDb shows and {len(unique_tvdb_ids)} TVDb shows...")
                
                final_overlay_style = merge_styles(global_defaults, overlay_override)
                final_overlay_style = validate_font(final_overlay_style)

                overlay_text = final_overlay_style.pop('text', 'RETURNING')
                overlay_name = f"text({overlay_text})"
                
                # Update overlay with the final calculated name and style
                overlay_content["overlay"]["name"] = overlay_name
                overlay_content["overlay"].update(final_overlay_style)

                overlay_content["tmdb_show"] = unique_tmdb_ids
                overlay_content["tvdb_show"] = unique_tvdb_ids
            
            kometa_data = {"overlays": {yaml_key: overlay_content}}

            try:
                os.makedirs(os.path.dirname(overlay_output_path), exist_ok=True)
                with open(overlay_output_path, 'w', encoding='utf-8') as f:
                    yaml.dump(kometa_data, f, sort_keys=False, indent=2, allow_unicode=True)
                logging.info(f"Successfully wrote config to: {overlay_output_path}")
            except Exception as e:
                logging.error(f"Failed to write YAML: {e}")

    logging.info("Returning Series Manager completed.")

if __name__ == "__main__":
    main()