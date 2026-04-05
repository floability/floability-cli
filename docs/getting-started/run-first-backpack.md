# Run Your First Backpack

This guide walks you through running the matrix multiplication example,
a simple distributed workflow that multiplies pairs of matrices in
parallel across workers.

By the end you will have run your first backpack and understand what
each of its components does.


## Before you begin

Complete [Installation](installation.md) first. Then verify:

```bash
floability --version
```

If the command is not found, make sure `floability-env` is active:

```bash
conda activate floability-env
```



## Get the Example Backpacks

Floability example backpacks are stored in a separate repository. Clone it:

```bash
git clone https://github.com/floability/floability-examples.git
cd floability-examples
```

## Run the Backpack

The examples repository contains multiple backpacks. You can run any of them by replacing `<example-backpack-path>` with the path to a backpack folder in the repository. For this guide, we run the `matrix-multiplication` backpack:

```bash
floability run --backpack matrix-multiplication
```

If you are running this command from an HPC cluster login node, you can also specify a batch type to submit worker jobs to the cluster scheduler. For example, on a Slurm cluster:

```bash
floability run --backpack matrix-multiplication --batch-type slurm
```

See [Deployment Overview](../deployment/index.md) for more on running on HPC clusters.

Then follow the on-screen instructions to open the Jupyter Notebook and execute the workflow.

You should see instructions like this in the terminal:

```
[jupyter] JupyterLab is running on port 8888 on 10.32.85.31.

    You can access it using one of the following URLs:
    local:  http://localhost:8888/lab/?token=9bc3277e77815110b5bd463b0c9467ad2f8eb7b60bbad97e
    remote: http://10.32.85.31:8888/lab/?token=9bc3277e77815110b5bd463b0c9467ad2f8eb7b60bbad97e

    If you are on a remote machine and it doesn't allow direct access to the port, you can create an SSH tunnel:

    1. Open a terminal and run the following command:
       ssh -L localhost:8888:localhost:8888 mislam5@10.32.85.31

    2. Open a web browser and enter the following URL:
       http://localhost:8888/lab/?token=9bc3277e77815110b5bd463b0c9467ad2f8eb7b60bbad97e
```

If you are running on a remote machine, follow the instructions to create an SSH tunnel and access Jupyter.

**Note:** On some clusters, the IP address shown in the instructions may not work. In that case, replace it with the domain name or IP address you used to SSH into the cluster.


## Understanding the Backpack Structure

A backpack is a directory that contains all the components needed to run a workflow. It typically includes a workflow file, an environment file, and optional data and compute specification files. The goal is to package everything needed for a reproducible run in one place.

For example, the `matrix-multiplication` backpack has the following structure:

```
matrix-multiplication/
├── compute
│   └── compute.yml
├── data
│   └── data.yml
├── software
│   └── environment.yml
└── workflow
    └── matrix-multiplication.ipynb
```

The `environment.yml` file defines the software environment, including Python version and dependencies. The `compute.yml` file defines the compute resources needed to run the workflow. The `data.yml` file specifies input datasets and their source locations. Finally, the `matrix-multiplication.ipynb` file contains the Jupyter Notebook that implements the workflow.

To learn more about how backpacks work and how to create your own, see [Concepts → Backpacks](../concepts/backpacks.md).

To learn more about data specifications and how Floability handles datasets, see [Reference → Data Specification](../reference/data-spec.md).

## Instances (reusable sandboxes)

When you run a backpack, it does not run directly from the backpack directory. Instead, Floability creates an "instance," a self-contained run directory with workflow, logs, metrics, metadata, and an extracted environment. You can reuse instances to avoid rebuilding environments and to manage multiple runs more easily.

After the run completes, final notebooks are copied back to the backpack directory.

## Default Directories and Caching

By default, Floability creates a directory named `floability-base-dir` in the user's home directory to store instances, Conda environments, and data files.


By default, data is cached in `<base-dir>/floability-data-cache`, which is `~/floability-base-dir/floability-data-cache` when `--base-dir` is not set.

You can change the base directory using the `--base-dir` flag when running a backpack. You can change only the data cache directory using the `--data-cache-dir` flag. For example:

```bash
floability run --backpack matrix-multiplication --data-cache-dir /scratch/mislam/floability-data-cache
```


## Next Steps

- Learn backpack structure: [Backpacks](../concepts/backpacks.md)
- Deploy on clusters: [Deployment Overview](../deployment/index.md)