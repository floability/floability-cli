# Floability Backpack
A Floability "backpack" is a self-contained package that includes everything you need to run a Jupyter notebook at a large-scale computing facility. Think of it as your “all-in-one” kit—containing the notebook, required software, data, and compute specifications. (Everything you need for the day, including your lunch.) It contains four components:

1. **Workflow** – the notebook or script
2. **Software** – a self-contained Conda environment description
3. **Data** – declarative data sources and integrity checks
4. **Compute** – resource requirements for scalable execution

With these pieces, a workflow becomes portable across laptops, clusters, and cloud systems—without modifying the notebook itself.


## From backpack to instance
Floability consumes a backpack and creates a runnable instance. An instance contains:
- a built Conda environment from the backpack’s software spec
- a resolved data set from the backpack’s data spec
- a worker factory configured from the backpack’s compute spec
- the original notebook or script placed in a workflow directory

A floabilty instance is created when you pefrom a `floability run --backpack <path>` or `floability instance create --backpack <path>`. You can then start Jupyter and workers against the instance.

In practice the floability instance is directory with subdirectories for workflow, logs, metrics, and metadata. See [Concepts → Instances](./instances.md) for details.

## Creating a Floability Backpack
A backpack is simply a directory containing four specification files:
```
<backpack-root>/
├── workflow/
│   └── my_notebook.ipynb
├── software/
│   └── environment.yml
├── data/
│   └── data.yml
└── compute/
    └── compute.yml
```
Each component is described below.

### 1. Workflow
The workflow is typically a Jupyter notebook file (`.ipynb`) placed in the `workflow/` subdirectory. This notebook contains the code you want to run in a distributed manner. The goal is portability, so notebooks should:
- Avoid hardcoded manager names: Use environment variables (e.g., for TaskVine) instead of fixed strings.
- Data references: Instead of absolute paths, refer to data sources by the target_path defined in the backpack’s configuration files (e.g., data.yml)
After making these adjustments, place the finalized notebook file into the backpack.

### 2. Software (environments)
The software component defines the exact software stack using a single environment.yml.
Floability will build and cache this environment on the cluster. The environment.yml file follows standard Conda syntax. Floability will add some additional packages automatically (e.g., Jupyter, ndcctools, cloudpickle) to support distributed execution.
#### Example `environment.yml`

```yaml
name: myenv
channels:
  - conda-forge
dependencies:
  - python=3.12
  - numpy
  - dask
```

### 3. Data
The data.yml file defines all datasets required by the workflow, including:
- Source locations (local paths, HTTP URLs, S3 buckets, etc.)
- Expected size and checksums for integrity verification
- Target paths within the instance workflow directory
- Multiple profiles for different data configurations (e.g., small test data vs full datasets)  

For more details on the data specification format and options, see [Reference → Data Specification](../reference/data.md).

#### Example `data.yml`

```yaml
schema_version: 1.0
default_profile: gutenberg_data

profiles:
  gutenberg_data:
    policy:
      retry_attempts: 3
      timeout: 60
      size_tolerance_bytes: 1024

    data:
      - name: gatsby
        source_type: http
        source: https://www.gutenberg.org/cache/epub/64317/pg64317.txt
        content_type: text/plain
        expected_size: 306594
        checksum: sha256:e6b7897aa8498b8dac4df0664827f857bc01135c3d9311adb820979bbc44b763
        target_path: data/pg64317.txt

      - name: frankenstein
        source_type: http
        source: https://www.gutenberg.org/files/84/84-0.txt
        content_type: text/plain
        expected_size: 421633
        checksum: sha256:06c37d2c52d208d3d81eb12c3b10b5edbd7728b73554325ddceadbe2fb427e77
        target_path: data/frankenstein.txt

      - name: alice
        source_type: http
        source: https://www.gutenberg.org/files/11/11-0.txt
        content_type: text/plain
        expected_size: 151191
        checksum: sha256:a3a27f8edbf7fcd9b8ba8435494440e24952deaa3e2f2d65192d4cb7ca403754
        target_path: data/alice.txt

      - name: shakespeare
        source_type: http
        source: https://www.gutenberg.org/cache/epub/100/pg100.txt
        content_type: text/plain
        expected_size: 5638525
        checksum: sha256:4291cb282e90f6580fa683148f7c94a55276acb1757d725a2e84caf8c00cb9a5
        target_path: data/shakespeare_complete.txt

```

### 4. Compute
The compute specification (`compute.yml`) describes the HPC resources you want for running the notebook:

- Number of workers (e.g., Vine workers, Dask workers, etc.)
- CPUs per worker, memory, disk space
- Credential requirements (e.g., key locations or authentication tokens)

By providing a clear blueprint of desired resources, Floability can allocate the appropriate compute environment when launching your notebook.

#### Example `compute.yml`
```yaml
vine_factory_config:
  min-workers: 2
  max-workers: 4
  cores: 4
  memory: 1024
  disk: 2000
```

See [Concepts → Workers](./workers.md) for how compute settings are applied and how to manage the worker factory.

## Summary
Putting it all together, a Floability Backpack encapsulates:

- The notebook code to run
- The exact software environment needed
- The datasets required, with integrity checks
- The compute resources to request for execution