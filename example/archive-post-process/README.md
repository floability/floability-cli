# Archive Post-Process Test Backpack

This backpack tests Floability's safe ZIP extraction and data caching. It
downloads three small public archives with different internal layouts, extracts
each one into its declared `target_location`, and verifies the resulting files
from a notebook.

Run the notebook interactively without starting workers:

```bash
floability run --backpack example/archive-post-process --no-worker
```

Execute it non-interactively:

```bash
floability execute --backpack example/archive-post-process --no-worker
```

The default cache mode for `run` and `execute` is `symlink`. To exercise direct
download and extraction instead, add `--data-cache-mode off`.
