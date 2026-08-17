# Makeflow quickstart backpack

This backpack adapts the Capitol animation from the official Makeflow manual
to Floability. It also demonstrates using a shell script as a workflow
entrypoint.

The workflow downloads one image on the manager, sends four independent
ImageMagick transformations to TaskVine workers, and combines the results into
an animated GIF on the manager.

## Run it

From the `floability-env` Conda environment:

```bash
floability execute \
  --backpack example/makeflow-quickstart \
  --batch-type local
```

Floability launches `vine_factory` and manages the workers. The shell
entrypoint launches Makeflow with the TaskVine backend and the same catalog
project name, allowing those workers to discover the Makeflow manager.

The final animation is written to:

```text
workflow/outputs/capitol.anim.gif
```

On an HPC system, change Floability's factory backend, for example to
`--batch-type condor`. The shell launcher should continue using Makeflow's
`vine` backend because Floability owns worker submission and cleanup.

Source example: https://cctools.readthedocs.io/en/latest/makeflow/
