import requests
from datetime import datetime, timedelta
import os
import yaml
import logging
import sys
from urllib.parse import quote  # Import for URL encoding

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class MaintainerrKometaGenerator:
    def __init__(self, config_path="config.yaml"):
        self.config = self.load_config(config_path)
        self.overlays_data = {}  # Dictionary to hold our groups

    def load_config(self, path):
        """Load settings from the YAML config file."""
        if not os.path.exists(path):
            logger.critical(f"Config file not found at: {path}")
            logger.critical("Please create the config file or check the path.")
            sys.exit(1)
        
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.critical(f"Failed to parse config file: {e}")
            sys.exit(1)

    def validate_config(self):
        """Check if the config has the required new fields."""
        defaults = [
            "YOUR_PLEX_TOKEN",
            "your#secure#password",
            "admin"
        ]
        
        issues = []
        connect = self.config.get('connect', {})
        
        if not connect:
            logger.critical("Config is missing the 'connect' section.")
            return False

        # Check for missing keys
        required_keys = ['maintainerr_host', 'maintainerr_port', 'maintainerr_user', 'maintainerr_pass']
        for key in required_keys:
            if key not in connect:
                issues.append(f"Missing config key: {key}")

        # Check for default placeholders
        if connect.get('plex_token') in defaults:
            issues.append("Plex Token is set to the default placeholder.")
        if connect.get('maintainerr_pass') in defaults:
            issues.append("Maintainerr Password appears to be default.")
            
        if issues:
            logger.critical("CONFIGURATION ERROR: It looks like you haven't updated 'config.yaml' yet.")
            for issue in issues:
                logger.error(f"  - {issue}")
            logger.info("Please open 'config.yaml' and enter your actual server details.")
            return False
        return True

    def construct_maintainerr_url(self):
        """
        Constructs the full authenticated URL: http://user:pass@host:port
        Encodes special characters in user/pass (e.g., # becomes %23).
        """
        c = self.config['connect']
        
        # 1. Get raw values
        raw_user = str(c.get('maintainerr_user', ''))
        raw_pass = str(c.get('maintainerr_pass', ''))
        raw_host = str(c.get('maintainerr_host', '')).replace('http://', '').replace('https://', '').strip('/')
        raw_port = str(c.get('maintainerr_port', ''))

        # 2. URL Encode User and Password (safe='' ensures symbols like / are also encoded)
        safe_user = quote(raw_user, safe='')
        safe_pass = quote(raw_pass, safe='')

        # 3. Construct URL
        # Format: http://username:password@host:port
        full_url = f"http://{safe_user}:{safe_pass}@{raw_host}:{raw_port}"
        
        return full_url

    def run(self):
        # Pre-flight check
        if not self.validate_config():
            sys.exit(1)

        logger.info("Starting Maintainerr to Kometa Sync...")
        
        # 1. Get Collections from Maintainerr
        collections = self.get_maintainerr_collections()
        
        if not collections:
            logger.error("No collections found or could not connect. Exiting.")
            return

        # 2. Process items
        for col in collections:
            self.process_collection(col)
            
        # 3. Generate YAML
        self.generate_yaml()
        
        logger.info("Sync Complete.")

    def get_maintainerr_collections(self):
        """Fetch all collections from Maintainerr"""
        
        # Construct the URL with credentials
        base_url = self.construct_maintainerr_url()
        url = f"{base_url}/api/collections"
        
        # Log the connection (masking password for security in logs)
        masked_url = url.split('@')[-1]
        logger.info(f"Connecting to Maintainerr at: http://***:***@{masked_url}")
        
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectTimeout:
            logger.critical(f"Connection timed out. Check IP and Port.")
            return []
        except requests.exceptions.ConnectionError:
            logger.critical(f"Failed to connect. The server might be down or credentials are wrong.")
            return []
        except Exception as e:
            logger.error(f"Unexpected error connecting to Maintainerr: {e}")
            return []

    def process_collection(self, collection):
        """Get items for a specific collection and calculate remaining time"""
        col_id = collection['id']
        delete_days_rule = collection['deleteAfterDays']
        
        # Construct the URL with credentials
        base_url = self.construct_maintainerr_url()
        
        # API to get items in this collection
        url = f"{base_url}/api/collections/media/{col_id}/content/1?size=1000"
        
        try:
            response = requests.get(url, timeout=10)
            data = response.json().get('items', [])
        except Exception as e:
            logger.error(f"Error fetching items for collection {col_id}: {e}")
            return

        for item in data:
            try:
                # Calculate Delete Date
                add_date = datetime.strptime(item['addDate'], '%Y-%m-%dT%H:%M:%S.000Z')
                delete_date = add_date + timedelta(days=delete_days_rule)
                
                # Normalize to midnight for cleaner math
                now = datetime.utcnow()
                time_left = delete_date - now
                
                # Generate the "Label" (e.g., "5 Days", "12 Hours")
                time_str, urgency_level = self.get_time_string_and_urgency(time_left, delete_days_rule)
                
                if time_str is None or urgency_level is None:
                    continue

                # We use the Plex GUID for robust matching in Kometa
                plex_guid = item['plexData']['guid']
                
                group_key = f"{time_str}|{urgency_level}"
                
                if group_key not in self.overlays_data:
                    self.overlays_data[group_key] = []
                
                self.overlays_data[group_key].append(plex_guid)
                
            except Exception as e:
                logger.error(f"Skipping item due to error: {e}")

    def get_time_string_and_urgency(self, delta, collection_limit_days):
        """
        Converts a timedelta into a clean string and an urgency level.
        Uses triggers from config file.
        """
        days = delta.days
        hours = round(delta.seconds / 3600)
        
        triggers = self.config.get('triggers', {})
        crit_days = triggers.get('critical_days', 3)
        warn_days = triggers.get('warning_days', 7)
        notice_days = triggers.get('notice_days', 14)
        use_limit = triggers.get('use_maintainerr_limit', False)

        # Determine Label and Urgency
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
        """Writes the gathered data into a Kometa-compatible YAML file"""
        
        if not self.overlays_data:
            logger.warning("No items found to overlay. YAML file will be empty (or unchanged).")
        
        kometa_config = {"overlays": {}}
        output_path = self.config['output']['yaml_path']
        
        for group_key, guids in self.overlays_data.items():
            time_str, urgency = group_key.split("|")
            
            styles = self.config.get('styles', {})
            style = styles.get(urgency, styles.get('notice', {})).copy()
            
            # Sanitize the key name for YAML (e.g., "maintainerr_5_days")
            safe_key = f"maintainerr_{time_str.replace(' ', '_').replace('<', 'less').lower()}"
            
            if urgency == "critical":
                text_content = f"EXPIRING: {time_str}"
            elif urgency == "warning":
                text_content = f"Leaves in {time_str}"
            elif urgency == "notice":
                text_content = f"Leaving: {time_str}"
            else:
                text_content = f"Deletion: {time_str}"
                
            overlay_def = {
                "overlay": {
                    "name": f"text({text_content})",
                    **style
                },
                "plex_search": {
                    "any": {
                        "guid": guids
                    }
                }
            }
            
            kometa_config["overlays"][safe_key] = overlay_def
            
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w') as f:
                f.write("# Generated by Maintainerr-Kometa Script\n")
                f.write(f"# Generated at: {datetime.now()}\n")
                f.write("# Do not edit manually; this file is overwritten on schedule.\n\n")
                yaml.dump(kometa_config, f, sort_keys=False)
            logger.info(f"Successfully wrote YAML to {output_path}")
        except Exception as e:
            logger.error(f"Failed to write YAML file: {e}")

if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    generator = MaintainerrKometaGenerator(config_file)
    
    try:
        generator.run()
    except KeyboardInterrupt:
        print("\n[!] Script cancelled by user.")
        sys.exit(0)