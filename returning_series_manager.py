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

def load_config():
    """Loads the YAML configuration file."""
    try:
        with open(DEFAULT_CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"CRITICAL: {DEFAULT_CONFIG_PATH} not found.")
        sys.exit(1)

def setup_logging(level_str):
    """Sets up logging to console."""
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        format='%(asctime)s - %(levelname)s - %(message)s',
        level=level,
        handlers=[logging.StreamHandler()]
    )

def get_sonarr_headers(api_key):
    return {
        "X-Api-Key": api_key,
        "Content-Type": "application/json"
    }

def get_sonarr_series(base_url, api_key):
    """Fetches all series from Sonarr."""
    try:
        url = f"{base_url.rstrip('/')}/api/v3/series"
        logging.info(f"Connecting to Sonarr at {url}")
        response = requests.get(url, headers=get_sonarr_headers(api_key))
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error connecting to Sonarr: {e}")
        sys.exit(1)

def has_real_media(show_path, stub_suffix):
    """
    Checks if a folder contains any real video files 
    (excluding the Kometa stub file).
    """
    if not os.path.exists(show_path):
        return False
        
    for root, dirs, files in os.walk(show_path):
        for file in files:
            if file.lower().endswith(VIDEO_EXTENSIONS):
                if not file.endswith(stub_suffix):
                    return True
    return False

def create_stub_file(show_path, show_title, template_file, stub_suffix):
    """
    Creates a stub video file in the show folder if it doesn't exist.
    """
    # Sanitize title for filename
    safe_title = "".join([c for c in show_title if c.isalpha() or c.isdigit() or c in ' .-_']).strip()
    stub_filename = f"{safe_title}{stub_suffix}"
    stub_path = os.path.join(show_path, stub_filename)

    if os.path.exists(stub_path):
        logging.debug(f"  > Stub already exists: {stub_filename}")
        return True

    # Create folder if missing
    if not os.path.exists(show_path):
        try:
            os.makedirs(show_path)
            logging.info(f"  > Created missing folder: {show_path}")
        except OSError as e:
            logging.error(f"  > Failed to create folder: {e}")
            return False

    # Copy template or create empty file
    try:
        if template_file and os.path.exists(template_file):
            shutil.copy(template_file, stub_path)
            logging.info(f"  > Stub created (from template): {stub_path}")
        else:
            with open(stub_path, 'wb') as f:
                f.write(b'\0' * 1024) # Write 1KB of null bytes
            logging.warning(f"  > Stub created (empty file - no template found): {stub_path}")
        return True
    except Exception as e:
        logging.error(f"  > Failed to create stub file: {e}")
        return False

def merge_styles(global_defaults, specific_style):
    """
    Merges global defaults with specific overrides.
    Only overrides if the specific value is NOT None (~).
    """
    if not specific_style:
        return global_defaults.copy()

    final_style = global_defaults.copy()
    for key, value in specific_style.items():
        if value is not None:
            final_style[key] = value
    return final_style

def main():
    logging.info("Starting Returning Series Manager...")
    config = load_config()
    
    # --- Load Configuration ---
    connect_cfg = config.get('connect', {})
    returning_cfg = config.get('returning', {})
    output_cfg = config.get('output', {})
    global_defaults = config.get('global_defaults', {})

    sonarr_url = connect_cfg.get('sonarr_url')
    sonarr_api_key = connect_cfg.get('sonarr_api_key')
    library_root = returning_cfg.get('library_root')
    template_file = returning_cfg.get('template_file')
    stub_suffix = returning_cfg.get('stub_suffix', '- kometa-overlay-lock.mp4')
    log_level = returning_cfg.get('log_level', 'INFO')
    
    # Overlay Generation Settings
    generate_overlay = returning_cfg.get('generate_overlay', False)
    overlay_output_path = output_cfg.get('returning_path')
    overlay_override = returning_cfg.get('overlay_style', {})

    setup_logging(log_level)

    if not sonarr_url or not sonarr_api_key or not library_root:
        logging.critical("Missing required Sonarr or Library settings in config.yaml.")
        sys.exit(1)

    # --- 1. Scan and Manage Stubs ---
    series_list = get_sonarr_series(sonarr_url, sonarr_api_key)
    
    # List to store TMDb IDs for the overlay file
    tmdb_ids_for_overlay = []

    for show in series_list:
        title = show.get('title')
        status = show.get('status').lower()
        monitored = show.get('monitored')
        tmdb_id = show.get('tmdbId')
        path = show.get('path')

        # Criteria: Monitored AND (Continuing OR Upcoming)
        if not monitored or status not in ['continuing', 'upcoming']:
            continue

        folder_name = os.path.basename(path)
        show_path = os.path.join(library_root, folder_name)

        # Check if the show has NO real media (only stubs or empty)
        if not has_real_media(show_path, stub_suffix):
            logging.info(f"Processing: {title} (TMDb: {tmdb_id}) | Status: {status}")
            
            # Action A: Create/Verify Stub
            create_stub_file(show_path, title, template_file, stub_suffix)
            
            # Action B: Add to list for Overlay Generation
            if tmdb_id:
                tmdb_ids_for_overlay.append(tmdb_id)

    # --- 2. Generate Overlay YAML (If Enabled) ---
    if generate_overlay:
        if not overlay_output_path:
            logging.error("Overlay generation enabled, but 'returning_path' is missing in output config.")
        elif not tmdb_ids_for_overlay:
            logging.info("No empty returning series found. Clearing overlay file.")
            # We explicitly write an empty/disabled file or just empty the list to clear old overlays
            # Writing an empty list to 'plex_search' effectively removes the overlays
            kometa_data = {
                 "overlays": {
                    "Returning Series": {
                        "overlay": { "name": "Returning Series" }, # Minimal valid structure
                        "plex_search": { "all": { "tmdb_id": [] } }
                    }
                }
            }
            with open(overlay_output_path, 'w') as f:
                yaml.dump(kometa_data, f, sort_keys=False)

        else:
            logging.info(f"Generating Overlay YAML for {len(tmdb_ids_for_overlay)} series...")
            
            # Merge Styles
            final_overlay_style = merge_styles(global_defaults, overlay_override)
            
            kometa_data = {
                "overlays": {
                    "Returning Series": {
                        "overlay": {
                            "name": "Returning Series",
                            **final_overlay_style
                        },
                        "plex_search": {
                            "all": {
                                "tmdb_id": tmdb_ids_for_overlay
                            }
                        }
                    }
                }
            }

            try:
                os.makedirs(os.path.dirname(overlay_output_path), exist_ok=True)
                with open(overlay_output_path, 'w') as f:
                    yaml.dump(kometa_data, f, sort_keys=False)
                logging.info(f"Successfully wrote Kometa config to: {overlay_output_path}")
            except Exception as e:
                logging.error(f"Failed to write YAML file: {e}")

    else:
        logging.info("Overlay generation is disabled in config (returning.generate_overlay).")

    logging.info("Returning Series Manager completed.")

if __name__ == "__main__":
    main()