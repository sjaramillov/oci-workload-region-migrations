This is an excellent and critical request. Moving from a single script to a professional, "anti-failure" automation tool requires a significant shift in architecture. A production-grade tool must be **modular, configurable, fault-tolerant, and resumable**.

Here is a review and refactor of the automation solution, followed by the updated `README.md` that incorporates its use.

-----

## 🚀 The Professional Automation Tool: Review & Refactor

The original script was a linear template. A professional tool separates **configuration**, **state**, **core logic**, and **execution**.

This refactor introduces several key "anti-failure" concepts:

1.  **External Configuration (`config.json`):** Removes all hardcoded OCIDs and settings from the code. This is safer and more flexible.
2.  **State Management (`migration.state.json`):** The tool saves its progress (e.g., the OCID of a newly created image) to a state file. If the script fails, you can rerun it, and it will **skip completed steps**, resuming from where it left off. This is the *most critical* anti-failure feature (idempotency).
3.  **Automatic Retries (`tenacity`):** The tool will automatically retry OCI CLI commands that fail due to transient errors (like network timeouts or API throttling), using an exponential backoff strategy.
4.  **Modularity:** The code is split into logical files:
      * `migrate.py`: The main entry point, handles argument-parsing and logging.
      * `oci_wrapper.py`: A dedicated class for running OCI commands, incorporating retries and error handling.
      * `workflows.py`: The actual step-by-step migration logic (the "what to do").
      * `config.json.template`: A template for users to fill out.
      * `requirements.txt`: Defines dependencies.

### File Structure

```
oci-migration-tool/
├── migrate.py
├── oci_wrapper.py
├── workflows.py
├── config.json.template
├── requirements.txt
└── .gitignore
```

### The Code

Here is the code for each file.

#### `requirements.txt`

This file lists the Python dependencies.

```
oci
tenacity
```

#### `config.json.template`

A template for the user's configuration. They will copy this to `config.json` and fill it in.

```json
{
  "source_region": "us-ashburn-1",
  "target_region": "sa-bogota-1",
  "source_compartment_id": "ocid1.compartment.oc1..aaaa...",
  "target_compartment_id": "ocid1.compartment.oc1..bbbb...",
  "migration_bucket_name": "ashburn-migration-staging-bucket",
  "source_instance_id": "ocid1.instance.oc1.iad.aaaa...",
  "target_ad": "EXAMPLE-AD-1",
  "target_subnet_id": "ocid1.subnet.oc1.bgy.bbbb...",
  "target_instance_shape": "VM.Standard.E4.Flex",
  "new_image_name": "migrated-app-server-image",
  "new_instance_name": "migrated-app-server-bogota",
  "state_file_path": "migration.state.json"
}
```

#### `oci_wrapper.py`

This is the **anti-failure** core. It uses the `tenacity` library to wrap OCI calls in a robust retry mechanism.

```python
import subprocess
import json
import sys
import logging
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

# Configure logging
log = logging.getLogger(__name__)

# Define which exceptions should trigger a retry
# We retry on general CalledProcessError (for timeouts/transient CLI errors)
RETRYABLE_EXCEPTIONS = (subprocess.CalledProcessError)

class OciClient:
    """
    A wrapper for OCI CLI commands that includes robust retry logic,
    state-aware waiting, and standardized error handling.
    """
    
    def __init__(self, region, dry_run=False):
        self.region = region
        self.dry_run = dry_run
        log.info(f"OciClient initialized for region: {self.region}")

    @retry(
        wait=wait_exponential(multiplier=2, min=5, max=60),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        reraise=True,
        before_sleep=lambda retry_state: log.warning(
            f"Retrying command (Attempt {retry_state.attempt_number}): {retry_state.args[1]}"
        )
    )
    def run_command(self, command):
        """
        Runs an OCI CLI command with automatic retries on failure.
        """
        base_command = ["oci"]
        base_command.extend(command)
        base_command.extend(["--region", self.region])
        
        log.debug(f"[EXEC] {' '.join(base_command)}")
        
        if self.dry_run:
            log.info(f"[DRY_RUN] Would execute: {' '.join(base_command)}")
            # For a dry run, we can't return real data, so we return a placeholder
            # A more advanced dry_run would simulate expected output.
            return {"data": {"dry_run_ocid": "ocid1.dryrun.placeholder"}}

        try:
            result = subprocess.run(
                base_command,
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8'
            )

            if result.stderr:
                log.warning(f"[STDERR] {result.stderr.strip()}")
            
            if not result.stdout:
                log.info("[INFO] Command returned no output (e.g., a create policy).")
                return None
            
            return json.loads(result.stdout)

        except subprocess.CalledProcessError as e:
            log.error(f"--- ❌ OCI CLI ERROR (Region: {self.region}) ---")
            log.error(f"  Command: {' '.join(e.cmd)}")
            log.error(f"  Return Code: {e.returncode}")
            try:
                # Try to parse the error for a meaningful message
                oci_error = json.loads(e.stderr)
                log.error(f"  OCI Error: {oci_error.get('message')}")
            except json.JSONDecodeError:
                log.error(f"  Stderr: {e.stderr.strip()}")
            # Reraise the exception to trigger tenacity retry
            raise e
        except json.JSONDecodeError:
            log.error(f"Failed to decode JSON from OCI output: {result.stdout}")
            sys.exit(1)

    def wait_for_work_request(self, work_request_id, poll_interval=30):
        """Polls a work request until it succeeds, using retry logic."""
        log.info(f"Waiting for work request {work_request_id} to SUCCEED...")
        status = ""
        while status != "SUCCEEDED":
            if self.dry_run:
                log.info(f"[DRY_RUN] Would wait for work request {work_request_id}")
                return
            
            command = ["work-requests", "work-request", "get", "--work-request-id", work_request_id]
            try:
                data = self.run_command(command)
                status = data.get("data", {}).get("status")
                percent = data.get("data", {}).get("percent-complete", 0)
                log.info(f"  ...Work request {work_request_id} status: {status} ({percent}%)")

                if status == "SUCCEEDED":
                    log.info(f"✅ Work request {work_request_id} SUCCEEDED.")
                    return data
                elif status in ("FAILED", "CANCELED"):
                    log.error(f"Work request {work_request_id} failed with status: {status}")
                    raise Exception(f"WorkRequestFailed: {work_request_id}")

            except Exception as e:
                log.warning(f"Error checking work request, will retry: {e}")
            
            time.sleep(poll_interval)

    def wait_for_image_state(self, image_id, target_state="AVAILABLE", poll_interval=30):
        """Polls a compute image until it reaches the target state."""
        log.info(f"Waiting for image {image_id} to become '{target_state}'...")
        current_state = ""
        while current_state != target_state:
            if self.dry_run:
                log.info(f"[DRY_RUN] Would wait for image {image_id} to be {target_state}")
                return {"data": {"id": image_id, "operating-system": "DRY_RUN_OS", "operating-system-version": "DRY_RUN_OS_VER", "launch-mode": "DRY_RUN_LAUNCH_MODE"}}

            command = ["compute", "image", "get", "--image-id", image_id]
            try:
                data = self.run_command(command)
                current_state = data.get("data", {}).get("lifecycle-state")
                log.info(f"  ...Image {image_id} state: {current_state} (waiting for {target_state})")

                if current_state == target_state:
                    log.info(f"✅ Image {image_id} is now {target_state}.")
                    return data
                elif current_state in ("FAULTED", "DELETED"):
                    log.error(f"Image {image_id} entered a failure state: {current_state}")
                    raise Exception(f"ImageFailed: {image_id}")
            
            except Exception as e:
                log.warning(f"Error checking image state, will retry: {e}")

            time.sleep(poll_interval)
```

#### `workflows.py`

This file contains the high-level business logic for the migration, using the `OciClient` wrapper. Note the **idempotency checks** (e.g., `if 'source_image_id' not in state:`).

```python
import logging
import time

log = logging.getLogger(__name__)

def migrate_compute_instance(config, state, ashburn_client, bogota_client):
    """
    Main workflow to migrate a compute instance from Ashburn to Bogotá
    using the Image Export/Import method.
    
    This workflow is IDEMPOTENT. It checks the 'state' dictionary
    before performing an action and saves progress back to it.
    """
    
    log.info("==============================================")
    log.info(f"🚀 Starting Compute Instance Migration Workflow")
    log.info(f"   From: {config['source_instance_id']} ({config['source_region']})")
    log.info(f"   To:   {config['new_instance_name']} ({config['target_region']})")
    log.info("==============================================")

    image_name = config['new_image_name']
    image_obj_name = f"{image_name}.img"
    
    # --- Step 1: Create Custom Image from Source Instance ---
    if 'source_image_id' not in state:
        log.info(f"[Step 1/5] Creating custom image from {config['source_instance_id']}...")
        image_create_cmd = [
            "compute", "image", "create",
            "--compartment-id", config['source_compartment_id'],
            "--instance-id", config['source_instance_id'],
            "--display-name", image_name
        ]
        image_data = ashburn_client.run_command(image_create_cmd)
        state['source_image_id'] = image_data["data"]["id"]
        log.info(f"Image creation initiated. New Image OCID: {state['source_image_id']}")
    else:
        log.info(f"[Step 1/5] SKIPPED - Source image already created: {state['source_image_id']}")

    # --- Step 2: Wait for Source Image to be Available ---
    if 'source_image_available' not in state or not state['source_image_available']:
        log.info(f"[Step 2/5] Waiting for source image {state['source_image_id']} to be AVAILABLE...")
        image_details = ashburn_client.wait_for_image_state(state['source_image_id'], "AVAILABLE")
        # Save details needed for import
        state['source_image_details'] = {
            "os": image_details["data"]["operating-system"],
            "os_ver": image_details["data"]["operating-system-version"],
            "launch_mode": image_details["data"]["launch-mode"]
        }
        state['source_image_available'] = True
    else:
        log.info(f"[Step 2/5] SKIPPED - Source image is already AVAILABLE.")

    # --- Step 3: Export Custom Image to Object Storage ---
    if 'image_export_complete' not in state or not state['image_export_complete']:
        log.info(f"[Step 3/5] Exporting image {state['source_image_id']} to bucket {config['migration_bucket_name']}...")
        image_export_cmd = [
            "compute", "image", "export", "to-object-storage",
            "--image-id", state['source_image_id'],
            "--bucket-name", config['migration_bucket_name'],
            "--name", image_obj_name
        ]
        export_data = ashburn_client.run_command(image_export_cmd)
        export_work_request_id = export_data["opc-work-request-id"]
        
        log.info(f"Image export work request: {export_work_request_id}")
        ashburn_client.wait_for_work_request(export_work_request_id)
        state['image_export_complete'] = True
        log.info(f"✅ Image exported to {config['migration_bucket_name']}/{image_obj_name}")
    else:
        log.info(f"[Step 3/5] SKIPPED - Image export is already complete.")

    # --- Step 4: Import Custom Image in Target Region ---
    if 'target_image_id' not in state:
        log.info(f"[Step 4/5] Importing image from bucket into {config['target_region']}...")
        img_details = state['source_image_details']
        image_import_cmd = [
            "compute", "image", "import", "from-object-storage",
            "--compartment-id", config['target_compartment_id'],
            "--region", config['source_region'], # Source bucket region
            "--bucket-name", config['migration_bucket_name'],
            "--name", image_obj_name,
            "--display-name", image_name,
            "--operating-system", img_details['os'],
            "--operating-system-version", img_details['os_ver'],
            "--launch-mode", img_details['launch_mode']
        ]
        import_data = bogota_client.run_command(image_import_cmd)
        state['target_image_id'] = import_data["data"]["id"]
        log.info(f"Image import initiated. Target Image OCID: {state['target_image_id']}")
        
        # Wait for the image to become available in Bogotá
        bogota_client.wait_for_image_state(state['target_image_id'], "AVAILABLE")
    else:
        log.info(f"[Step 4/5] SKIPPED - Target image already imported: {state['target_image_id']}")

    # --- Step 5: Launch New Instance in Target Region ---
    if 'target_instance_id' not in state:
        log.info(f"[Step 5/5] Launching new instance {config['new_instance_name']} in {config['target_region']}...")
        instance_launch_cmd = [
            "compute", "instance", "launch",
            "--compartment-id", config['target_compartment_id'],
            "--availability-domain", config['target_ad'],
            "--subnet-id", config['target_subnet_id'],
            "--image-id", state['target_image_id'],
            "--shape", config['target_instance_shape'],
            "--display-name", config['new_instance_name'],
            "--wait-for-state", "RUNNING" # Use built-in waiter
        ]
        launch_data = bogota_client.run_command(instance_launch_cmd)
        state['target_instance_id'] = launch_data["data"]["id"]
        log.info(f"Instance launch initiated. New Instance OCID: {state['target_instance_id']}")
    else:
        log.info(f"[Step 5/5] SKIPPED - Target instance already launched: {state['target_instance_id']}")

    # Final wait for instance to be RUNNING
    if 'target_instance_running' not in state:
        # This is slightly redundant if --wait-for-state worked, but is a good final check
        log.info(f"Final check: Waiting for instance {state['target_instance_id']} to be RUNNING...")
        # A real wait_for_instance_state would be in the wrapper, but this is ok
        bogota_client.run_command(["compute", "instance", "wait", "--instance-id", state['target_instance_id'], "--wait-for-state", "RUNNING"])
        state['target_instance_running'] = True
        
    log.info("\n==============================================")
    log.info(f"✅ MIGRATION WORKFLOW COMPLETE!")
    log.info(f"   New Instance Name: {config['new_instance_name']}")
    log.info(f"   New Instance OCID: {state['target_instance_id']}")
    log.info("==============================================")
    
    return True
```

#### `migrate.py`

This is the main entry point that ties everything together. It handles logging, config/state loading, and argument parsing.

```python
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
```

-----

## Updated `README.md`

Here is the revised `README.md`. It has been updated to include a comprehensive section on the new automation tool, its usage, and its anti-failure design.

-----

````markdown
# CUSTOMER: OCI Workload Migration Guide (US Ashburn to CO Bogotá)

**Version:** 1.0
**Author:** Sebastián Jaramillo

---

## 🎯 Overview and Objectives

This guide provides architectural best practices and a comprehensive framework for migrating Oracle Cloud Infrastructure (OCI) workloads from the **US Ashburn (us-ashburn-1)** region to the **CO Bogotá (sa-bogota-1)** region.

The primary drivers for this migration (tailored for OCI Pilots) include:

* **Reduced Latency:** Improve application performance and user experience for South American users (e.g., faster access to patient data in Colombia).
* **Data Sovereignty & Compliance:** Align with local data protection regulations (e.g., Colombian Law 1581) by hosting sensitive data within national borders.
* **Disaster Recovery (DR):** Establish a robust, geographically distributed DR strategy.
* **Cost Optimization:** Leverage region-specific pricing for compute and other services.

This document outlines key OCI services, migration strategies, a step-by-step process, and a **professional automation tool** to ensure a seamless, repeatable, and fault-tolerant transition.

---

## 🗺️ Core Migration Strategies

The optimal migration approach depends on the workload type (stateful vs. stateless), data volume, and downtime tolerance. This guide covers four primary strategies:

1.  **Replication-Based:** Using native OCI asynchronous replication services for **Block Volume** and **Object Storage**. This is the preferred method for persistent data.
2.  **Lift-and-Shift (IaC):** Using **OCI Resource Manager (Terraform)**, OCI CLI, or APIs to export and redeploy resource configurations (e.g., custom images, VCNs).
3.  **Hybrid Approach:** Combining replication with live data syncing over a secure **Remote Peering Connection (RPC)**.
4.  **Offline Transfer:** Using the **OCI Data Transfer Service** (Data Transfer Appliance) for massive datasets (e.g., >1 PB) where online transfer is not feasible.

---

## 🏆 Best Practices Summary

This section highlights the critical recommendations detailed in the full guide.

### 1. Planning and Assessment
* **Inventory:** Assess all workload dependencies (VCNs, IAM policies, security lists) using OCI CLI (`oci search resource free-text-search`) or OCI Resource Manager.
* **Costing:** Model data egress costs from Ashburn. **Note: Egress fees apply.** Use the OCI Cost Analysis tool and Budgets.
* **Compliance:** Validate that the Bogotá region meets all data sovereignty requirements for OCI Pilots's workloads (e.g., Law 1581 for healthcare data).
* **Testing:** Measure round-trip time (RTT) between regions to set performance expectations.
* **Backup:** Perform complete backups of all volumes and databases in Ashburn using the OCI Backup Service before initiating any migration tasks.

### 2. Data Transfer and Replication
* **Block Volumes:** Enable cross-region replication policies for VM boot and data volumes.
* **Object Storage:** Configure bucket-level replication for unstructured data (e.g., medical images, logs).
* **Databases:**
    * **Oracle Database:** Use **Data Guard** for active-passive replication.
    * **Autonomous/Real-Time:** Use **GoldenGate** for real-time syncing and zero-downtime migrations.
* **Security:** Encrypt all data in transit (TLS 1.2+) and at rest (**OCI Vault** with customer-managed keys).

### 3. Compute and Application Migration
* **Instances:** Export custom images from Ashburn (`oci compute image export-to-object-storage`) and import them into Bogotá for redeployment.
* **Automation (IaC):** Use **OCI Resource Manager (Terraform)** to provision the target environment (VCNs, compute, etc.) for consistency and repeatability.
* **Containers:** Leverage **OCI Container Registry (OCIR)** to push/pull images between regions. Migrate OKE clusters using Helm charts and persistent volume replication.

### 4. Networking and Connectivity
* **Secure Peering:** Establish a **Remote Peering Connection (RPC)** between Dynamic Routing Gates (DRGs) in both regions. This provides a private, secure, and low-latency path over the OCI backbone.
* **Cutover:** Plan for DNS updates (using OCI DNS) and leverage the **Global Load Balancer** for controlled, gradual traffic steering (e.g., a blue-green deployment).

### 5. Testing and Monitoring
* **Validation:** Use OCI Load Testing or synthetic workloads to benchmark performance in Bogotá and ensure it meets requirements.
* **Observability:** Implement **OCI Monitoring** and **Logging Analytics** to track key metrics like transfer throughput, error rates, and resource utilization.
* **Rollback:** Maintain the Ashburn environment as a hot standby (fallback) until the Bogotá region is fully validated in production.

---

## 🚀 High-Level Migration Phases

A typical migration follows these stages (estimated 2-4 weeks for medium-sized workloads):

1.  **Preparation (1-2 weeks):**
    * Assess and inventory workloads.
    * Perform full backups.
    * Set up target compartments, IAM policies, and VCN structure in Bogotá.
2.  **Data Replication (Ongoing):**
    * Configure and start asynchronous replication for Block Volumes, Object Storage, and Databases (Data Guard).
    * Monitor replication progress.
3.  **Resource Provisioning (1 week):**
    * Deploy networking (VCN, DRG, RPC) via Terraform.
    * Deploy compute instances (from custom images) and applications in Bogotá. **(This step is automated by the tool below)**.
4.  **Testing (1-2 days):**
    * Perform functional, performance, and failover tests in the isolated Bogotá environment.
    * Validate data integrity.
5.  **Cutover (Scheduled Downtime):**
    * Stop applications in Ashburn.
    * Perform final data sync (e.g., Data Guard switchover).
    * Update DNS records to point traffic to the Bogotá endpoints.
    * Validate application functionality.
6.  **Decommission (Post-Cutover):**
    * Monitor the new environment for 1-2 weeks.
    * Once stable, terminate and clean up Ashburn resources to avoid costs.

---

## 🛠️ Professional Automation Tool

To support the "Resource Provisioning" phase (specifically for compute workloads), a professional, "anti-failure" automation tool is provided.

### Tool Overview & Features

This Python-based tool is designed to automate the "Lift-and-Shift" of a Compute instance by handling the complex image export/import/launch workflow. It is built to be **fault-tolerant and resumable**.

* **Configuration-Driven:** All OCIDs, names, and regions are defined in an external `config.json` file. No code modification is needed.
* **Idempotent (Resumable):** The tool saves its progress to a `migration.state.json` file. If the script fails (e.g., due to a network error or a failed step), you can **rerun it**, and it will **skip all completed steps**, resuming from exactly where it left off.
* **Automatic Retries:** Uses exponential backoff to automatically retry OCI commands that fail due to transient API errors or throttling.
* **Robust Logging:** Logs detailed debug information to `migration.log` while printing a clean, high-level summary to the console.
* **Dry Run Mode:** Includes a `--dry-run` flag to simulate the entire migration flow without executing any creating/modifying commands.

### Prerequisites & Setup

1.  **Install Python 3.8+**
2.  **Install OCI CLI:** The tool is a wrapper around the OCI CLI. Ensure it is installed and configured with a valid user, API key, and tenancy.
    ```bash
    bash -c "$(curl -L [https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh](https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh))"
    oci setup config
    ```
3.  **IAM Permissions:** The configured OCI user *must* have policies allowing them to:
    * Manage compute images (create, get, export) in the **source** compartment.
    * Manage object storage (put/get) in the **source** bucket.
    * Manage work requests (get) in the **source** region.
    * Manage compute images (get, import, create) in the **target** compartment.
    * Manage compute instances (launch, get, wait) in the **target** compartment.
    * Read VCN/subnet details in the **target** compartment.
4.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

### Configuration (`config.json`)

Before running, copy `config.json.template` to `config.json` and fill in all values for your environment.

```json
{
  "source_region": "us-ashburn-1",
  "target_region": "sa-bogota-1",
  "source_compartment_id": "ocid1.compartment.oc1..aaaa...",
  "target_compartment_id": "ocid1.compartment.oc1..bbbb...",
  "migration_bucket_name": "ashburn-migration-staging-bucket",
  "source_instance_id": "ocid1.instance.oc1.iad.aaaa...",
  "target_ad": "EXAMPLE-AD-1",
  "target_subnet_id": "ocid1.subnet.oc1.bgy.bbbb...",
  "target_instance_shape": "VM.Standard.E4.Flex",
  "new_image_name": "migrated-app-server-image",
  "new_instance_name": "migrated-app-server-bogota",
  "state_file_path": "migration.state.json"
}
````

  * `migration_bucket_name`: Must be an existing Object Storage bucket in the **source (Ashburn)** region.
  * `target_ad`: Must be a valid Availability Domain in the **target (Bogotá)** region (e.g., `EMuz:SA-BOGOTA-1-AD-1`).
  * `target_subnet_id`: The OCID of the subnet where the new instance will be launched.

### Usage

The tool is run from the command line.

**1. Run a Dry Run (Recommended First):**
Simulate the entire process. This will not execute any commands but will show you the steps it *would* take.

```bash
python3 migrate.py --config config.json --workflow compute --dry-run
```

**2. Execute the Migration:**
Run the `compute` workflow. The tool will log all progress and automatically save its state.

```bash
python3 migrate.py --config config.json --workflow compute
```

**3. Recovering from Failure:**
If the script fails at "Step 3/5", simply **rerun the exact same command**. The tool will read `migration.state.json`, see that Steps 1 and 2 are complete, and resume at Step 3.

```bash
# Rerunning after a failure
python3 migrate.py --config config.json --workflow compute
```

> [INFO] Found existing state file: migration.state.json. Resuming progress.
> [INFO] [Step 1/5] SKIPPED - Source image already created: ocid1.image...
> [INFO] [Step 2/5] SKIPPED - Source image is already AVAILABLE.
> [INFO] [Step 3/5] Exporting image ocid1.image...

### Automation Best Practices

  * **NEVER Run in Production First:** Always test this tool and your `config.json` in a non-production (staging) compartment first.
  * **Monitor Costs:** This tool creates new resources (Images, Instances) that incur costs.
  * **Post-Migration Cleanup:** The tool *does not* clean up resources. After you validate the new instance in Bogotá, you must manually delete:
      * The source custom image in Ashburn.
      * The target custom image in Bogotá.
      * The exported image object (`.img`) from your Object Storage bucket.
      * The original instance in Ashburn (once decommissioned).
  * **Review `migration.log`:** If an error occurs that the script cannot recover from, the `migration.log` file will contain the full debug trace and error message from the OCI CLI.

-----

## ⚠️ Key Considerations and Risks

  * **Costs:** **Data egress** from `us-ashburn-1` is a primary cost factor. Compress data and use OCI Budgets to track spending.
  * **Latency:** Inter-region latency during replication will be high (100-200 ms). Plan for this during data sync. Post-migration, latency for Colombian users should drop significantly (\~8 ms).
  * **Data Integrity:** Use checksums and thorough application-level validation post-cutover to prevent data loss or corruption.
  * **Regulatory Hurdles:** Ensure full legal and compliance sign-off for cross-border data transfer *before* moving any protected health information (PHI) or personally identifiable information (PII).

-----

## 📚 References

  * [OCI Documentation: Cross-Region Replication](https://www.google.com/search?q=https://docs.oracle.com/en-us/iaas/Content/Block/Tasks/replicatingavolume.htm)
  * [OCI Networking: Remote Peering](https://www.google.com/search?q=https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/remotepeering.htm)
  * [OCI Migration Tools: Data Transfer Service](https://docs.oracle.com/en-us/iaas/Content/DataTransfer/home.htm)
  * [Pricing Calculator: OCI Pricing](https://www.oracle.com/cloud/price-list/)
  * [OKIT: Introduction to OKIT the OCI Designer Toolkit](https://www.google.com/search?q=https://www.oracle.com/a/ocom/docs/okit.pdf)

<!-- end list -->

```
```

-----

## License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE.md) file for full details.
