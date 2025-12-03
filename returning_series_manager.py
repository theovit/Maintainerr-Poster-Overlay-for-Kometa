import os
import sys
import yaml
import requests
import logging

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
    config = load_config()
    
    # --- Load Config Sections ---
    connect_cfg = config.get('connect', {})
    returning_cfg = config.get('returning', {})
    output_cfg = config.get('output', {})
    global_defaults = config.get('global_defaults', {})
    
    # --- 1. Check Toggle (New) ---
    # Defaults to False if missing to avoid accidental overwrites
    if not returning_cfg.get('generate_overlay', False):
        # We use print here because logging might not be set up yet if we exit early
        print("Skipping Overlay Generation: 'generate_overlay' is False or missing in 'returning:' section.")
        sys.exit(0)

    # --- 2. Setup Logging ---
    log_level = returning_cfg.get('log_level', 'INFO')
    setup_logging(log_level)
    
    # --- 3. Check Output Path (New) ---
    output_path = output_cfg.get('returning_path')
    if not output_path:
        logging.critical("Missing 'returning_path' in the 'output:' section of config.yaml.")
        sys.exit(1)

    # --- 4. Load Sonarr Settings ---
    sonarr_url = connect_cfg.get('sonarr_url')
    sonarr_api_key = connect_cfg.get('sonarr_api_key')
    library_root = returning_cfg.get('library_root')
    stub_suffix = returning_cfg.get('stub_suffix', '- kometa-overlay-lock.mp4')
    overlay_override = returning_cfg.get('overlay_style', {})

    if not sonarr_url or not sonarr_api_key:
        logging.critical("Sonarr settings missing in connect config.")
        sys.exit(1)
        
    logging.info("--- Generating Kometa Overlay YAML ---")

    # --- 5. Identify Target Shows ---
    series_list = get_sonarr_series(sonarr_url, sonarr_api_key)
    tmdb_ids = []

    for show in series_list:
        title = show.get('title')
        status = show.get('status').lower()
        monitored = show.get('monitored')
        tmdb_id = show.get('tmdbId')
        path = show.get('path')
        
        # Must be monitored and (Continuing OR Upcoming)
        if not monitored or status not in ['continuing', 'upcoming']:
            continue
            
        folder_name = os.path.basename(path)
        show_path = os.path.join(library_root, folder_name)
        
        # If it has NO real media, we want to overlay it
        if not has_real_media(show_path, stub_suffix):
            logging.debug(f"Target identified: {title}")
            if tmdb_id:
                tmdb_ids.append(tmdb_id)

    if not tmdb_ids:
        logging.info("No returning series without media found. No file written.")
        sys.exit(0)

    # --- 6. Build the Overlay Style ---
    final_overlay_style = merge_styles(global_defaults, overlay_override)
    
    # --- 7. Construct Kometa YAML ---
    kometa_data = {
        "overlays": {
            "Returning Series": {
                "overlay": {
                    "name": "Returning Series",
                    **final_overlay_style
                },
                "plex_search": {
                    "all": {
                        "tmdb_id": tmdb_ids
                    }
                }
            }
        }
    }

    # --- 8. Write to Configured Output Path ---
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            yaml.dump(kometa_data, f, sort_keys=False)
        logging.info(f"Successfully wrote Kometa config to: {output_path}")
    except Exception as e:
        logging.error(f"Failed to write YAML file: {e}")

if __name__ == "__main__":
    main()