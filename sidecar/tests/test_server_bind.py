from argparse import ArgumentTypeError

import pytest

from atme.server.__main__ import _loopback


@pytest.mark.parametrize(("value", "expected"), [
    ("LOCALHOST", "127.0.0.1"), ("127.0.0.2", "127.0.0.2"), ("::1", "::1"),
])
def test_local_listeners(value, expected):
    assert _loopback(value) == expected


@pytest.mark.parametrize("value", ["0.0.0.0", "::", "192.0.2.2", "example.test"])
def test_other_listeners_rejected(value):
    with pytest.raises(ArgumentTypeError):
        _loopback(value)
