import os
import tempfile

# Isolate tests from the user's real data dir/config and force loopback binding.
# Must run before any src.* module is imported.
os.environ.setdefault("VIDEO_DESCRIBER_DATA_DIR", tempfile.mkdtemp(prefix="cinetag-test-"))
os.environ["CINETAG_BIND_HOST"] = "127.0.0.1"
os.environ.pop("CINETAG_TOKEN", None)


import types
import pytest


@pytest.fixture
def allow_path():
    """Register file paths as queue tasks so download endpoints permit them."""
    from src.server.queue_manager import manager
    added = []

    def _allow(path):
        t = types.SimpleNamespace(file_path=str(path), result=None)
        manager.queue.append(t)
        added.append(t)

    yield _allow
    for t in added:
        if t in manager.queue:
            manager.queue.remove(t)
