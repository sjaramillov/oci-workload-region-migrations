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
