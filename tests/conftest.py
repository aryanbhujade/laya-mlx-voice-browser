import pytest


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Tests never read the developer's real Laya settings."""
    monkeypatch.setenv("LAYA_CONFIG", str(tmp_path / "config.json"))
