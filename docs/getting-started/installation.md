# Installation

## Prerequisites

Floability requires **Conda 24.0 or later**. We recommend
[Miniforge](https://github.com/conda-forge/miniforge) — it uses
conda-forge by default and gives the best compatibility with Floability's
dependencies. [Miniconda](https://docs.conda.io/en/latest/miniconda.html)
also works.

Check your current version:
```bash
conda --version
```


## Install from conda-forge
```bash
conda create -n floability-env -c conda-forge floability
conda activate floability-env
```

**Note:** Floability is under active development. The conda-forge release may lag behind recent fixes. If you run into issues with the conda install, switch to the source install.

## Install from source (recommended)

Clone the repository:
```bash
git clone https://github.com/floability/floability-cli.git
cd floability-cli
```

Create and activate the environment:
```bash
conda env create -f environment.yml
conda activate floability-env
```

Install Floability:
```bash
pip install .
```


## Verify
```bash
floability --version
```

If this command is not found, make sure the `floability-env` environment
is active (`conda activate floability-env`) and that the install step
completed without errors.

---

Next: [Run your first backpack](run-first-backpack.md)