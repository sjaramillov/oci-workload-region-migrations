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
