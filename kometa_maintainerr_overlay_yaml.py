import requests
from datetime import datetime, timedelta, timezone
import os
import yaml
import logging
import sys
from urllib.parse import quote

class MaintainerrKometaGenerator:
    def __init__(self, config_path="config.yaml"):
        self.setup_logging()
        self.config = self.load_config(config_path)
        self.overlays_data_movies = {}
        self.overlays_data_shows = {}

    def setup_logging(self):
        """Sets up logging to both console (clean) and file (detailed)."""
        log_file = "kometa_maintainerr_overlay_yaml.log"
        
        self.logger = logging.getLogger("MaintainerrOverlay")
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
            
        self.logger.info(f"Logging initialized. Debug logs writing to: {log_file}")

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
        output = self.config.get('output', {})
        
        required_keys = ['maintainerr_host', 'maintainerr_port', 'maintainerr_user', 'maintainerr_pass']
        for key in required_keys:
            if key not in connect:
                self.logger.critical(f"Missing required key in 'connect' section: {key}")
                return False

        if not output.get('movies_path') or not output.get('shows_path'):
             self.logger.critical("Missing 'movies_path' or 'shows_path' in 'output' section of config.")
             return False
             
        return True

    def construct_maintainerr_url(self):
        c = self.config['connect']
        raw_user = str(c.get('maintainerr_user', ''))
        raw_pass = str(c.get('maintainerr_pass', ''))
        raw_host = str(c.get('maintainerr_host', '')).replace('http://', '').replace('https://', '').strip('/')
        raw_port = str(c.get('maintainerr_port', ''))
        safe_user = quote(raw_user, safe='')
        safe_pass = quote(raw_pass, safe='')
        return f"http://{safe_user}:{safe_pass}@{raw_host}:{raw_port}"

    def run(self):
        if not self.validate_config():
            sys.exit(1)

        self.logger.info("Starting Maintainerr to Kometa Sync...")
        
        collections = self.get_maintainerr_collections()
        if not collections:
            self.logger.error("No collections found or connection failed.")
            return

        for col in collections:
            self.process_collection(col)
            
        self.generate_yaml()
        self.logger.info("Sync Complete.")

    def get_maintainerr_collections(self):
        base_url = self.construct_maintainerr_url()
        url = f"{base_url}/api/collections"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Error connecting to Maintainerr: {e}")
            return []

    def get_external_id(self, item):
        if item.get('tmdbId'): return 'tmdb', item['tmdbId']
        if item.get('tvdbId'): return 'tvdb', item['tvdbId']

        plex_data = item.get('plexData', {})
        for guid_entry in plex_data.get('guids', []):
            guid_id = guid_entry.get('id', '')
            if guid_id.startswith('tmdb://'): return 'tmdb', int(guid_id.split('//')[1])
            if guid_id.startswith('tvdb://'): return 'tvdb', int(guid_id.split('//')[1])

        main_guid = plex_data.get('guid', '')
        if 'tmdb-' in main_guid:
            try: return 'tmdb', int(main_guid.split('tmdb-')[1].split('?')[0].split('/')[0])
            except: pass
        if 'tvdb-' in main_guid:
            try: return 'tvdb', int(main_guid.split('tvdb-')[1].split('?')[0].split('/')[0])
            except: pass

        return None, None

    def process_collection(self, collection):
        col_id = collection.get('id')
        delete_days_rule = collection.get('deleteAfterDays')

        if delete_days_rule is None: return

        base_url = self.construct_maintainerr_url()
        url = f"{base_url}/api/collections/media/{col_id}/content/1?size=1000"
        
        try:
            response = requests.get(url, timeout=30)
            data = response.json().get('items', [])
        except Exception as e:
            self.logger.error(f"Error fetching items for collection {col_id}: {e}")
            return

        for item in data:
            try:
                add_date_str = item.get('addDate')
                if not add_date_str: continue

                add_date = datetime.strptime(add_date_str, '%Y-%m-%dT%H:%M:%S.000Z').replace(tzinfo=timezone.utc)
                delete_date = add_date + timedelta(days=delete_days_rule)
                time_left = delete_date - datetime.now(timezone.utc)
                
                time_str, urgency_level = self.get_time_string_and_urgency(time_left, delete_days_rule)
                
                if not time_str or not urgency_level: continue

                media_type = item.get('mediaType') or item.get('plexData', {}).get('type')
                id_type, id_val = self.get_external_id(item)
                
                if not id_val: continue

                group_key = f"{time_str}|{urgency_level}"
                
                if media_type == 'movie':
                    if group_key not in self.overlays_data_movies:
                        self.overlays_data_movies[group_key] = {'tmdb_movie': []}
                    if id_type == 'tmdb':
                        self.overlays_data_movies[group_key]['tmdb_movie'].append(id_val)
                
                elif media_type in ['tv', 'show']:
                    if group_key not in self.overlays_data_shows:
                        self.overlays_data_shows[group_key] = {'tmdb_show': [], 'tvdb_show': []}
                    if id_type == 'tmdb':
                        self.overlays_data_shows[group_key]['tmdb_show'].append(id_val)
                    elif id_type == 'tvdb':
                        self.overlays_data_shows[group_key]['tvdb_show'].append(id_val)

            except Exception as e:
                self.logger.error(f"Skipping item error: {e}")

    def get_time_string_and_urgency(self, delta, collection_limit_days):
        days = delta.days
        hours = round(delta.seconds / 3600)
        triggers = self.config.get('triggers', {})
        
        if days < 0: return "Expiring", "critical"
        if days < 1: return f"{hours} Hours" if hours > 1 else "< 1 Hour", "critical"
        elif days < triggers.get('critical_days', 3): return f"{days} Days", "critical"
        elif days <= triggers.get('warning_days', 7): return f"{days} Days", "warning"
        elif days <= triggers.get('notice_days', 14): return f"{days} Days", "notice"
        elif triggers.get('use_maintainerr_limit', False) and days <= collection_limit_days: return f"{days} Days", "monitor"
        else: return None, None

    def validate_font_path(self, font_path, output_path):
        """
        Checks if font exists. Tries absolute path, then relative to config, then relative to output.
        Returns (True/False, Path to use)
        """
        if not font_path: 
            return False, None

        # 1. Check absolute/direct path
        if os.path.exists(font_path):
            return True, font_path
            
        # 2. Check relative to the output directory (often config/overlays/...)
        base_dir = os.path.dirname(output_path)
        rel_path = os.path.join(base_dir, font_path)
        
        # Try to find common root (e.g., strip 'config/overlays' from file path if font has it too)
        # This is tricky without knowing Kometa root, so we trust the user's relative path mostly.
        # But we return the raw string so Kometa can resolve it if we can't find it locally.
        
        # Use a simple heuristic: If it looks like a path but we can't find it, 
        # log a warning but Pass it through anyway (Kometa might find it relative to ITSELF).
        self.logger.warning(f"Font file not found at '{font_path}' from script location. Passing to Kometa anyway, but it may fallback to default.")
        return True, font_path

    def get_merged_style(self, urgency, time_str):
        final_style = self.config.get('global_defaults', {}).copy()
        specific = self.config.get('styles', {}).get(urgency, {})
        
        for key, val in specific.items():
            if val is not None and val != "":
                final_style[key] = val
        
        # Clean up Font
        if 'font' in final_style:
             if not final_style['font']: 
                 del final_style['font']
             # We intentionally do NOT rigorously check file existence here because
             # the script and Kometa might see different relative paths. 
             # We trust the config but log a warning if it looks totally wrong.

        # Handle Text
        text_template = final_style.get('text', 'Deletion: {time}')
        final_text = text_template.replace('{time}', time_str)
        if 'text' in final_style:
            del final_style['text']
            
        return f"text({final_text})", final_style

    def write_single_file(self, file_path_key, data_dict):
        output_path = self.config.get('output', {}).get(file_path_key)
        
        if not output_path or "/path/to/" in output_path:
             self.logger.warning(f"Output path for '{file_path_key}' is default or missing. Skipping.")
             return

        output_path = os.path.abspath(os.path.expanduser(output_path))
        
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            kometa_config = {"overlays": {}}
            
            for group_key, buckets in data_dict.items():
                time_str, urgency = group_key.split("|")
                
                overlay_name, style_dict = self.get_merged_style(urgency, time_str)
                
                # Check font existence relative to script if possible, just for logging
                if 'font' in style_dict:
                    font_path = style_dict['font']
                    if not os.path.exists(font_path) and not font_path.startswith("/"):
                         # Just a weak check for logging purposes
                         pass 
                
                safe_key = f"maintainerr_{time_str.replace(' ', '_').replace('<', 'less').lower()}"
                
                overlay_def = { "overlay": { "name": overlay_name, **style_dict } }
                
                has_items = False
                for builder, ids in buckets.items():
                    if ids: 
                        overlay_def[builder] = ids
                        has_items = True
                
                if has_items:
                    kometa_config["overlays"][safe_key] = overlay_def

            with open(output_path, 'w') as f:
                f.write(f"# Generated by Maintainerr-Kometa Script at {datetime.now()}\n")
                yaml.dump(kometa_config, f, sort_keys=False)
            self.logger.info(f"Successfully wrote YAML to {output_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to write {output_path}: {e}")

    def generate_yaml(self):
        self.write_single_file("movies_path", self.overlays_data_movies)
        self.write_single_file("shows_path", self.overlays_data_shows)

if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    generator = MaintainerrKometaGenerator(config_file)
    try:
        generator.run()
    except KeyboardInterrupt:
        sys.exit(0)