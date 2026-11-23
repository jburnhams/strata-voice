import importlib
from importlib.metadata import PackageNotFoundError

import stratavoice


def test_version_comes_from_the_installed_package_metadata():
    assert stratavoice.__version__ == importlib.metadata.version("strata-voice")


def test_version_falls_back_when_the_package_was_never_installed(monkeypatch):
    def missing(_name):
        raise PackageNotFoundError

    monkeypatch.setattr("importlib.metadata.version", missing)
    try:
        assert importlib.reload(stratavoice).__version__ == "0+unknown"
    finally:
        monkeypatch.undo()
        importlib.reload(stratavoice)
