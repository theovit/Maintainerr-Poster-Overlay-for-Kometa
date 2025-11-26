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
        """Load settings from the YAML config file."""
        if not os.path.exists(path):
            self.logger.critical(f"Config file not found at: {path}")
            self.logger.critical("Please create the config file.")
            sys.exit(1)
        
        try:
            with open(path, 'r') as f:
                config = yaml.safe_load(f)
                self.logger.debug(f"Config loaded successfully from {path}")
                return config
        except Exception as e:
            self.logger.critical(f"Failed to parse config file: {e}")
            sys.exit(1)

    def validate_config(self):
        """Strictly checks if the user is still using template/default values."""
        forbidden_defaults = {
            "maintainerr_pass": "your#secure#password",
            "plex_token": "YOUR_PLEX_TOKEN",
            "yaml_path": "/path/to/kometa/config/overlays/maintainerr_overlays.yml",
            "maintainerr_host": "192.168.1.100"
        }

        issues = []
        connect = self.config.get('connect', {})
        output = self.config.get('output', {})

        for key, default_val in forbidden_defaults.items():
            if key in connect and connect[key] == default_val:
                issues.append(f"Config '{key}' is still set to default: '{default_val}'")
            if key == "yaml_path" and output.get('yaml_path') == default_val:
                issues.append(f"Config 'yaml_path' is still set to default: '{default_val}'")

        required_connect = ['maintainerr_host', 'maintainerr_port', 'maintainerr_user', 'maintainerr_pass']
        for key in required_connect:
            if key not in connect:
                issues.append(f"Missing required key in 'connect' section: {key}")

        if issues:
            self.logger.critical("Configuration Validation Failed! You must update 'config.yaml'.")
            for issue in issues:
                self.logger.error(f"  [!] {issue}")
            return False
            
        self.logger.info("Configuration passed validation checks.")
        return True

    def construct_maintainerr_url(self):
        """Constructs the full authenticated URL."""
        c = self.config['connect']
        
        raw_user = str(c.get('maintainerr_user', ''))
        raw_pass = str(c.get('maintainerr_pass', ''))
        raw_host = str(c.get('maintainerr_host', '')).replace('http://', '').replace('https://', '').strip('/')
        raw_port = str(c.get('maintainerr_port', ''))

        safe_user = quote(raw_user, safe='')
        safe_pass = quote(raw_pass, safe='')

        full_url = f"http://{safe_user}:{safe_pass}@{raw_host}:{raw_port}"
        self.logger.debug(f"Constructed URL: http://{safe_user}:***@{raw_host}:{raw_port}")
        return full_url

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
            self.logger.debug(f"Fetching collections from: {url}")
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            self.logger.info(f"Successfully retrieved {len(data)} collections from Maintainerr.")
            return data
        except Exception as e:
            self.logger.error(f"Error connecting to Maintainerr: {e}")
            return []

    def process_collection(self, collection):
        col_id = collection.get('id')
        col_name = collection.get('name', 'Unknown')
        delete_days_rule = collection.get('deleteAfterDays')

        self.logger.debug(f"Processing Collection: '{col_name}' (ID: {col_id}) - Rule: {delete_days_rule} days")

        if delete_days_rule is None:
             self.logger.warning(f"Collection '{col_name}' has NO delete rule set. Skipping.")
             return

        base_url = self.construct_maintainerr_url()
        url = f"{base_url}/api/collections/media/{col_id}/content/1?size=1000"
        
        try:
            response = requests.get(url, timeout=30)
            data = response.json().get('items', [])
            self.logger.debug(f"  > Found {len(data)} items in collection '{col_name}'")
        except Exception as e:
            self.logger.error(f"Error fetching items for collection {col_id}: {e}")
            return

        for item in data:
            try:
                add_date_str = item.get('addDate')
                if not add_date_str:
                    continue

                add_date = datetime.strptime(add_date_str, '%Y-%m-%dT%H:%M:%S.000Z')
                add_date = add_date.replace(tzinfo=timezone.utc)
                
                delete_date = add_date + timedelta(days=delete_days_rule)
                now = datetime.now(timezone.utc)
                time_left = delete_date - now
                
                time_str, urgency_level = self.get_time_string_and_urgency(time_left, delete_days_rule)
                
                # FIX: Use ratingKey instead of GUID for Kometa compatibility
                rating_key = item.get('plexData', {}).get('ratingKey')
                
                if time_str and urgency_level and rating_key:
                    group_key = f"{time_str}|{urgency_level}"
                    
                    if group_key not in self.overlays_data:
                        self.overlays_data[group_key] = []
                    
                    # Ensure it's an integer for cleaner YAML
                    self.overlays_data[group_key].append(int(rating_key))
                
            except Exception as e:
                self.logger.error(f"Skipping item in '{col_name}' due to error: {e}", exc_info=True)

    def get_time_string_and_urgency(self, delta, collection_limit_days):
        days = delta.days
        hours = round(delta.seconds / 3600)
        
        triggers = self.config.get('triggers', {})
        crit_days = triggers.get('critical_days', 3)
        warn_days = triggers.get('warning_days', 7)
        notice_days = triggers.get('notice_days', 14)
        use_limit = triggers.get('use_maintainerr_limit', False)

        if days < 0:
             return "Expiring", "critical"
        if days < 1:
            if hours <= 1:
                return "< 1 Hour", "critical"
            return f"{hours} Hours", "critical"
        elif days < crit_days:
            return f"{days} Days", "critical"
        elif days <= warn_days:
            return f"{days} Days", "warning"
        elif days <= notice_days:
            return f"{days} Days", "notice"
        elif use_limit and days <= collection_limit_days:
            return f"{days} Days", "monitor"
        else:
            return None, None

    def generate_yaml(self):
        raw_path = self.config.get('output', {}).get('yaml_path')
        
        if not raw_path:
             self.logger.critical("No output path defined in config!")
             return

        if "/path/to/" in raw_path:
             self.logger.critical("Output path is default placeholder! Update config.")
             return

        output_path = os.path.abspath(os.path.expanduser(raw_path))

        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
        except OSError as e:
            self.logger.error(f"Could not create directory for output path '{output_path}': {e}")
            return
        
        kometa_config = {"overlays": {}}
        
        for group_key, keys in self.overlays_data.items():
            time_str, urgency = group_key.split("|")
            styles = self.config.get('styles', {})
            style = styles.get(urgency, styles.get('notice', {})).copy()
            safe_key = f"maintainerr_{time_str.replace(' ', '_').replace('<', 'less').lower()}"
            
            if urgency == "critical": text_content = f"EXPIRING: {time_str}"
            elif urgency == "warning": text_content = f"Leaves in {time_str}"
            elif urgency == "notice": text_content = f"Leaving: {time_str}"
            else: text_content = f"Deletion: {time_str}"
            
            # FIX: Use the 'key' builder instead of 'plex_search'
            overlay_def = {
                "overlay": { "name": f"text({text_content})", **style },
                "key": keys
            }
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
        print("\n[!] Script cancelled by user.")
        sys.exit(0)