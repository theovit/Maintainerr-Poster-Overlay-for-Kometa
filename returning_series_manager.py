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
    """Returns True if any video file (other than stub) exists."""
    if not os.path.exists(show_path):
        return False
    for root, dirs, files in os.walk(show_path):
        for file in files:
            if file.lower().endswith(VIDEO_EXTENSIONS):
                if not file.endswith(stub_suffix):
                    return True
    return False

def create_stub_file(show_path, show_title, template_file, stub_suffix):
    """Creates the dummy file if missing."""
    safe_title = "".join([c for c in show_title if c.isalpha() or c.isdigit() or c in ' .-_']).strip()
    stub_filename = f"{safe_title}{stub_suffix}"
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

def process_plex_label(plex, tmdb_id, title, stub_suffix):
    """Labels show in Plex and marks stub episode as watched."""
    if not plex:
        return
    try:
        results = plex.search(title, mediatype='show')
        found_show = None
        for item in results:
            matches = [g.id for g in item.guids] if hasattr(item, 'guids') else []
            matches.append(item.guid)
            if any(f"tmdb://{tmdb_id}" in g for g in matches):
                found_show = item
                break
        
        if found_show:
            # Label
            current_labels = [l.tag for l in found_show.labels]
            if PLEX_LABEL_NAME not in current_labels:
                logging.info(f"  > Plex: Adding label '{PLEX_LABEL_NAME}' to '{found_show.title}'")
                found_show.addLabel(PLEX_LABEL_NAME)

            # Mark Stub Watched
            found_stub = False
            for episode in found_show.episodes():
                is_this_stub = False
                for media in episode.media:
                    for part in media.parts:
                        if part.file and part.file.endswith(stub_suffix):
                            is_this_stub = True
                            break
                    if is_this_stub: break
                
                if is_this_stub:
                    found_stub = True
                    if not episode.isWatched:
                        logging.info(f"  > Plex: Marking stub episode '{episode.title}' (S{episode.parentIndex}E{episode.index}) as watched.")
                        episode.markWatched()
                    break
            
            if not found_stub:
                logging.debug("  > Plex: Stub file not found in Plex yet.")
        else:
            logging.warning(f"  > Plex: Could not find show '{title}' (TMDb: {tmdb_id}).")
    except Exception as e:
        logging.error(f"  > Plex Error: {e}")

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
    Processes a single Sonarr instance. Returns list of TMDb IDs.
    """
    name = instance.get('name', 'Unknown')
    url = instance.get('url')
    api_key = instance.get('api_key')
    library_path = instance.get('library_path')

    if not url or not api_key or not library_path:
        logging.error(f"[{name}] Skipping: Missing settings.")
        return []

    ensure_sonarr_settings(name, url, api_key)

    template_file = config_settings['template_file']
    stub_suffix = config_settings['stub_suffix']

    series_list = get_sonarr_series(name, url, api_key)
    instance_tmdb_ids = []

    logging.info(f"[{name}] Scanning {len(series_list)} shows...")

    for show in series_list:
        title = show.get('title')
        status = show.get('status').lower()
        monitored = show.get('monitored')
        tmdb_id = show.get('tmdbId')
        sonarr_path = show.get('path', '')

        # --- SIMPLIFIED PATH LOGIC ---
        # 1. Take ONLY the folder name from Sonarr
        folder_name = os.path.basename(os.path.normpath(sonarr_path))
        # 2. Append it to our local library path
        show_path = os.path.join(library_path, folder_name)

        if not monitored or status not in ['continuing', 'upcoming']:
            continue

        if not has_real_media(show_path, stub_suffix):
            logging.info(f"[{name}] Processing: {title} (TMDb: {tmdb_id}) | Status: {status}")
            
            # 1. Stub
            create_stub_file(show_path, title, template_file, stub_suffix)
            
            # 2. Plex
            if plex_server and tmdb_id:
                process_plex_label(plex_server, tmdb_id, title, stub_suffix)
            
            # 3. Add to List
            if tmdb_id:
                instance_tmdb_ids.append(tmdb_id)
                # DEBUG: Force this to print
                logging.info(f"[{name}] + ADDED ID {tmdb_id} to internal list. Count is now: {len(instance_tmdb_ids)}")
            else:
                logging.warning(f"[{name}] WARNING: Show '{title}' has no TMDb ID!")

    logging.info(f"[{name}] Finished. IDs collected: {len(instance_tmdb_ids)}")
    return instance_tmdb_ids

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
    plex_url = plex_cfg.get('url')
    plex_token = plex_cfg.get('token')

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
    master_tmdb_ids = []

    for instance in sonarr_instances:
        logging.info(f"--- Starting Instance: {instance.get('name')} ---")
        ids = process_sonarr_instance(instance, plex_server, config_settings)
        logging.info(f"--- Instance {instance.get('name')} returned {len(ids)} IDs ---")
        master_tmdb_ids.extend(ids)

    # 6. Deduplicate
    master_tmdb_ids = list(set(master_tmdb_ids))
    logging.info(f"Total Unique Returning Series found (All Instances): {len(master_tmdb_ids)}")

    # 7. Generate YAML
    if generate_overlay:
        if not overlay_output_path:
            logging.error("Overlay generation enabled, but 'returning_path' is missing in 'output:' config.")
        else:
            yaml_key = "returning_series" 
            
            if not master_tmdb_ids:
                logging.info("No empty returning series found. Clearing overlay.")
                kometa_data = { "overlays": { yaml_key: { "overlay": { "name": "Returning Series" }, "tmdb_show": [] } } }
            else:
                logging.info(f"Generating Overlay for {len(master_tmdb_ids)} series...")
                
                final_overlay_style = merge_styles(global_defaults, overlay_override)
                final_overlay_style = validate_font(final_overlay_style)

                overlay_text = final_overlay_style.pop('text', 'RETURNING')
                overlay_name = f"text({overlay_text})"
                
                kometa_data = {
                    "overlays": {
                        yaml_key: {
                            "overlay": {
                                "name": overlay_name,
                                **final_overlay_style
                            },
                            "tmdb_show": master_tmdb_ids
                        }
                    }
                }

            try:
                os.makedirs(os.path.dirname(overlay_output_path), exist_ok=True)
                with open(overlay_output_path, 'w') as f:
                    yaml.dump(kometa_data, f, sort_keys=False)
                logging.info(f"Successfully wrote config to: {overlay_output_path}")
            except Exception as e:
                logging.error(f"Failed to write YAML: {e}")

    logging.info("Returning Series Manager completed.")

if __name__ == "__main__":
    main()