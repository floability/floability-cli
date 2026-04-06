# Create Your First Backpack

This guide walks you through creating a backpack from scratch. By the end,
you will have a working backpack ready to run workflows on distributed workers.


## Before you begin

Complete [Installation](installation.md) first. Verify your setup:

```bash
floability --version
floability backpack --help
```


## What is a Backpack?

A **backpack** is a self-contained directory bundle that contains everything
needed to run a reproducible workflow:

- **Workflow**: A Jupyter notebook or Python script that defines the computation
- **Software**: A `conda` environment file specifying all dependencies
- **Compute**: Resource requirements (number of workers, cores, memory)
- **Data** (optional): Input datasets and their source locations

The goal is to package all of these together so your workflow runs
consistently everywhere — your laptop, a university cluster, or cloud.


## Creating a Backpack

You have two options:

1. **Bootstrap Mode** (recommended for beginners): Use a template to generate a starter backpack, then customize it
2. **Custom Mode**: Import your own notebook and configure dependencies interactively


### Option 1: Bootstrap Mode (Recommended)

The bootstrap command scaffolds a complete backpack structure with example code,
letting you focus on editing the workflow rather than creating files from scratch.

#### Create a backpack from the `taskvine` template:

```bash
floability backpack init --name my-first-analysis --from-template taskvine
```

This creates a directory called `my-first-analysis/` with the following structure:

```
my-first-analysis/
├── compute
│   └── compute.yml        # Worker resource specifications
├── software
│   └── environment.yml    # Conda dependencies
└── workflow
    └── my-first-analysis.ipynb  # Your workflow
```

#### What the taskvine template generates

The template creates a ready-to-run 8-cell notebook that demonstrates
the distributed computing pattern:

**Cell 1: Imports**
```python
import ndcctools.taskvine as tvine
```

**Cell 2: Define worker function**
```python
def process_item(item):
    """Worker function that runs on distributed nodes."""
    return item * 2
```

**Cell 3-6: Setup & execute work**
```python
# Create TaskVine manager
manager = tvine.Manager(port=MANAGER_PORT)

# Submit tasks to workers
for item in range(10):
    task = tvine.Task(process_item, item)
    manager.submit(task)

# Retrieve results
results = [task.output for task in manager.wait_for_completion()]
```

#### What you need to edit

Edit `my-first-analysis.ipynb` to replace the example `process_item()` function
with your own logic. The template handles:
- TaskVine manager setup ✓
- Worker task submission ✓
- Result collection ✓

You only need to customize:
- `process_item()` function: your actual computation
- Input data: change `range(10)` to your dataset
- Result post-processing: add any final analysis after `wait_for_completion()`

**Tip:** Open the notebook in Jupyter to test your changes locally before running:
```bash
jupyter lab my-first-analysis/workflow/my-first-analysis.ipynb
```

#### Create a backpack with optional data handling:

If your workflow uses input data files, use the `taskvine-data` template:

```bash
floability backpack init --name my-data-analysis --from-template taskvine-data
```

This generates the same notebook structure but also creates:

```
my-data-analysis/
├── compute
│   └── compute.yml
├── data
│   └── data.yml          # Data specification (you configure this)
├── software
│   └── environment.yml
└── workflow
    └── my-data-analysis.ipynb
```

The `data.yml` file lets you specify where input files come from (S3, HTTP, local directory).
See [Data Specification](../reference/data-spec.md) for how to configure it.


### Option 2: Custom Mode (Import Your Own Workflow)

If you already have a notebook or script, bootstrap can import it and help you
configure the environment interactively.

#### Import an existing notebook:

```bash
floability backpack init --name my-existing-analysis --from-workflow /path/to/your/notebook.ipynb
```

This prompts you through several questions:

**1. Environment configuration:**
```
[floability] Environment Configuration
--------------------------------------------------
Options:
  1. Path to existing environment.yml
  2. Comma-separated conda packages (e.g., numpy,pandas)
  3. Comma-separated pip packages (e.g., requests,pyyaml)
  4. Skip (barebones: python + ndcctools)

Select option (1-4, default 4):
```

Choose based on your workflow:
- **Option 1**: If you have an existing `environment.yml` from another project
- **Option 2**: For conda packages (recommended for most scientific work)
  - Example: `numpy,scipy,pandas,scikit-learn`
- **Option 3**: For pip packages (useful if dependencies aren't on conda-forge)
  - Example: `plotly,altair`
- **Option 4**: Default barebones (includes Python + TaskVine, you can edit later)

**2. Data configuration:**
```
[floability] Data Configuration
--------------------------------------------------
Create data.yml? (y/n, default n):
```

Choose "y" if your workflow loads data files. You'll configure `data.yml` later.

#### Customize the generated backpack:

After import, the backpack is ready but you may need to adjust:
- **environment.yml**: Add missing dependencies
  ```yaml
  name: my-existing-analysis
  channels:
    - conda-forge
  dependencies:
    - python
    - numpy
    - scipy
    - ndcctools
  ```
- **compute.yml**: Adjust worker requirements for your workload
  ```yaml
  vine_factory_config:
    min_workers: 2
    max_workers: 10
    cores_per_worker: 4
    memory_per_worker: 4096      # MB
    disk_per_worker: 10000       # MB
  ```
- **Notebook**: Wrap your computation in TaskVine tasks (see template example)


## Best Practices Before Creating a Backpack

Before you run `floability backpack init`, organize your work:

### 1. **Know your dependencies**
Identify all Python packages your workflow needs:
```bash
# If you have an existing environment
conda list -e > requirements.txt

# Or manually list them
pip freeze | grep -E "numpy|scipy|pandas"
```

### 2. **Prepare input data locations (if applicable)**
Know where input files are and how to access them:
- **Local directory**: Path on disk to files
- **HTTP**: Public download URL
- **S3**: S3 bucket path (requires credentials in `~/.aws/credentials`)
- **Custom directory service**: Pelican or other federation URLs

See [Data Specification](../reference/data-spec.md) for details.

### 3. **Identify your compute footprint**
Estimate what resources each task needs:
- **Cores**: How many CPU cores per worker task?
  - Rule of thumb: 1-4 for typical data processing
- **Memory**: How much RAM per worker?
  - Rule of thumb: 2-8 GB for typical analysis
- **Total workers**: How many parallel tasks at once?
  - Start conservative (2-4), scale up after testing

### 4. **Test your computation locally first**
Before creating a backpack, verify your workflow works:
```bash
# Make sure dependencies install
conda install -c conda-forge numpy scipy pandas

# Run your notebook or script once locally
jupyter lab your-notebook.ipynb
python your-script.py
```

This prevents wasting time debugging backpacks when the issue is in your code.

### 5. **Plan file organization (optional)**
For complex workflows with multiple scripts or data sources:
```
my-analysis/
├── README.md                    # Document your workflow
├── compute/
│   └── compute.yml
├── software/
│   └── environment.yml
├── workflow/
│   ├── my-analysis.ipynb        # Main entry point
│   └── helpers.py               # Supporting utilities
└── data/
    └── data.yml
```

You can add extra files (like `helpers.py`) to the `workflow/` directory,
and they'll be available when your notebook runs.


## Validate Your Backpack

After creating your backpack, validate the structure:

```bash
floability backpack validate my-first-analysis
```

This checks:
- ✓ Required directories exist (workflow, software, compute)
- ✓ Workflow file is present (.ipynb, .py, or .sh)
- ✓ All YAML files are valid and parseable

Output:
```
[floability] Validating backpack: my-first-analysis
[floability] Status: VALID
[floability] Workflow: my-first-analysis.ipynb
[floability] Has data specification: no
```

If validation fails, read the errors carefully — they point to missing files or invalid YAML.


## Next Steps

1. **Run your backpack**: [Run Your First Backpack](run-first-backpack.md)
2. **Understand backpack concepts**: [Backpacks](../concepts/backpacks.md)
3. **Configure data**: [Data Specification](../reference/data-spec.md)
4. **Deploy on clusters**: [Deployment Overview](../deployment/index.md)
