import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402


@pytest.fixture(scope="session")
def fx(tmp_path_factory):
    return fixtures.build_all(tmp_path_factory.mktemp("fixtures"))


@pytest.fixture(scope="session", autouse=True)
def offline():
    """Core functionality must work offline: any non-loopback connection fails the test run."""
    real = socket.socket.connect

    def guarded(self, addr):
        host = addr[0] if isinstance(addr, tuple) else addr
        if isinstance(host, str) and host not in ("127.0.0.1", "localhost", "::1") and not host.startswith("/"):
            raise AssertionError(f"Unexpected network access to {addr}")
        return real(self, addr)
    socket.socket.connect = guarded
    yield
    socket.socket.connect = real


@pytest.fixture()
def svc(tmp_path):
    from ptd.config import Paths
    from ptd.service import Service
    s = Service(Paths(tmp_path / "data"))
    yield s
    s.close()


@pytest.fixture(scope="session")
def shared_svc(tmp_path_factory):
    from ptd.config import Paths
    from ptd.service import Service
    s = Service(Paths(tmp_path_factory.mktemp("shared") / "data"))
    yield s
    s.close()
