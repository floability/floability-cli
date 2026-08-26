import re
from pathlib import Path
from urllib.parse import unquote

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPOSITORY_ROOT / "docs"
FENCED_YAML = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL)
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")


def _documentation_files():
    return sorted(DOCS_ROOT.rglob("*.md"))


def test_documentation_has_no_empty_pages():
    empty = [path for path in _documentation_files() if not path.read_text().strip()]

    assert empty == []


def test_documentation_yaml_examples_parse():
    failures = []
    for path in _documentation_files():
        text = path.read_text(encoding="utf-8")
        for index, block in enumerate(FENCED_YAML.findall(text), start=1):
            try:
                yaml.safe_load(block)
            except yaml.YAMLError as error:
                failures.append(
                    f"{path.relative_to(REPOSITORY_ROOT)} block {index}: {error}"
                )

    assert failures == []


def test_documentation_local_links_resolve():
    missing = []
    for path in _documentation_files():
        text = path.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if not target or target.startswith(
                ("#", "http://", "https://", "mailto:")
            ):
                continue

            relative_target = unquote(target.split("#", 1)[0])
            resolved = (path.parent / relative_target).resolve()
            if not resolved.exists():
                missing.append(
                    f"{path.relative_to(REPOSITORY_ROOT)} -> {relative_target}"
                )

    assert missing == []
