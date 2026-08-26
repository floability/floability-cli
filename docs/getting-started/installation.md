# Installation

## Prerequisites

Floability requires a current Conda installation with `conda env create` and
`conda run`. The CLI does not currently enforce a specific minimum Conda
version. We recommend
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

The environment installs Floability in editable mode with its development
dependencies. Source changes are immediately available through the
`floability` command.


## Verify
```bash
floability --version
floability --version --verbose
```

The verbose output identifies the Python executable, package location, source
commit when available, and required runtime tools. A source checkout derives
its development version from Git. A tagged Conda build records the supplied
release version in package metadata and does not require Git at runtime.

If the command is not found, make sure the `floability-env` environment is
active (`conda activate floability-env`) and that environment creation
completed without errors. Floability is not documented as a standalone pip
installation because `ndcctools` is supplied through Conda rather than PyPI.

---

Next: [Run your first backpack](run-first-backpack.md)
