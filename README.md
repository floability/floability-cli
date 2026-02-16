# Floability CLI

Floability is available on conda-forge. To install it, use the following command:

```bash
conda install -c conda-forge floability
```

If you do not have Conda installed, you can install it via Miniconda or Miniforge. They are both light versions of Anaconda, with Miniforge having conda-forge as the default channel. Follow the instructions provided in the links below:

- [Miniforge Installation](https://github.com/conda-forge/miniforge)
- [Miniconda Installation](https://docs.anaconda.com/miniconda/install)

For development or to get the latest features, you can install Floability from source code using the following steps:
```
git clone https://github.com/floability/floability-cli && cd floability-cli/
```

All conda specific dependencies for floability are specified in the `environment.yml` file. To create the environment, use the following command:

```bash
conda env create -f environment.yml
```

Then activate the new environment:

```bash
conda activate floability-env
```

Install Floability as a package:

```bash
pip install -e .
```


Now you are ready to run the `floability` command-line tool. You can examples as `backpak`s like:

```bash
floability run --backpack example/matrix-multiplication
```

## Structure of a Backpack
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

The compute file defines the compute resources and environment needed to run the workflow. For example, it might specify the number of workers, the type of compute resources, and any other relevant settings. Here is an example `compute.yml` file:

```yaml
vine_factory_config:
  min-workers: 2
  max-workers: 4
  cores: 1
```

The  software directory contains the environment file that specifies the dependencies needed to run the workflow. This is a standard conda environment file. Here is an example `environment.yml` file:

```yaml
name: matrix
channels:
  - conda-forge
dependencies:
  - python
  - numpy
```

The workflow file in this case is a Jupyter notebook that contains the actual code to be executed. In the matrix multiplication example, the worklow is to do the matrix multiplication on the distributed workers. We run the following python funaction as distributed tasks on the workers. 

```python
def multiply_pair(A, B):
    import numpy as np  # Only the worker environment needs numpy
    
    A_np = np.array(A, dtype=float)
    B_np = np.array(B, dtype=float)
    C_np = A_np @ B_np
    return C_np.tolist()
```
We can then run the notebook using the `floability` command:

```bash
floability run --backpack example/matrix-multiplication
```

To deppoy the workers on a batch system, we can use the `--batch-type` flag. This will submit the workers to a job scheduler like HTCondor, UGE or SLURM. 
For example:

```bash
floability run --backpack example/matrix-multiplication --batch-type condor
```

## Floability Audit

The user needs to run the following command for matrix multiplication example from the terminal:

```bash
floability audit --notebook example/matrix-multiplication --kernel "kernel_name"  --manager-name "manager_name" --manager-port 9123
```

`floability audit` command executes the Jupyter notebook and audits the execution using `strace`. It then extracts and gathers the dependencies for both worker and manager code into `manager_environment.yml` and `worker_environment.yml` files (example shown below):

Manager Environment:
```
name: autoenv
channels:
- defaults
- rich
- matplotlib
- ndcctools
```

Worker Environment:
```
name: autoenv
channels:
- defaults
- cloudpickle=3.1.1
- numpy=2.2.4
```

## Floability CLI Documentation

The documentation source lives in the `docs/` directory and MkDocs configuration is at the repository root (`mkdocs.yml`). The required dependencies for building the documentation are listed in `docs/mkdocs.requirements.txt`.

To browse the documentation in Markdown, start from [docs/index.md](docs/index.md).

To build and serve the documentation locally with MkDocs:

```bash
# create and activate a virtualenv 
python3 -m venv .venv
source .venv/bin/activate 

# upgrade pip and install the MkDocs dependencies from the repo
pip install --upgrade pip
pip install -r docs/mkdocs.requirements.txt   

# serve locally (auto-reloads on changes)
mkdocs serve
```
Then open the site at: http://127.0.0.1:8000/

## License

This project is licensed under GNU GPL v2.0 — see [COPYING](COPYING).
