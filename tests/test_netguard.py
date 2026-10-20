"""netguard tests (D-039). In-process only: no child process, and no packet leaves (refused before the syscall).

Every test saves the original socket attributes and restores them in a finally, so no other test runs guarded.
"""

import socket
import urllib.request

import pytest

from resist import netguard
from resist.errors import ResistError

ATTRS = [(socket.socket, "connect"), (socket.socket, "connect_ex"), (socket.socket, "sendto"),
         (socket, "create_connection"), (socket, "getaddrinfo")]


@pytest.fixture
def guarded():
    saved = [(owner, name, getattr(owner, name)) for owner, name in ATTRS]
    try:
        netguard.install()
        yield
    finally:
        for owner, name, original in saved:
            setattr(owner, name, original)
    assert not netguard.installed()


def _refused(fn, *args):
    with pytest.raises(netguard.NetworkRefused) as exc:
        fn(*args)
    assert exc.value.reason == "network-refused (D-039)" and str(exc.value) == exc.value.reason
    assert isinstance(exc.value, ResistError)


def test_not_installed_by_import():
    assert not netguard.installed()


def test_connect_refused_before_syscall(guarded):
    assert netguard.installed()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _refused(s.connect, ("127.0.0.1", 9))  # unguarded this would be ConnectionRefusedError from the OS
        _refused(s.connect_ex, ("127.0.0.1", 9))
    finally:
        s.close()
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _refused(u.sendto, b"x", ("127.0.0.1", 9))
    finally:
        u.close()


def test_module_functions_refused(guarded):
    _refused(socket.create_connection, ("127.0.0.1", 9))
    _refused(socket.getaddrinfo, "localhost", 9)
    with pytest.raises(netguard.NetworkRefused):  # a stdlib client fails closed too
        urllib.request.urlopen("http://127.0.0.1:9/", timeout=1)


def test_install_idempotent(guarded):
    first = [getattr(owner, name) for owner, name in ATTRS]
    netguard.install()
    assert [getattr(owner, name) for owner, name in ATTRS] == first  # no double wrap
    assert netguard.installed()
