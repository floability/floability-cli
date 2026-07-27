from setuptools import setup, find_packages

# Use README.md as long description
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="floability",
    version="0.2.1",
    description="Run distributed Jupyter-based workflows with TaskVine",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Floability Team",
    author_email="dthain@nd.edu",
    url="https://floability.github.io",
    packages=find_packages(),
    package_data={
        "floability": [
            "bootstrap_templates/*.ipynb",
            "bootstrap_templates/*.yml",
        ],
    },
    python_requires=">=3.8",
    install_requires=[
        "pyyaml",
        "requests",
        "tqdm",
        "nbformat",
        "boto3",
    ],
    entry_points={
        "console_scripts": [
            "floability=floability.cli:main",
        ],
    },
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
    ],
)
