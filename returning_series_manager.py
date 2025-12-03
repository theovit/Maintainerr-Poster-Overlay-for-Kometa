import os
import shutil
import requests
import yaml
import re
import sys
import logging
import subprocess

# Global constant for video extensions to check against
VIDEO_EXTENSIONS = ('.mkv', '.mp4', '.avi', '.m4v', '.mov', '.wmv')

def load_config():
    """
    Loads the YAML configuration file.
    Exits the script if the file is missing.
    """
    try:
        with open('config.yaml', 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print("CRITICAL: config.yaml not found. Please create it.")
        sys.exit(1)

def setup_logging(level_str):
    """
    Sets up logging to both the console (stdout) and a file (returning_series_manager.log).
    """
    level = getattr(logging, level_str.upper(), logging.INFO)
    logger = logging.getLogger()
    logger.setLevel(level)
    
    # Clear existing handlers to prevent duplicates if function is called twice
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    file_handler = logging.FileHandler('returning_series_manager.log', mode='w')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logging.debug(f"Logging initialized at level: {level_str}")

def get_sonarr_headers(api_key):
    return {
        "X-Api-Key": api_key,
        "Content-Type": "application/json"
    }

def get_tag_id(base_url, api_key, tag_label):
    """
    Fetches the numeric ID for a specific tag text label.
    Returns None if tag is not found.
    """
    if not tag_label:
        return None
    
    try:
        url = f"{base_url.rstrip('/')}/api/v3/tag"
        response = requests.get(url, headers=get_sonarr_headers(api_key))
        response.raise_for_status()
        tags = response.json()
        
        for tag in tags:
            if tag['label'].lower() == tag_label.lower():
                return tag['id']
        
        logging.warning(f"Tag '{tag_label}' configured but NOT found in Sonarr. Ignoring tag filter.")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching tags: {e}")
        return None

def get_sonarr_series(base_url, api_key):
    try:
        url = f"{base_url.rstrip('/')}/api/v3/series"
        response = requests.get(url, headers=get_sonarr_headers(api_key))
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error connecting to Sonarr: {e}")
        sys.exit(1)

def create_plexmatch(show_path, tmdb_id, title, year):
    plexmatch_path = os.path.join(show_path, ".plexmatch")
    content = f"Title: {title}\nYear: {year}\ntmdbid: {tmdb_id}\n"
    
    if not os.path.exists(plexmatch_path):
        try:
            with open(plexmatch_path, 'w') as f:
                f.write(content)
            logging.info(f"   [+] Created .plexmatch for '{title}'")
        except Exception as e:
            logging.error(f"Failed to write plexmatch: {e}")

def generate_blank_video(filepath):
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logging.error("FFMPEG not found. Cannot generate stub.")
        return False

    command = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "color=c=black:s=640x480:d=1",
        "-c:v", "libx264", "-tune", "stillimage",
        "-pix_fmt", "yuv420p", "-shortest", filepath
    ]
    
    try:
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        logging.info(f"   [+] Created stub (FFMPEG): {os.path.basename(filepath)}")
        return True
    except subprocess.CalledProcessError:
        return False

def has_real_media(show_path, stub_suffix):
    if not os.path.exists(show_path):
        return False
        
    for root, dirs, files in os.walk(show_path):
        for file in files:
            if file.lower().endswith(VIDEO_EXTENSIONS):
                if not file.endswith(stub_suffix):
                    return True
    return False

def clean_stubs(show_path, stub_suffix, clean_plexmatch=False):
    if not os.path.exists(show_path):
        return

    for root, dirs, files in os.walk(show_path):
        for file in files:
            if file.endswith(stub_suffix):
                try:
                    os.remove(os.path.join(root, file))
                    logging.info(f"   [-] Removed stub: {file}")
                except OSError:
                    pass

    if clean_plexmatch:
        pm_path = os.path.join(show_path, ".plexmatch")
        if os.path.exists(pm_path):
            try:
                os.remove(pm_path)
                logging.info(f"   [-] Removed .plexmatch")
            except OSError:
                pass

def process_shows():
    config = load_config()
    
    # Load settings
    connect_cfg = config.get('connect', {})
    returning_cfg = config.get('returning', {})

    sonarr_url = connect_cfg.get('sonarr_url')
    sonarr_api_key = connect_cfg.get('sonarr_api_key')
    
    log_level = returning_cfg.get('log_level', 'INFO')
    target_tag_label = returning_cfg.get('sonarr_tag')
    library_root = returning_cfg.get('library_root')
    template_file = returning_cfg.get('template_file')
    stub_suffix = returning_cfg.get('stub_suffix', '- kometa-overlay-lock.mp4')
    
    setup_logging(log_level)

    if not sonarr_url or not sonarr_api_key:
        logging.critical("Sonarr URL or API Key missing.")
        sys.exit(1)

    logging.info("--- Starting Returning Series Manager ---")

    # Resolve Tag ID (Optional)
    target_tag_id = None
    if target_tag_label:
        target_tag_id = get_tag_id(sonarr_url, sonarr_api_key, target_tag_label)
        if target_tag_id:
            logging.info(f"Filtering active. Tag: '{target_tag_label}' (ID: {target_tag_id})")
        else:
            # If tag lookup failed, we just log it and proceed without filtering by tag
            logging.info("Tag not configured or not found. Processing based on Status only.")

    series_list = get_sonarr_series(sonarr_url, sonarr_api_key)

    for show in series_list:
        title = show.get('title')
        status = show.get('status').lower() # 'continuing', 'ended', 'upcoming'
        monitored = show.get('monitored')
        tags = show.get('tags', [])
        tmdb_id = show.get('tmdbId')
        year = show.get('year')
        
        folder_name = os.path.basename(show.get('path'))
        
        if not library_root:
             logging.critical("library_root is missing in config.")
             sys.exit(1)

        show_path = os.path.join(library_root, folder_name)

        # FILTER 1: Tag (If configured and found)
        # Only filter if we successfully resolved a tag ID.
        if target_tag_id and target_tag_id not in tags:
            continue

        # FILTER 2: Monitored Status
        # Standard "Continuing" logic implies the show is monitored in Sonarr.
        if not monitored:
            # If show is unmonitored but ended, ensure cleanup
            if status == "ended":
                clean_stubs(show_path, stub_suffix, clean_plexmatch=True)
            continue

        # FILTER 3: Status Check
        if status == "ended":
            # Show ended -> Clean up any stubs
            clean_stubs(show_path, stub_suffix, clean_plexmatch=True)
            continue
            
        elif status == "continuing" or status == "upcoming":
            # Show is active -> Check for media
            if not os.path.exists(show_path):
                logging.warning(f"   [!] Folder missing: {show_path}")
                continue

            if has_real_media(show_path, stub_suffix):
                # Real media exists -> Clean stubs
                clean_stubs(show_path, stub_suffix, clean_plexmatch=False)
            else:
                # No media -> Create stub
                logging.info(f"Processing: {title} ({status})")
                
                season_path = os.path.join(show_path, "Specials")
                if not os.path.exists(season_path):
                    os.makedirs(season_path)

                clean_title = re.sub(r'[\\/*?:"<>|]', "", title)
                stub_name = f"{clean_title} - S00E99{stub_suffix}"
                stub_path = os.path.join(season_path, stub_name)

                if not os.path.exists(stub_path):
                    if template_file and os.path.exists(template_file):
                        shutil.copy(template_file, stub_path)
                        logging.info(f"   [+] Created stub (Template): {stub_name}")
                    else:
                        if generate_blank_video(stub_path):
                             logging.info(f"   [+] Created stub (FFMPEG): {stub_name}")
                        else:
                             logging.error(f"   [X] Failed: {title}")
                        
                    if tmdb_id:
                        create_plexmatch(show_path, tmdb_id, title, year)

    logging.info("--- Run Complete ---")

if __name__ == "__main__":
    process_shows()