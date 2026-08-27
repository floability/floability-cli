"""Deploy portable TaskVine workflow backpacks on HPC systems."""

try:
    from ._version import __version__
except ImportError:  # Source tree before setuptools-scm has generated _version.py.
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("floability")
    except PackageNotFoundError:
        __version__ = "0+unknown"

__all__ = ["__version__"]
