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
    # Convert string level (e.g., "DEBUG") to logging constant
    level = getattr(logging, level_str.upper(), logging.INFO)

    # Create a logger
    logger = logging.getLogger()
    logger.setLevel(level)

    # Create formatters
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # Handler 1: File (saves logs to returning_series_manager.log)
    file_handler = logging.FileHandler('returning_series_manager.log', mode='w') # 'w' overwrites each run, use 'a' to append
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Handler 2: Console (prints to screen)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logging.debug(f"Logging initialized at level: {level_str}")

def get_sonarr_headers(api_key):
    """Returns the standard headers required for Sonarr API calls."""
    return {
        "X-Api-Key": api_key,
        "Content-Type": "application/json"
    }

def get_tag_id(base_url, api_key, tag_label):
    """
    Fetches the numeric ID for a specific tag text label (e.g., "stub" -> 4).
    Returns -1 if tag is not found.
    """
    if not tag_label:
        return None
    
    try:
        url = f"{base_url.rstrip('/')}/api/v3/tag"
        logging.debug(f"Fetching tags from: {url}")
        
        response = requests.get(url, headers=get_sonarr_headers(api_key))
        response.raise_for_status()
        tags = response.json()
        
        for tag in tags:
            if tag['label'].lower() == tag_label.lower():
                logging.debug(f"Found Tag ID: {tag['id']} for label '{tag_label}'")
                return tag['id']
        
        logging.warning(f"Tag '{tag_label}' not found in Sonarr.")
        return -1
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching tags: {e}")
        sys.exit(1)

def get_sonarr_series(base_url, api_key):
    """
    Retrieves the entire library of series from Sonarr.
    """
    try:
        url = f"{base_url.rstrip('/')}/api/v3/series"
        logging.debug(f"Fetching series list from: {url}")
        
        response = requests.get(url, headers=get_sonarr_headers(api_key))
        response.raise_for_status()
        series = response.json()
        logging.info(f"Successfully fetched {len(series)} shows from Sonarr.")
        return series
    except requests.exceptions.RequestException as e:
        logging.error(f"Error connecting to Sonarr: {e}")
        sys.exit(1)

def create_plexmatch(show_path, tmdb_id, title, year):
    """
    Creates a .plexmatch file inside the show folder.
    This file forces Plex to use the specific TMDB ID for metadata, 
    which is crucial when the folder is empty or contains only dummy files.
    """
    plexmatch_path = os.path.join(show_path, ".plexmatch")
    content = f"Title: {title}\nYear: {year}\ntmdbid: {tmdb_id}\n"
    
    # Only write if file doesn't exist to save I/O
    if not os.path.exists(plexmatch_path):
        try:
            with open(plexmatch_path, 'w') as f:
                f.write(content)
            logging.info(f"   [+] Created .plexmatch for '{title}' (TMDB: {tmdb_id})")
        except Exception as e:
            logging.error(f"Failed to write plexmatch at {plexmatch_path}: {e}")

def generate_blank_video(filepath):
    """
    Uses FFMPEG to create a 1-second black video file if the template is missing.
    Returns True if successful, False otherwise.
    """
    # Check if ffmpeg is installed
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logging.error("FFMPEG not found in system path. Cannot generate stub video.")
        return False

    # FFMPEG command to generate 1 second of black video
    command = [
        "ffmpeg",
        "-y", # Overwrite existing
        "-f", "lavfi",
        "-i", "color=c=black:s=640x480:d=1", # Source: Black color, 1 sec duration
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-pix_fmt", "yuv420p",
        "-shortest",
        filepath
    ]
    
    try:
        logging.debug(f"Running FFMPEG generation for: {filepath}")
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        logging.info(f"   [+] Generated FFMPEG stub: {os.path.basename(filepath)}")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"FFMPEG generation failed: {e}")
        return False

def has_real_media(show_path, stub_suffix):
    """
    Scans the directory recursively.
    Returns True if it finds ANY video file that is NOT a stub.
    Returns False if the directory is empty or only contains stubs.
    """
    if not os.path.exists(show_path):
        return False
        
    for root, dirs, files in os.walk(show_path):
        for file in files:
            # Check if file is a video
            if file.lower().endswith(VIDEO_EXTENSIONS):
                # If the file does NOT end with our custom suffix, it's real media
                if not file.endswith(stub_suffix):
                    logging.debug(f"   [!] Found real media: {file}")
                    return True
    return False

def clean_stubs(show_path, stub_suffix, clean_plexmatch=False):
    """
    Removes any files in the directory that match the stub suffix.
    Optionally removes the .plexmatch file as well.
    """
    if not os.path.exists(show_path):
        return

    # Walk through folders and delete stubs
    for root, dirs, files in os.walk(show_path):
        for file in files:
            if file.endswith(stub_suffix):
                full_path = os.path.join(root, file)
                try:
                    os.remove(full_path)
                    logging.info(f"   [-] Removed stub: {file}")
                except OSError as e:
                    logging.error(f"Error deleting stub {file}: {e}")

    # Remove .plexmatch if requested (usually done when show ends)
    if clean_plexmatch:
        pm_path = os.path.join(show_path, ".plexmatch")
        if os.path.exists(pm_path):
            try:
                os.remove(pm_path)
                logging.info(f"   [-] Removed .plexmatch")
            except OSError:
                pass

def process_shows():
    """
    Main logic loop:
    1. Load config
    2. Get Sonarr Data
    3. Iterate through shows
    4. Apply logic based on Show Status and Real Media existence
    """
    config = load_config()
    
    # --- CHANGED: Load nested configurations ---
    connect_cfg = config.get('connect', {})
    returning_cfg = config.get('returning', {})

    # Pull variables from specific blocks
    sonarr_url = connect_cfg.get('sonarr_url')
    sonarr_api_key = connect_cfg.get('sonarr_api_key')
    
    # Pull returning variables from the 'returning' block
    log_level = returning_cfg.get('log_level', 'INFO')
    target_tag_label = returning_cfg.get('sonarr_tag')
    library_root = returning_cfg.get('library_root')
    template_file = returning_cfg.get('template_file')
    stub_suffix = returning_cfg.get('stub_suffix', '- kometa-overlay-lock.mp4')
    
    # Initialize Logging based on config
    setup_logging(log_level)

    # Basic validation
    if not sonarr_url or not sonarr_api_key:
        logging.critical("Sonarr URL or API Key missing in 'connect' block.")
        sys.exit(1)

    logging.info("--- Starting Returning Series Manager ---")

    # --- Step 1: Resolve Tag ID ---
    target_tag_id = None
    if target_tag_label:
        target_tag_id = get_tag_id(sonarr_url, sonarr_api_key, target_tag_label)
        if target_tag_id == -1:
            logging.critical("Tag lookup failed. Aborting to prevent library damage.")
            sys.exit(1)
        logging.info(f"Filtering mode active. Processing ONLY shows with tag: '{target_tag_label}' (ID: {target_tag_id})")

    # --- Step 2: Fetch Library ---
    series_list = get_sonarr_series(sonarr_url, sonarr_api_key)

    # --- Step 3: Process Each Show ---
    for show in series_list:
        title = show.get('title')
        status = show.get('status') # 'continuing', 'ended', 'upcoming'
        tags = show.get('tags', [])
        tmdb_id = show.get('tmdbId')
        year = show.get('year')
        
        # Determine the local file system path for this show
        # We rely on Sonarr's folder naming
        folder_name = os.path.basename(show.get('path'))
        
        # Check if library_root is defined
        if not library_root:
             logging.critical("library_root is missing in config 'returning' block.")
             sys.exit(1)

        show_path = os.path.join(library_root, folder_name)

        # CHECK: Does the show have the required tag?
        if target_tag_id is not None and target_tag_id not in tags:
            # Tag missing, skip silently (or debug log)
            # logging.debug(f"Skipping {title} (Tag mismatch)")
            continue

        logging.info(f"Processing: {title} | Status: {status}")

        # CHECK: Does the folder exist locally?
        if not os.path.exists(show_path):
            logging.warning(f"   [!] Folder missing at: {show_path}. Ensure Sonarr has created the empty folder.")
            continue

        # CHECK: Does the folder have real media?
        real_media_exists = has_real_media(show_path, stub_suffix)

        # --- SCENARIO A: Show has Ended ---
        # Logic: We don't need dummy files for ended shows. Clean up.
        if status.lower() == "ended":
            clean_stubs(show_path, stub_suffix, clean_plexmatch=True)
            continue

        # --- SCENARIO B: Show is Active (Continuing or Upcoming) ---
        if status.lower() in ["continuing", "upcoming"]:
            
            # Sub-scenario: User has downloaded real episodes
            if real_media_exists:
                logging.info(f"   [>] Real media detected. Ensuring stubs are removed.")
                clean_stubs(show_path, stub_suffix, clean_plexmatch=False)
            
            # Sub-scenario: No real episodes found. We need a stub.
            else:
                # 1. Create 'Specials' folder (Season 00)
                season_path = os.path.join(show_path, "Specials")
                if not os.path.exists(season_path):
                    os.makedirs(season_path)
                    logging.debug(f"   [+] Created Specials folder")

                # 2. Construct the stub filename
                clean_title = re.sub(r'[\\/*?:"<>|]', "", title)
                stub_name = f"{clean_title} - S00E99{stub_suffix}"
                stub_path = os.path.join(season_path, stub_name)

                # 3. Create the file if it doesn't exist
                if not os.path.exists(stub_path):
                    # Try copying template first
                    if template_file and os.path.exists(template_file):
                        shutil.copy(template_file, stub_path)
                        logging.info(f"   [+] Created stub (from template): {stub_name}")
                    # Fallback to FFMPEG generation
                    else:
                        logging.warning(f"   [!] Template not found or not configured. Attempting FFMPEG...")
                        if generate_blank_video(stub_path):
                             logging.info(f"   [+] Created stub (FFMPEG): {stub_name}")
                        else:
                             logging.error(f"   [X] Failed to create stub for {title}")
                        
                    # 4. Ensure .plexmatch exists so Plex identifies the empty show correctly
                    if tmdb_id:
                        create_plexmatch(show_path, tmdb_id, title, year)
                else:
                    logging.debug(f"   [=] Stub already exists. No action needed.")

    logging.info("--- Run Complete ---")

if __name__ == "__main__":
    process_shows()