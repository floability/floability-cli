# Floability Documentation

To browse the documentation in Markdown, start from [index.md](index.md).

## Build and serve locally with MkDocs

From the root of the repository, run the following commands:

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

## Contributing
Contributions are welcome! Please open an issue or pull request with improvements, fixes, or new content.