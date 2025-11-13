# Getting Started
This guide walks you through installing Floability, setting up a development environment, and running your first workflow using the Floability CLI.

## Installation

### Prerequisites

Floability requires Conda 24.0 or later.

You can check your Conda version with:

```bash
conda --version
```

If Conda is not installed or is outdated, install one of the lightweight distributions below:

- [Miniforge Installation](https://github.com/conda-forge/miniforge) 
- [Miniconda Installation](https://docs.conda.io/en/latest/miniconda.html)

### Install Floability via Conda
Floability is available on conda-forge. To install it, use the following command:

```bash
conda install -c conda-forge floability
```

It is recommended to create a new Conda environment for Floability to avoid dependency conflicts:

```bash
conda create -n floability-env -c conda-forge floability
conda activate floability-env
```

```bash
conda create -n floability-env -c conda-forge floability
conda activate floability-env
```

### Install Floability from Source
For development or to get the latest features, you can install Floability from source code using the following steps:

Clone the repository and move into it:

```bash
git clone https://github.com/floability/floability-cli.git
cd floability-cli
``` 

Create a Conda environment using the provided `environment.yml` file:

```bash
conda env create -f environment.yml
```
Activate the new environment:

```bash
conda activate floability-env
```

Install Floability in editable mode:

```bash
pip install -e .    
``` 



## Running Your First Backpack
After installing Floability, verify the installation by checking the version:

```bash
floability --version
``` 

If the command returns the version number, Floability is installed correctly. Now you are ready to run your first backpack! We will use the matrix multiplication example backpack included in the floability-cli repository. If you cloned the repository earlier, you can run the example directly. If not, clone the repository first:

```bash
git clone https://github.com/floability/floability-cli.git
cd floability-cli
```
Run the matrix multiplication backpack using the following command:

```bash
floability run --backpack example/matrix-multiplication
```

Then follow the on-screen instructions to open the Jupyter Notebook and execute the workflow.

## Understanding the Backpack Structure
A backpack is a directory that contains all the necessary components to run a workflow. It typically includes a workflow file, an environment file, and any necessary data or compute-related files. The idea is to encapsulate everything needed to run a specific task or example in one place, making it easy to share and reproduce.

The matrix multiplication example has the following structure:

```
example/matrix-multiplication/
├── compute
│   └── compute.yml
├── software
│   └── environment.yml
└── workflow
    └── matrix-multiplication.ipynb
```

In addition, a backpack may include a **data specification** file at `data/data.yml`, which defines input datasets, source locations (local, remote, or federated), and verification policies. Floability uses this file to automatically stage and verify input data before running workflows.

To learn more about how backpacks work and how to create your own, see [Concepts → Backpacks](../concept/backpack.md).  

To learn more about data specifications and how Floability handles datasets, see [Reference → Data Specification](../reference/data.md).

## Instances (reusable sandboxes)

Floability creates an "instance" — a self-contained run directory with workflow, logs, metrics, metadata, and an extracted environment — from your backpack. You can reuse instances to avoid rebuilding environments and easily manage multiple runs.

Common commands:

```bash
# Create an instance from a backpack (no Jupyter yet)
floability instance create --backpack <backpack-root>

# List registered instances (short names and status)
floability instance list --show-paths

# Run on an existing instance by short name or path
floability run --instance <name-or-path>

# Stop a running instance (Jupyter/manager/workers)
floability instance stop <name-or-path>
```

Learn more: [Concepts → Instances](../concept/instances.md) and [Reference → Instance registry](../reference/instance-registry.md). For full command details, see [Reference → CLI](../reference/cli.md).


## Running on HPC Clusters
To deploy workers on an HPC cluster, use the `--batch-type` flag.  
This submits worker jobs to a batch scheduler such as **HTCondor**, **UGE**, or **Slurm**.

For example, to run the matrix multiplication backpack on an HTCondor cluster, use:     

```bash 
floability run --backpack example/matrix-multiplication --batch-type condor
```

Run this command from a cluster login node. This command will start the manager on HPC login node and submit worker jobs to the HTCondor scheduler.

For detailed site-specific instructions and examples, see [Deployment → HPC Clusters](../deployment/index.md).

## Next Steps

1. **Learn and Create a Backpack**  
   Understand how backpacks are structured and create your own by following the examples.  
   → See [Concepts → Backpacks](../concept/backpack.md)

2. **Explore Examples**  
   Try the sample workflows to see how Floability executes notebooks across different environments.  
   → Visit the [Floability Examples Repository](https://github.com/floability/floability-examples)

3. **Deploy Your Backpack on an HPC Cluster**  
   Run your workflow on real compute systems using the `--batch-type` option.  
   → See [Deployment → HPC Clusters](../deployment/index.md)
