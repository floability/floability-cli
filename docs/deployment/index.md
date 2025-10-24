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
``` 


## HPC Clusters (Batch Systems)

To deploy floability backpacks on HPC clusters, setup floability on the cluster login node and use the `--batch-type` flag to submit worker jobs to the batch scheduler.  Supported batch types are **HTCondor**, **UGE**, and **Slurm**. 

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

## Site-specific Instructions

Although the general instructions mentioned above should work in most HPC clusters, every HPC site has different settings, permissions, and configurations. You may need to adjust some settings when running floability at different sites. Here are site-specific instructions for sites where we have tested floability:

- [ND CRC (Notre Dame)](nd-crc.md)
- [OSG (Open Science Grid)](osg.md)
- [Purdue Anvil](purdue-anvil.md)
- [UT Stampede3](ut-stampede3.md)