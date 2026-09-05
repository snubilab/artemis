import pytest

from src.utils.store_resolution import StoreMismatchError, resolve_store_path


def test_should_raise_when_env_set_to_different_path(tmp_path, monkeypatch):
    explicit = tmp_path / "correct" / "studies.json"
    explicit.parent.mkdir(parents=True)
    explicit.write_text("{}")

    other = tmp_path / "stale" / "studies.json"
    other.parent.mkdir(parents=True)
    other.write_text("{}")

    monkeypatch.setenv("TTE_STORE_PATH", str(other))

    with pytest.raises(StoreMismatchError) as exc_info:
        resolve_store_path(explicit)

    message = str(exc_info.value)
    assert str(explicit.resolve()) in message
    assert str(other.resolve()) in message


def test_should_return_explicit_path_when_env_unset(tmp_path, monkeypatch):
    explicit = tmp_path / "studies.json"
    explicit.write_text("{}")

    monkeypatch.delenv("TTE_STORE_PATH", raising=False)

    resolved = resolve_store_path(explicit)

    assert resolved == explicit.resolve()


def test_should_return_explicit_path_when_env_agrees(tmp_path, monkeypatch):
    explicit = tmp_path / "studies.json"
    explicit.write_text("{}")

    monkeypatch.setenv("TTE_STORE_PATH", str(explicit))

    resolved = resolve_store_path(explicit)

    assert resolved == explicit.resolve()


def test_should_raise_when_file_missing(tmp_path, monkeypatch):
    missing = tmp_path / "does-not-exist" / "studies.json"

    monkeypatch.delenv("TTE_STORE_PATH", raising=False)

    with pytest.raises(FileNotFoundError):
        resolve_store_path(missing)
