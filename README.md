#  OCI Workload Migration Guide (US Ashburn to CO Bogotá)

**Version:** 2.0
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

```
*migration_bucket_name:* Must be an existing Object Storage bucket in the source (Ashburn) region.

*target_ad:* Must be a valid Availability Domain in the target (Bogotá) region (e.g., EMuz:SA-BOGOTA-1-AD-1).

*target_subnet_id:* The OCID of the subnet where the new instance will be launched.

**Usage**
The tool is run from the command line.

1. Run a Dry Run (Recommended First): Simulate the entire process. This will not execute any commands but will show you the steps it would take.

```Bash

python3 migrate.py --config config.json --workflow compute --dry-run
```
2. Execute the Migration: Run the compute workflow. The tool will log all progress and automatically save its state.

```Bash

python3 migrate.py --config config.json --workflow compute
```
3. Recovering from Failure: If the script fails at "Step 3/5", simply rerun the exact same command. The tool will read migration.state.json, see that Steps 1 and 2 are complete, and resume at Step 3.

```Bash
# Rerunning after a failure
python3 migrate.py --config config.json --workflow compute
```
[INFO] Found existing state file: migration.state.json. Resuming progress. [INFO] [Step 1/5] SKIPPED - Source image already created: ocid1.image... [INFO] [Step 2/5] SKIPPED - Source image is already AVAILABLE. [INFO] [Step 3/5] Exporting image ocid1.image...

## **Automation Best Practices**
* NEVER Run in Production First: Always test this tool and your config.json in a non-production (staging) compartment first.

* Monitor Costs: This tool creates new resources (Images, Instances) that incur costs.

* Post-Migration Cleanup: The tool does not clean up resources. After you validate the new instance in Bogotá, you must manually delete:

* The source custom image in Ashburn.

* The target custom image in Bogotá.

* The exported image object (.img) from your Object Storage bucket.

* The original instance in Ashburn (once decommissioned).

* Review migration.log: If an error occurs that the script cannot recover from, the migration.log file will contain the full debug trace and error message from the OCI CLI.

## ⚠️ Key Considerations and Risks
 *Costs:* Data egress from us-ashburn-1 is a primary cost factor. Compress data and use OCI Budgets to track spending.

 *Latency:* Inter-region latency during replication will be high (100-200 ms). Plan for this during data sync. Post-migration, latency for Colombian users should drop significantly (~8 ms).

 *Data Integrity:* Use checksums and thorough application-level validation post-cutover to prevent data loss or corruption.

 *Regulatory Hurdles:* Ensure full legal and compliance sign-off for cross-border data transfer before moving any protected health information (PHI) or personally identifiable information (PII).

-----
## License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE.md) file for full details.
