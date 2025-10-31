# oci-workload-region-migrations
Migrate your workload between oci regions

# FEPEP: OCI Workload Migration Guide (US Ashburn to CO Bogotá)

**Version:** 1.0
**Author:** Sebastián Jaramillo

---

## 🎯 Overview and Objectives

This guide provides architectural best practices and a comprehensive framework for migrating Oracle Cloud Infrastructure (OCI) workloads from the **US Ashburn (us-ashburn-1)** region to the **CO Bogotá (sa-bogota-1)** region.

The primary drivers for this migration (tailored for FEPEP) include:

* **Reduced Latency:** Improve application performance and user experience for South American users (e.g., faster access to patient data in Colombia).
* **Data Sovereignty & Compliance:** Align with local data protection regulations (e.g., Colombian Law 1581) by hosting sensitive data within national borders.
* **Disaster Recovery (DR):** Establish a robust, geographically distributed DR strategy.
* **Cost Optimization:** Leverage region-specific pricing for compute and other services.

This document outlines key OCI services, migration strategies, and a step-by-step process to ensure a seamless transition with minimal downtime and high data integrity.

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
* **Compliance:** Validate that the Bogotá region meets all data sovereignty requirements for FEPEP's workloads (e.g., Law 1581 for healthcare data).
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
* **Secure Peering:** Establish a **Remote Peering Connection (RPC)** between Dynamic Routing Gateways (DRGs) in both regions. This provides a private, secure, and low-latency path over the OCI backbone, avoiding the public internet.
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
    * Deploy compute instances (from custom images) and applications in Bogotá.
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

## ⚠️ Key Considerations and Risks

* **Costs:** **Data egress** from `us-ashburn-1` is a primary cost factor. Compress data and use OCI Budgets to track spending.
* **Latency:** Inter-region latency during replication will be high (100-200 ms). Plan for this during data sync. Post-migration, latency for Colombian users should drop significantly (~8 ms).
* **Data Integrity:** Use checksums and thorough application-level validation post-cutover to prevent data loss or corruption.
* **Regulatory Hurdles:** Ensure full legal and compliance sign-off for cross-border data transfer *before* moving any protected health information (PHI) or personally identifiable information (PII).

---

## 📚 References

* [OCI Documentation: Cross-Region Replication](https://docs.oracle.com/en-us/iaas/Content/Block/Tasks/replicatingavolume.htm)
* [OCI Networking: Remote Peering](https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/remotepeering.htm)
* [OCI Migration Tools: Data Transfer Service](https://docs.oracle.com/en-us/iaas/Content/DataTransfer/home.htm)
* [Pricing Calculator: OCI Pricing](https://www.oracle.com/cloud/price-list/)
* [OKIT: Introduction to OKIT the OCI Designer Toolkit](https://www.oracle.com/a/ocom/docs/okit.pdf)


-----

## License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE.md) file for full details.
