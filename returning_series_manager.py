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

def setup_logging(level_str):
    """Sets up logging to console (stdout) to ensure terminal visibility."""
    level = getattr(logging, level_str.upper(), logging.INFO)
    
    # Clear any existing handlers to prevent duplicates or silent swallowing
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.handlers = []

    logging.basicConfig(
        format='%(asctime)s - %(levelname)s - %(message)s',
        level=level,
        handlers=[logging.StreamHandler(sys.stdout)]  # Explicitly use stdout
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

def process_plex_label(plex, tmdb_id, title):
    """
    Finds the show in Plex by TMDb ID or Title and adds the lock label.
    """
    if not plex:
        return

    found_show = None
    
    try:
        # Use mediatype='show' for proper Plex searching
        results = plex.search(title, mediatype='show')
        
        for item in results:
            # Check GUIDs (e.g. tmdb://12345)
            matches = [g.id for g in item.guids] if hasattr(item, 'guids') else []
            matches.append(item.guid)
            
            # Look for tmdb://{id}
            if any(f"tmdb://{tmdb_id}" in g for g in matches):
                found_show = item
                break
        
        if found_show:
            current_labels = [l.tag for l in found_show.labels]
            if PLEX_LABEL_NAME not in current_labels:
                logging.info(f"  > Plex: Adding label '{PLEX_LABEL_NAME}' to '{found_show.title}'")
                found_show.addLabel(PLEX_LABEL_NAME)
            else:
                logging.debug(f"  > Plex: Label '{PLEX_LABEL_NAME}' already present.")
        else:
            # Only warn if we really expected to find it (meaning the stub exists)
            logging.warning(f"  > Plex: Could not find show '{title}' (TMDb: {tmdb_id}) to label. Ensure library is scanned.")

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
    """
    Checks if the font file exists. If not, removes it from the style
    to prevent Kometa crashing or falling back to image mode.
    """
    font_path = style_dict.get('font')
    if font_path:
        # Check absolute path or relative to current dir
        if os.path.exists(font_path):
            return style_dict
        
        # Check if it exists inside the 'config' folder if path started with 'config/'
        if not os.path.exists(font_path):
            logging.warning(f"  [WARN] Font file not found at: {font_path}")
            logging.warning("  [WARN] Removing font setting to use Kometa default.")
            del style_dict['font']
            
    return style_dict

def main():
    # Setup logging first with default INFO
    setup_logging('INFO')
    
    logging.info("Starting Returning Series Manager...")
    config = load_config()
    
    # --- Load Configuration ---
    connect_cfg = config.get('connect', {})
    returning_cfg = config.get('returning', {})
    output_cfg = config.get('output', {})
    global_defaults = config.get('global_defaults', {})

    sonarr_url = connect_cfg.get('sonarr_url')
    sonarr_api_key = connect_cfg.get('sonarr_api_key')
    
    # Plex Settings
    plex_url = connect_cfg.get('plex_url')
    plex_token = connect_cfg.get('plex_token')
    
    library_root = returning_cfg.get('library_root')
    template_file = returning_cfg.get('template_file')
    stub_suffix = returning_cfg.get('stub_suffix', '- kometa-overlay-lock.mp4')
    log_level = returning_cfg.get('log_level', 'INFO')
    
    generate_overlay = returning_cfg.get('generate_overlay', False)
    overlay_output_path = output_cfg.get('returning_path')
    overlay_override = returning_cfg.get('overlay_style', {})

    # Re-setup logging with configured level
    setup_logging(log_level)

    if not sonarr_url or not sonarr_api_key or not library_root:
        logging.critical("Missing required Sonarr or Library settings in config.yaml.")
        sys.exit(1)

    # --- Initialize Plex ---
    plex_server = None
    if plex_url and plex_token:
        if PLEX_AVAILABLE:
            try:
                plex_server = PlexServer(plex_url, plex_token)
                logging.info(f"Connected to Plex: {plex_server.friendlyName}")
            except Exception as e:
                logging.error(f"Failed to connect to Plex: {e}")
        else:
            logging.warning("plexapi library not installed. Skipping Plex labeling.")
    else:
        logging.warning("Plex URL/Token not found in config. Skipping Plex labeling.")

    # --- 1. Scan and Manage Stubs ---
    series_list = get_sonarr_series(sonarr_url, sonarr_api_key)
    tmdb_ids_for_overlay = []

    for show in series_list:
        title = show.get('title')
        status = show.get('status').lower()
        monitored = show.get('monitored')
        tmdb_id = show.get('tmdbId')
        path = show.get('path')

        if not monitored or status not in ['continuing', 'upcoming']:
            continue

        folder_name = os.path.basename(path)
        show_path = os.path.join(library_root, folder_name)

        if not has_real_media(show_path, stub_suffix):
            logging.info(f"Processing: {title} (TMDb: {tmdb_id}) | Status: {status}")
            
            # Action A: Create/Verify Stub
            create_stub_file(show_path, title, template_file, stub_suffix)
            
            # Action B: Label in Plex (If available)
            if plex_server and tmdb_id:
                process_plex_label(plex_server, tmdb_id, title)
            
            # Action C: Add to list for Overlay Generation
            if tmdb_id:
                tmdb_ids_for_overlay.append(tmdb_id)

    # --- 2. Generate Overlay YAML (If Enabled) ---
    if generate_overlay:
        if not overlay_output_path:
            logging.error("Overlay generation enabled, but 'returning_path' is missing in output config.")
        else:
            # Check if list is empty
            if not tmdb_ids_for_overlay:
                logging.info("No empty returning series found. Clearing overlay configuration.")
                # Clear content
                kometa_data = {
                    "overlays": {
                        "returning_series": {
                            "overlay": { "name": "Returning Series" },
                            "tmdb_show": [] 
                        }
                    }
                }
            else:
                logging.info(f"Generating Overlay YAML for {len(tmdb_ids_for_overlay)} series using 'tmdb_show'...")

                # Merge Styles
                final_overlay_style = merge_styles(global_defaults, overlay_override)
                
                # --- VALIDATE FONT ---
                final_overlay_style = validate_font(final_overlay_style)

                # --- FIX: USE 'text(...)' NAME FORMAT ---
                # Extract text or use default
                overlay_text = final_overlay_style.pop('text', 'RETURNING')
                # Format name as text(CONTENT) so Kometa detects Text Overlay mode
                overlay_name = f"text({overlay_text})"
                
                logging.debug(f"Generated Overlay Name: {overlay_name}")

                kometa_data = {
                    "overlays": {
                        "returning_series": {
                            "overlay": {
                                "name": overlay_name,
                                **final_overlay_style
                            },
                            "tmdb_show": tmdb_ids_for_overlay
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