import os
import re
import requests
from plexapi.server import PlexServer
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()

# 1. FIXED: Hardcoded Internal IP to ensure it works immediately
# This bypasses the "None" error you saw.
PLEX_URL = 'http://172.17.0.1:14725' 
PLEX_TOKEN = os.getenv('PLEX_TOKEN', 'qiZbQv9h3TMt3x9MFQgR') # I grabbed your token from the log to ensure it works

# 2. CONFIG: Point this to your assets folder
ASSET_DIR = '/home32/northmainave/scripts/kometa/config/assets'

# Libraries to scan
LIBRARIES = ['Movies', 'TV Shows', 'Anime', ]

# If True, tries to find the "original" metadata poster (skipping user uploads/overlays)
GRAB_ORIGINALS = True 

# ---------------------

def get_correct_folder_name(item):
    """
    Gets the exact folder name from the disk path.
    Fixed to handle both Movies (media parts) and Shows (locations).
    """
    try:
        dir_path = ""
        
        # Logic for TV Shows (Bosch, Anime, etc.)
        if item.type == 'show':
            if hasattr(item, 'locations') and item.locations:
                dir_path = item.locations[0]
        
        # Logic for Movies
        elif hasattr(item, 'media') and item.media:
            file_path = item.media[0].parts[0].file
            dir_path = os.path.dirname(file_path)

        if not dir_path:
            raise ValueError("No path found")

        # Extract just the folder name (e.g., "Bosch - Legacy (2022) {imdb-tt...}")
        folder_name = os.path.basename(dir_path)
        
        # Safety check: If path ends in root slash, basename might be empty
        if not folder_name:
            folder_name = os.path.basename(os.path.dirname(dir_path))

        return folder_name

    except Exception as e:
        print(f"    [!] Could not determine path for {item.title}: {e}")
        # Fallback to sanitized title if path fails (Not ideal for Kometa asset_folders)
        safe_title = re.sub(r'[\\/*?:"<>|]', "", item.title).strip()
        if item.year:
            return f"{safe_title} ({item.year})"
        return safe_title

def get_best_poster(item):
    """
    Finds the best 'original' poster url.
    """
    if not GRAB_ORIGINALS:
        return item.thumb

    try:
        # Fetch all available posters for this item
        images = item.posters()
        
        if not images:
            return None

        # Priority: Look for an image provided by a metadata agent (tmdb/tvdb)
        for img in images:
            if img.provider and 'localmedia' not in img.provider:
                return img.key
        
        # If no remote metadata poster found, return the first available
        return images[0].key

    except:
        return item.thumb

def download_image(url, filepath):
    if not url:
        return

    # Skip if already exists to save time
    if os.path.exists(filepath):
        print(f"    [Exists] {os.path.basename(filepath)}")
        return

    try:
        # Build URL if relative
        full_url = url
        if not url.startswith('http'):
            full_url = f"{PLEX_URL}{url}"

        headers = {'X-Plex-Token': PLEX_TOKEN, 'Accept': 'application/json'}
        
        response = requests.get(full_url, headers=headers, stream=True)
        if response.status_code == 200:
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            print(f"    [Saved] {os.path.basename(filepath)}")
        else:
            print(f"    [Error] HTTP {response.status_code} for {full_url}")
    except Exception as e:
        print(f"    [Error] Failed to download: {e}")

def process_library(plex, lib_name):
    print(f"\n--- Scanning Library: {lib_name} ---")
    try:
        library = plex.library.section(lib_name)
        all_items = library.all()
        print(f"Found {len(all_items)} items. Processing...")
        
        for item in all_items:
            # 1. Get the exact folder name on disk
            asset_name = get_correct_folder_name(item)
            
            # 2. Create the folder in your Asset Directory
            target_dir = os.path.join(ASSET_DIR, asset_name)
            if not os.path.exists(target_dir):
                try:
                    os.makedirs(target_dir)
                except OSError:
                    print(f"    [!] Error creating folder: {asset_name}")
                    continue

            # 3. Download Series/Movie Poster
            poster_url = get_best_poster(item)
            if poster_url:
                download_image(poster_url, os.path.join(target_dir, "poster.jpg"))

            # 4. If it's a TV Show, handle Season posters
            if item.type == 'show':
                for season in item.seasons():
                    season_idx = int(season.index)
                    
                    # Kometa expects "Season01.jpg", "Season02.jpg", etc.
                    # Season 0 is usually "Specials"
                    if season_idx == 0:
                         filename = "Season00.jpg"
                    else:
                        filename = f"Season{season_idx:02d}.jpg"
                    
                    s_poster = get_best_poster(season)
                    if s_poster:
                        download_image(s_poster, os.path.join(target_dir, filename))
                        
    except Exception as e:
        print(f"Could not process library {lib_name}: {e}")

def main():
    print(f"Connecting to Plex at {PLEX_URL}...")
    try:
        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        print(f"Connected to: {plex.friendlyName}")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    if not os.path.exists(ASSET_DIR):
        try:
            os.makedirs(ASSET_DIR)
            print(f"Created asset directory: {ASSET_DIR}")
        except:
            print(f"Error: Could not create {ASSET_DIR}")
            return

    for lib in LIBRARIES:
        process_library(plex, lib)

    print("\nDone! Run Kometa now.")

if __name__ == "__main__":
    main()