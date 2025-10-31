import argparse
import json
import logging
import sys
import os

from oci_wrapper import OciClient
import workflows

# --- State Management ---
def load_state(state_file_path):
    """Loads the migration state from a file."""
    if os.path.exists(state_file_path):
        log.info(f"Found existing state file: {state_file_path}. Resuming progress.")
        with open(state_file_path, 'r') as f:
            return json.load(f)
    log.info("No state file found. Starting a new migration.")
    return {}

def save_state(state_file_path, state):
    """Saves the migration state to a file."""
    log.info(f"Saving migration progress to {state_file_path}")
    with open(state_file_path, 'w') as f:
        json.dump(state, f, indent=2)

# --- Config & Logging ---
def load_config(config_path):
    """Loads the migration configuration."""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        log.error(f"Configuration file not found: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError:
        log.error(f"Invalid JSON in configuration file: {config_path}")
        sys.exit(1)

def setup_logging():
    """Configures logging to both console and file."""
    log = logging.getLogger()
    log.setLevel(logging.DEBUG) # Set root logger to debug
    
    # Console handler (INFO level)
    c_handler = logging.StreamHandler(sys.stdout)
    c_handler.setLevel(logging.INFO)
    c_format = logging.Formatter('%(message)s') # Simple format for console
    c_handler.setFormatter(c_format)
    log.addHandler(c_handler)
    
    # File handler (DEBUG level)
    f_handler = logging.FileHandler('migration.log', mode='w')
    f_handler.setLevel(logging.DEBUG)
    f_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    f_handler.setFormatter(f_format)
    log.addHandler(f_handler)
    
    return log

# --- Main Execution ---
def main():
    parser = argparse.ArgumentParser(description="OCI Migration Automation Tool (Ashburn to Bogotá)")
    parser.add_argument(
        "-c", "--config",
        default="config.json",
        help="Path to the configuration JSON file (default: config.json)"
    )
    parser.add_argument(
        "-w", "--workflow",
        required=True,
        choices=['compute', 'storage-replication', 'volume-replication'],
        help="The migration workflow to run."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the migration without executing OCI commands."
    )
    args = parser.parse_args()

    # --- 1. Initialization ---
    config = load_config(args.config)
    state_file = config.get('state_file_path', 'migration.state.json')
    state = load_state(state_file)
    
    if args.dry_run:
        log.info("********** DRY RUN MODE ENABLED **********")
        log.info("No commands will be executed. State will not be saved.")
    
    # --- 2. Instantiate OCI Clients ---
    ashburn_client = OciClient(config['source_region'], dry_run=args.dry_run)
    bogota_client = OciClient(config['target_region'], dry_run=args.dry_run)

    # --- 3. Execute Workflow ---
    try:
        if args.workflow == 'compute':
            workflows.migrate_compute_instance(config, state, ashburn_client, bogota_client)
        
        elif args.workflow == 'storage-replication':
            log.info("Storage replication workflow not yet implemented.")
            # Call workflows.setup_storage_replication(config, state, ashburn_client)
        
        elif args.workflow == 'volume-replication':
            log.info("Volume replication workflow not yet implemented.")
            # Call workflows.setup_volume_replication(config, state, bogota_client)

        log.info("Workflow completed successfully.")
        
    except Exception as e:
        log.critical(f"--- 🚨 MIGRATION FAILED ---")
        log.critical(f"  An unrecoverable error occurred: {e}")
        log.critical("  Migration progress has been saved to the state file.")
        log.critical("  Review 'migration.log' for details. Rerun the script to resume.")
    
    finally:
        # Always save state, even on failure, to resume
        if not args.dry_run:
            save_state(state_file, state)

if __name__ == "__main__":
    log = setup_logging() # Setup logging first
    main()
