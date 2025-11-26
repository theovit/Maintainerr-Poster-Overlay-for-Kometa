import requests
from datetime import datetime, timedelta
import os
import yaml
import logging
import sys

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
            sys.exit(1)
        
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.critical(f"Failed to parse config file: {e}")
            sys.exit(1)

    def run(self):
        logger.info("Starting Maintainerr to Kometa Sync...")
        
        # 1. Get Collections from Maintainerr
        collections = self.get_maintainerr_collections()
        
        # 2. Process items
        for col in collections:
            self.process_collection(col)
            
        # 3. Generate YAML
        self.generate_yaml()
        
        logger.info("Sync Complete.")

    def get_maintainerr_collections(self):
        """Fetch all collections from Maintainerr"""
        base_url = self.config['connect']['maintainerr_url'].rstrip('/')
        url = f"{base_url}/api/collections"
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to connect to Maintainerr: {e}")
            return []

    def process_collection(self, collection):
        """Get items for a specific collection and calculate remaining time"""
        col_id = collection['id']
        delete_days_rule = collection['deleteAfterDays']
        base_url = self.config['connect']['maintainerr_url'].rstrip('/')
        
        # API to get items in this collection
        url = f"{base_url}/api/collections/media/{col_id}/content/1?size=1000"
        
        try:
            response = requests.get(url)
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
                # We pass the collection's rule so we can check against the 4th trigger
                time_str, urgency_level = self.get_time_string_and_urgency(time_left, delete_days_rule)
                
                # If urgency is None, it means we are outside all trigger windows
                if time_str is None or urgency_level is None:
                    continue

                # We use the Plex GUID for robust matching in Kometa
                plex_guid = item['plexData']['guid']
                
                # Add to our grouping dictionary
                # Key = "5 Days|critical" (We combine them to ensure uniqueness in grouping)
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
        
        crit_days = self.config['triggers']['critical_days']
        warn_days = self.config['triggers']['warning_days']
        notice_days = self.config['triggers']['notice_days']
        use_limit = self.config['triggers'].get('use_maintainerr_limit', False)

        # Determine Label and Urgency
        # Priority: Critical -> Warning -> Notice -> Monitor
        
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
            # This is the 4th trigger: Item is within the collection's lifespan
            return f"{days} Days", "monitor"
        else:
            # Item hasn't hit any visual trigger yet
            return None, None

    def generate_yaml(self):
        """Writes the gathered data into a Kometa-compatible YAML file"""
        
        kometa_config = {"overlays": {}}
        output_path = self.config['output']['yaml_path']
        
        for group_key, guids in self.overlays_data.items():
            time_str, urgency = group_key.split("|")
            
            # Select the correct style template from config
            # Default to 'notice' if something weird happens
            style = self.config['styles'].get(urgency, self.config['styles']['notice']).copy()
            
            # Sanitize the key name for YAML (e.g., "maintainerr_5_days")
            safe_key = f"maintainerr_{time_str.replace(' ', '_').replace('<', 'less').lower()}"
            
            # Define the Overlay Text Prefix based on urgency
            if urgency == "critical":
                text_content = f"EXPIRING: {time_str}"
            elif urgency == "warning":
                text_content = f"Leaves in {time_str}"
            elif urgency == "notice":
                text_content = f"Leaving: {time_str}"
            else:
                # Monitor / Default text
                text_content = f"Deletion: {time_str}"
                
            # Build the Kometa Block
            overlay_def = {
                "overlay": {
                    "name": f"text({text_content})",
                    **style  # Unpack selected style settings
                },
                "plex_search": {
                    "any": {
                        "guid": guids # List of Plex GUIDs to match
                    }
                }
            }
            
            kometa_config["overlays"][safe_key] = overlay_def
            
        # Write to file
        try:
            # Ensure directory exists
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
    # Optional: Pass config path as argument, otherwise defaults to config.yaml
    config_file = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    generator = MaintainerrKometaGenerator(config_file)
    generator.run()