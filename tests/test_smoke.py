"""M0 smoke test:套件可匯入、版本存在。"""

from fhir_copilot import __version__


def test_version() -> None:
    assert __version__ == "0.2.1"
