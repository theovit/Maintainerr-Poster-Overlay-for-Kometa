import requests
from datetime import datetime, timedelta, timezone
import os
import yaml
import logging
import sys
from urllib.parse import quote, urlparse

class MaintainerrKometaGenerator:
    def __init__(self, config_path="config.yaml"):
        self.setup_logging()
        self.config = self.load_config(config_path)
        self.overlays_data = {}

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
        required_keys = ['maintainerr_host', 'maintainerr_port', 'maintainerr_user', 'maintainerr_pass']
        for key in required_keys:
            if key not in connect:
                self.logger.critical(f"Missing required key in 'connect' section: {key}")
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
        """
        Attempts to find TMDb or TVDb ID from Maintainerr item data.
        Returns tuple: (id_type, id_value) or (None, None)
        id_type will be 'tmdb' or 'tvdb'.
        """
        # 1. Check explicit fields if Maintainerr provides them (common in 'tmdbId')
        if item.get('tmdbId'):
            return 'tmdb', item['tmdbId']
        
        if item.get('tvdbId'):
            return 'tvdb', item['tvdbId']

        # 2. Check Plex GUIDs (common for Hama/Anime or legacy agents)
        # Structure: "guid": "com.plexapp.agents.hama://tvdb-12345?lang=en"
        # or "guids": [ { "id": "tmdb://123" } ]
        
        # Check nested guids array
        plex_data = item.get('plexData', {})
        for guid_entry in plex_data.get('guids', []):
            guid_id = guid_entry.get('id', '')
            if guid_id.startswith('tmdb://'):
                return 'tmdb', int(guid_id.split('//')[1])
            if guid_id.startswith('tvdb://'):
                return 'tvdb', int(guid_id.split('//')[1])

        # Check main guid string
        main_guid = plex_data.get('guid', '')
        if 'tmdb-' in main_guid:
            try:
                return 'tmdb', int(main_guid.split('tmdb-')[1].split('?')[0].split('/')[0])
            except: pass
        if 'tvdb-' in main_guid:
            try:
                return 'tvdb', int(main_guid.split('tvdb-')[1].split('?')[0].split('/')[0])
            except: pass

        return None, None

    def process_collection(self, collection):
        col_id = collection.get('id')
        delete_days_rule = collection.get('deleteAfterDays')

        if delete_days_rule is None:
             return

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
                
                if not time_str or not urgency_level:
                    continue

                # Determine Media Type
                # Maintainerr 'mediaType' is usually 'movie' or 'tv'
                # Plex 'type' is 'movie' or 'show'
                media_type = item.get('mediaType') or item.get('plexData', {}).get('type')
                
                # Find ID
                id_type, id_val = self.get_external_id(item)
                
                if not id_val:
                    self.logger.warning(f"Skipping item '{item.get('title')}' - Could not find TMDb or TVDb ID.")
                    continue

                group_key = f"{time_str}|{urgency_level}"
                if group_key not in self.overlays_data:
                    self.overlays_data[group_key] = {'tmdb_movie': [], 'tmdb_show': [], 'tvdb_show': []}

                # Sort into correct builder bucket
                if media_type == 'movie':
                    if id_type == 'tmdb':
                        self.overlays_data[group_key]['tmdb_movie'].append(id_val)
                    # If we only have tvdb for a movie (rare), we skip or add logic here
                elif media_type in ['tv', 'show']:
                    if id_type == 'tmdb':
                        self.overlays_data[group_key]['tmdb_show'].append(id_val)
                    elif id_type == 'tvdb':
                        self.overlays_data[group_key]['tvdb_show'].append(id_val)

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

    def generate_yaml(self):
        raw_path = self.config.get('output', {}).get('yaml_path')
        if not raw_path or "/path/to/" in raw_path:
             self.logger.critical("Output path is default or missing.")
             return

        output_path = os.path.abspath(os.path.expanduser(raw_path))
        
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
        except OSError as e:
            self.logger.error(f"Directory error: {e}")
            return
        
        kometa_config = {"overlays": {}}
        
        for group_key, buckets in self.overlays_data.items():
            time_str, urgency = group_key.split("|")
            styles = self.config.get('styles', {})
            style = styles.get(urgency, styles.get('notice', {})).copy()
            safe_key = f"maintainerr_{time_str.replace(' ', '_').replace('<', 'less').lower()}"
            
            if urgency == "critical": text_content = f"EXPIRING: {time_str}"
            elif urgency == "warning": text_content = f"Leaves in {time_str}"
            elif urgency == "notice": text_content = f"Leaving: {time_str}"
            else: text_content = f"Deletion: {time_str}"
            
            # Build the definition using valid Builders
            overlay_def = {
                "overlay": { "name": f"text({text_content})", **style }
            }
            
            # Add valid builders if they have data
            if buckets['tmdb_movie']:
                overlay_def['tmdb_movie'] = buckets['tmdb_movie']
            if buckets['tmdb_show']:
                overlay_def['tmdb_show'] = buckets['tmdb_show']
            if buckets['tvdb_show']:
                overlay_def['tvdb_show'] = buckets['tvdb_show']
            
            # Only add if we actually have items
            if any(buckets.values()):
                kometa_config["overlays"][safe_key] = overlay_def
            
        try:
            with open(output_path, 'w') as f:
                f.write("# Generated by Maintainerr-Kometa Script\n")
                f.write(f"# Generated at: {datetime.now()}\n")
                yaml.dump(kometa_config, f, sort_keys=False)
            self.logger.info(f"Successfully wrote YAML to {output_path}")
        except Exception as e:
            self.logger.error(f"Failed to write YAML file: {e}")

if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    generator = MaintainerrKometaGenerator(config_file)
    try:
        generator.run()
    except KeyboardInterrupt:
        sys.exit(0)