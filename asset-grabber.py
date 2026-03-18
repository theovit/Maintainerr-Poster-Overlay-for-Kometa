import os
import re
import time
import json
import requests
import yaml
import logging
import sys
try:
    from plexapi.server import PlexServer
except ImportError:
    print("ERROR: PlexAPI is not installed. Run: pip install PlexAPI")
    sys.exit(1)

class KometaAssetGrabber:
    def __init__(self, config_path="config.yaml"):
        self.setup_logging()
        self.config = self.load_config(config_path)

    def setup_logging(self):
        """Sets up logging to both console (clean) and file (detailed)."""
        log_file = "kometa_asset_grabber.log"
        
        self.logger = logging.getLogger("AssetGrabber")
        self.logger.setLevel(logging.DEBUG)
        
        c_handler = logging.StreamHandler()
        f_handler = logging.FileHandler(log_file, mode='w')
        
        c_handler.setLevel(logging.INFO)
        f_handler.setLevel(logging.DEBUG)
        
        c_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
        f_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s')
        c_handler.setFormatter(c_format)
        f_handler.setFormatter(f_format)
        
        if not self.logger.handlers:
            self.logger.addHandler(c_handler)
            self.logger.addHandler(f_handler)
            
        self.logger.info(f"Logging initialized. Writing to: {log_file}")

    def load_config(self, path):
        if not os.path.exists(path):
            self.logger.critical(f"Config file not found at: {path}")
            sys.exit(1)
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.logger.critical(f"Failed to parse config file: {e}")
            sys.exit(1)

    def validate_config(self):
        connect = self.config.get('connect', {})
        assets = self.config.get('assets', {})
        plex_cfg = connect.get('plex', {})
        plex_url = plex_cfg.get('url') or connect.get('plex_url')
        plex_token = plex_cfg.get('token') or connect.get('plex_token')

        if not plex_url or not plex_token:
            self.logger.critical("Missing Plex URL or token in config.yaml (connect.plex.url / connect.plex.token)")
            return False

        if not assets.get('path'):
            self.logger.critical("Missing 'assets: path' in config.yaml")
            return False

        return True

    def get_correct_folder_name(self, item):
        """
        Gets the exact folder name from the disk path.
        Crucial for Kometa's asset matching.
        """
        try:
            dir_path = ""
            
            # Logic for TV Shows
            if item.type == 'show':
                if hasattr(item, 'locations') and item.locations:
                    dir_path = item.locations[0]
            
            # Logic for Movies
            elif hasattr(item, 'media') and item.media:
                file_path = item.media[0].parts[0].file
                dir_path = os.path.dirname(file_path)

            if not dir_path:
                raise ValueError("No path found")

            # Extract just the folder name
            folder_name = os.path.basename(dir_path)
            
            # Safety check for root slash issues
            if not folder_name:
                folder_name = os.path.basename(os.path.dirname(dir_path))

            return folder_name

        except Exception as e:
            self.logger.warning(f"Could not determine path for {item.title}: {e}")
            # Fallback to sanitized title
            safe_title = re.sub(r'[\\/*?:"<>|]', "", item.title).strip()
            if item.year:
                return f"{safe_title} ({item.year})"
            return safe_title

    def get_best_poster(self, item):
        """Finds the best 'original' poster URL (skipping local overlays if requested)."""
        grab_originals = self.config['assets'].get('grab_originals', True)

        if not grab_originals:
            return item.thumb

        try:
            images = item.posters()
            if not images: return None

            # Priority: Image provided by metadata agent (tmdb/tvdb)
            for img in images:
                if img.provider and 'localmedia' not in img.provider:
                    return img.key
            
            return images[0].key
        except:
            return item.thumb

    def download_image(self, url, filepath, plex_url, plex_token):
        if not url: return

        # 1. Smart Check: Don't re-download if ANY valid version exists (JPG or WebP)
        base_path = os.path.splitext(filepath)[0]
        if os.path.exists(base_path + ".jpg"):
            self.logger.debug(f"Skipping (JPG Exists): {os.path.basename(base_path + '.jpg')}")
            return
        if os.path.exists(base_path + ".webp"):
            self.logger.debug(f"Skipping (WebP Exists): {os.path.basename(base_path + '.webp')}")
            return

        try:
            full_url = url
            if not url.startswith('http'):
                full_url = f"{plex_url}{url}"

            headers = {'X-Plex-Token': plex_token, 'Accept': 'application/json'}
            
            response = requests.get(full_url, headers=headers, stream=True, timeout=20)
            if response.status_code == 200:
                # 2. Fix: Detect the REAL format from the headers
                content_type = response.headers.get('Content-Type', '')
                final_filepath = filepath

                # If Plex sent a WebP, force the extension to .webp
                if 'image/webp' in content_type:
                    final_filepath = base_path + ".webp"
                
                with open(final_filepath, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                self.logger.info(f"Downloaded: {os.path.basename(final_filepath)}")
                time.sleep(0.2)
            else:
                self.logger.error(f"HTTP {response.status_code} for {full_url}")
        except Exception as e:
            self.logger.error(f"Failed to download: {e}")

    def load_season_cache(self, cache_path):
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_season_cache(self, cache_path, cache):
        try:
            with open(cache_path, 'w') as f:
                json.dump(cache, f)
        except Exception as e:
            self.logger.warning(f"Could not save season cache: {e}")

    def run(self):
        # 1. Check if Enabled
        if not self.config.get('assets', {}).get('enabled', True):
            self.logger.info("Asset Grabber is disabled in config.yaml. Skipping.")
            return

        # 2. Validate other settings
        if not self.validate_config():
            sys.exit(1)

        connect = self.config['connect']
        plex_cfg = connect.get('plex', {})
        plex_url = plex_cfg.get('url') or connect.get('plex_url')
        plex_token = plex_cfg.get('token') or connect.get('plex_token')
        asset_dir = os.path.expanduser(self.config['assets']['path'])
        libraries = self.config['assets'].get('libraries', [])
        cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'asset_season_cache.json')
        season_cache = self.load_season_cache(cache_path)

        self.logger.info(f"Connecting to Plex at {plex_url}...")
        
        try:
            plex = PlexServer(plex_url, plex_token)
            self.logger.info(f"Connected to: {plex.friendlyName}")
        except Exception as e:
            self.logger.critical(f"Connection failed: {e}")
            return

        # Create Asset Directory
        try:
            os.makedirs(asset_dir, exist_ok=True)
        except OSError as e:
            self.logger.critical(f"Could not create asset directory: {e}")
            return

        for lib_name in libraries:
            self.logger.info(f"--- Scanning Library: {lib_name} ---")
            try:
                library = plex.library.section(lib_name)
                all_items = library.all()
                self.logger.info(f"Found {len(all_items)} items. Processing...")
                
                for item in all_items:
                    # 1. Get correct folder name
                    asset_name = self.get_correct_folder_name(item)
                    
                    # 2. Create folder
                    target_dir = os.path.join(asset_dir, asset_name)
                    if not os.path.exists(target_dir):
                        try:
                            os.makedirs(target_dir)
                        except OSError:
                            self.logger.error(f"Error creating folder: {asset_name}")
                            continue

                    # 3. Download Poster (skip API call if already on disk)
                    poster_path = os.path.join(target_dir, "poster.jpg")
                    poster_base = os.path.splitext(poster_path)[0]
                    if not os.path.exists(poster_base + ".jpg") and not os.path.exists(poster_base + ".webp"):
                        poster_url = self.get_best_poster(item)
                        if poster_url:
                            self.download_image(poster_url, poster_path, plex_url, plex_token)

                    # 4. Handle Seasons (cache-aware: skip API call if count unchanged and all posters exist)
                    if item.type == 'show':
                        key = str(item.ratingKey)
                        current_count = item.childCount
                        cached = season_cache.get(key, {})
                        cached_indices = cached.get('indices', [])
                        cached_count = cached.get('count', -1)

                        # Check if all cached season posters exist on disk
                        def all_posters_exist(indices):
                            for idx in indices:
                                base = os.path.join(target_dir, "Season00" if idx == 0 else f"Season{idx:02d}")
                                if not os.path.exists(base + ".jpg") and not os.path.exists(base + ".webp"):
                                    return False
                            return True

                        if cached_count == current_count and cached_indices and all_posters_exist(cached_indices):
                            self.logger.debug(f"Season cache hit (all {current_count} seasons present): {item.title}")
                        else:
                            # Fetch seasons from Plex, download any missing posters, update cache
                            season_indices = []
                            for season in item.seasons():
                                season_idx = int(season.index)
                                season_indices.append(season_idx)
                                filename = "Season00.jpg" if season_idx == 0 else f"Season{season_idx:02d}.jpg"
                                season_path = os.path.join(target_dir, filename)
                                season_base = os.path.splitext(season_path)[0]
                                if not os.path.exists(season_base + ".jpg") and not os.path.exists(season_base + ".webp"):
                                    s_poster = self.get_best_poster(season)
                                    if s_poster:
                                        self.download_image(s_poster, season_path, plex_url, plex_token)
                            season_cache[key] = {'count': current_count, 'indices': season_indices}

            except Exception as e:
                self.logger.error(f"Could not process library {lib_name}: {e}")

        self.save_season_cache(cache_path, season_cache)
        self.logger.info("Asset Grabber Complete.")

if __name__ == "__main__":
    grabber = KometaAssetGrabber()
    try:
        grabber.run()
    except KeyboardInterrupt:
        sys.exit(0)