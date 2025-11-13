# Deployment

This page shows how to run Floability locally and on HPC clusters, and links to site-specific instructions.

---

## Local (Single Machine)

Run a backpack locally (no scheduler) using the local batch type or skip batch type altogether.

```bash
floability run --backpack <backpack-root> --batch-type local
```

Or simply:

```bash
floability run --backpack <backpack-root>

You can also manage workers explicitly:

```bash
floability workers start --instance <name-or-path> --batch-type local
floability workers status --instance <name-or-path>
floability workers stop --instance <name-or-path>
```

Learn more about worker architecture and configuration: [Concepts → Workers](../concept/workers.md).
``` 


## HPC Clusters (Batch Systems)

To deploy floability backpacks on HPC clusters, setup floability on the cluster login node and use the `--batch-type` flag to submit worker jobs to the batch scheduler. Supported batch types are **HTCondor**, **UGE**, and **Slurm**. 

For example, to run the matrix multiplication backpack on an HTCondor cluster, use:     

```bash 
floability run --backpack <backpack-root> --batch-type condor
``` 

To run on UGE:

```bash 
floability run --backpack <backpack-root> --batch-type uge
```
To run on Slurm:

```bash 
floability run --backpack <backpack-root> --batch-type slurm
```

If you prefer to create and reuse instances explicitly:

```bash
floability instance create --backpack <backpack-root>
floability instance list
floability run --instance <short-name>
floability instance stop <short-name>
```

## Site-specific Instructions

Although the general instructions mentioned above should work in most HPC clusters, every HPC site has different settings, permissions, and configurations. You may need to adjust some settings when running floability at different sites. Here are site-specific instructions for sites where we have tested floability:

- [ND CRC (Notre Dame)](nd-crc.md)
- [OSG (Open Science Grid)](osg.md)
- [Purdue Anvil](purdue-anvil.md)
- [UT Stampede3](ut-stampede3.md)