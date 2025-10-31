#!/usr/bin/env python3

"""
================================================================================
OCI Workload Migration Automation Script (Ashburn to Bogotá)
================================================================================

Version: 1.0
Author: Sebastián Jaramillo (Based on Customer Migration Guide)


**DISCLAIMER:**
This script is provided as an automation template and a proof-of-concept.
It is NOT intended for production use without thorough review, customization,
and testing in a non-production environment.

The author and provider assume NO liability for any data loss, downtime,
or unexpected costs incurred by using this script.

**Prerequisites:**
1.  OCI CLI is installed and configured with appropriate user credentials
    and permissions for both source and target regions.
2.  The target Compartment, VCN, and Subnet must already exist in the
    target region (Bogotá).
3.  The source Instance to be migrated must be running or stopped (not terminated).
4.  An Object Storage bucket for staging the exported image must exist in the
    SOURCE region.

"""

import subprocess
import json
import time
import sys

# --- ⚙️ CONFIGURATION (MODIFY THESE VALUES) ---

# == Source Region (Ashburn) ==
SOURCE_REGION = "us-ashburn-1"
SOURCE_COMPARTMENT_ID = "ocid1.compartment.oc1..aaaa..."  # Compartment of source instance
SOURCE_INSTANCE_ID = "ocid1.instance.oc1.iad.aaaa..."     # Instance to migrate
MIGRATION_BUCKET_NAME = "ashburn-migration-staging-bucket" # Bucket in Ashburn for image export

# == Target Region (Bogotá) ==
TARGET_REGION = "sa-bogota-1"
TARGET_COMPARTMENT_ID = "ocid1.compartment.oc1..bbbb..."  # Compartment for new resources
TARGET_SUBNET_ID = "ocid1.subnet.oc1.bgy.bbbb..."         # Subnet for the new instance
TARGET_INSTANCE_SHAPE = "VM.Standard.E4.Flex"            # Shape for the new instance
TARGET_AD = "EXAMPLE-AD-1" # Target AD in Bogotá (e.g., AD-1)

# == Naming ==
NEW_IMAGE_NAME = "migrated-app-server-image"
NEW_INSTANCE_NAME = "migrated-app-server-bogota"

# --- ⚙️ END OF CONFIGURATION ---


def run_oci_command(command, region=None):
    """
    Runs an OCI CLI command and returns the parsed JSON output.
    Handles errors and provides verbose output.
    """
    if region:
        command.extend(["--region", region])

    print(f"  [EXEC] {' '.join(command)}", flush=True)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8'
        )

        if result.stderr:
            print(f"  [WARN] {result.stderr}", file=sys.stderr, flush=True)

        if not result.stdout:
            print("  [INFO] Command returned no output (e.g., a create policy).")
            return None

        return json.loads(result.stdout)

    except subprocess.CalledProcessError as e:
        print(f"\n--- ❌ OCI CLI ERROR ---", file=sys.stderr, flush=True)
        print(f"  Command: {' '.join(e.cmd)}", file=sys.stderr, flush=True)
        print(f"  Return Code: {e.returncode}", file=sys.stderr, flush=True)
        print(f"  Stderr: {e.stderr}", file=sys.stderr, flush=True)
        print(f"  Stdout: {e.stdout}", file=sys.stderr, flush=True)
        print(f"--- END ERROR ---\n", file=sys.stderr, flush=True)
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"  [ERROR] Failed to decode JSON from command output: {result.stdout}", file=sys.stderr, flush=True)
        sys.exit(1)

def wait_for_image_state(image_id, region, target_state="AVAILABLE", poll_interval=30):
    """Polls an OCI compute image until it reaches the target state."""
    print(f"\n⏳ Waiting for image {image_id} to become '{target_state}' in {region}...")
    current_state = ""
    while current_state != target_state:
        try:
            command = ["oci", "compute", "image", "get", "--image-id", image_id]
            data = run_oci_command(command, region)
            current_state = data.get("data", {}).get("lifecycle-state")
            print(f"  ...current state: {current_state} (waiting for {target_state})")
            if current_state == target_state:
                print(f"✅ Image is now {target_state}.")
                return data
            elif current_state in ("FAULTED", "DELETED"):
                print(f"  [ERROR] Image entered a failure state: {current_state}", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"  [WARN] Error checking image state: {e}. Retrying...")
        
        time.sleep(poll_interval)

def wait_for_instance_state(instance_id, region, target_state="RUNNING", poll_interval=20):
    """Polls an OCI compute instance until it reaches the target state."""
    print(f"\n⏳ Waiting for instance {instance_id} to become '{target_state}' in {region}...")
    current_state = ""
    while current_state != target_state:
        try:
            command = ["oci", "compute", "instance", "get", "--instance-id", instance_id]
            data = run_oci_command(command, region)
            current_state = data.get("data", {}).get("lifecycle-state")
            print(f"  ...current state: {current_state} (waiting for {target_state})")
            if current_state == target_state:
                print(f"✅ Instance is now {target_state}.")
                return data
            elif current_state in ("TERMINATED", "TERMINATING", "FAULTED"):
                print(f"  [ERROR] Instance entered a failure state: {current_state}", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"  [WARN] Error checking instance state: {e}. Retrying...")
        
        time.sleep(poll_interval)

def wait_for_work_request(work_request_id, region, poll_interval=30):
    """Polls an OCI work request until it succeeds."""
    print(f"\n⏳ Waiting for work request {work_request_id} to SUCCEED in {region}...")
    status = ""
    while status != "SUCCEEDED":
        command = ["oci", "work-requests", "work-request", "get", "--work-request-id", work_request_id]
        data = run_oci_command(command, region)
        status = data.get("data", {}).get("status")
        percent = data.get("data", {}).get("percent-complete", 0)
        print(f"  ...current status: {status} ({percent}%)")

        if status == "SUCCEEDED":
            print(f"✅ Work request SUCCEEDED.")
            return data
        elif status in ("FAILED", "CANCELED"):
            print(f"  [ERROR] Work request failed with status: {status}", file=sys.stderr)
            sys.exit(1)

        time.sleep(poll_interval)


def migrate_compute_instance():
    """
    Main workflow to migrate a compute instance from Ashburn to Bogotá
    using the Image Export/Import method.
    """
    print("==============================================")
    print(f"🚀 Starting Compute Instance Migration")
    print(f"   From: {SOURCE_INSTANCE_ID} ({SOURCE_REGION})")
    print(f"   To:   {NEW_INSTANCE_NAME} ({TARGET_REGION})")
    print("==============================================")

    # --- Step 1: Create Custom Image from Source Instance ---
    print(f"\n[Step 1/4] Creating custom image from {SOURCE_INSTANCE_ID} in {SOURCE_REGION}...")
    image_create_cmd = [
        "oci", "compute", "image", "create",
        "--compartment-id", SOURCE_COMPARTMENT_ID,
        "--instance-id", SOURCE_INSTANCE_ID,
        "--display-name", NEW_IMAGE_NAME
    ]
    image_data = run_oci_command(image_create_cmd, SOURCE_REGION)
    source_image_id = image_data["data"]["id"]
    
    # Wait for the image to become available
    wait_for_image_state(source_image_id, SOURCE_REGION, "AVAILABLE")

    # --- Step 2: Export Custom Image to Object Storage ---
    print(f"\n[Step 2/4] Exporting image {source_image_id} to bucket {MIGRATION_BUCKET_NAME}...")
    image_export_cmd = [
        "oci", "compute", "image", "export", "to-object-storage",
        "--image-id", source_
