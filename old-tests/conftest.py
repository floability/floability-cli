"""
Pytest configuration and shared fixtures for floability tests.
"""
import pytest
import tempfile
import shutil
from pathlib import Path


# Test data constants - Pelican
TEST_PELICAN_URL = "pelican://disc-head-002.crc.nd.edu:443/nd/disc2/apps/floability/examples/cms-physics-dv5/data/samples/diboson/zz/nano_mc2017_6.root"
TEST_PELICAN_FILENAME = "nano_mc2017_6.root"
TEST_PELICAN_SIZE = 190634
TEST_PELICAN_CHECKSUM = "sha256:4c976188f38ffbd755267acb9d5b431b9208c7376afa5a26f9a62412e2f33bb0"

# Test data constants - HTTP
TEST_HTTP_URL = "https://www.gutenberg.org/cache/epub/64317/pg64317.txt"
TEST_HTTP_FILENAME = "pg64317.txt"
TEST_HTTP_SIZE = 306594
TEST_HTTP_CHECKSUM = "sha256:e6b7897aa8498b8dac4df0664827f857bc01135c3d9311adb820979bbc44b763"


@pytest.fixture
def tmp_test_dir():
    """Create a temporary directory for test files."""
    tmp_dir = tempfile.mkdtemp(prefix="floability_test_")
    yield Path(tmp_dir)
    # Cleanup after test
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def test_pelican_url():
    """Return the test Pelican URL."""
    return TEST_PELICAN_URL


@pytest.fixture
def test_pelican_filename():
    """Return the expected filename for test Pelican file."""
    return TEST_PELICAN_FILENAME


@pytest.fixture
def test_pelican_size():
    """Return the expected size for test Pelican file."""
    return TEST_PELICAN_SIZE


@pytest.fixture
def test_pelican_checksum():
    """Return the expected checksum for test Pelican file."""
    return TEST_PELICAN_CHECKSUM


@pytest.fixture
def mock_base_dir(tmp_test_dir):
    """Create a mock floability base directory structure."""
    base = tmp_test_dir / "floability-base-dir"
    base.mkdir(parents=True, exist_ok=True)
    
    # Create cache directory
    cache_dir = base / "flo_data_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Create workflow directory
    workflow_dir = base / "workflow"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    
    return base


@pytest.fixture
def cleanup_cache(mock_base_dir):
    """Clean up cache between tests."""
    cache_dir = mock_base_dir / "flo_data_cache"
    yield cache_dir
    # Cleanup after test
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)
        cache_dir.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def test_data_spec_path():
    """Return path to test data spec fixture (Pelican)."""
    return Path(__file__).parent / "fixtures" / "data" / "pelican_single_item.yml"


@pytest.fixture
def test_http_data_spec_path():
    """Return path to HTTP test data spec fixture."""
    return Path(__file__).parent / "fixtures" / "data" / "http_single_item.yml"


@pytest.fixture
def test_http_url():
    """Return the test HTTP URL."""
    return TEST_HTTP_URL


@pytest.fixture
def test_http_filename():
    """Return the expected filename for test HTTP file."""
    return TEST_HTTP_FILENAME


@pytest.fixture
def test_http_size():
    """Return the expected size for test HTTP file."""
    return TEST_HTTP_SIZE


@pytest.fixture
def test_http_checksum():
    """Return the expected checksum for test HTTP file."""
    return TEST_HTTP_CHECKSUM


@pytest.fixture
def test_backpack_root(tmp_test_dir):
    """Create a mock backpack structure."""
    backpack = tmp_test_dir / "test_backpack"
    backpack.mkdir(parents=True, exist_ok=True)
    
    # Create expected backpack structure
    (backpack / "data").mkdir(exist_ok=True)
    (backpack / "workflow").mkdir(exist_ok=True)
    (backpack / "compute").mkdir(exist_ok=True)
    (backpack / "software").mkdir(exist_ok=True)
    
    return backpack


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: mark test as a unit test (fast, no network)")
    config.addinivalue_line("markers", "network: mark test as requiring network access")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "integration: mark test as integration test")
