"""The backfill writes the store the way the service writes it.

The backfill mutates the same `studies.json` a running service mutates, so its write
has to carry the service's three properties. Each test below fails against a plain
`store_path.write_text(json.dumps(doc, ensure_ascii=False))`, which is what it replaced.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backfill_registered_conditions import write_store  # noqa: E402

KOREAN = "한글 조건"  # non-ASCII the store really carries


@pytest.fixture
def store(tmp_path: Path) -> Path:
    path = tmp_path / "studies.json"
    path.write_text(json.dumps({"studies": [{"id": 1, "note": KOREAN}]}, indent=2))
    return path


class TestTheWriteMatchesTheService:
    def test_should_escape_non_ascii_when_writing_the_store(self, store: Path) -> None:
        """The service uses ensure_ascii=True; writing it raw makes the next service
        write flip the whole file back, and a 52MB file that churns on every write
        cannot be diffed."""
        write_store(store, {"studies": [{"id": 1, "note": KOREAN}]})

        raw = store.read_text(encoding="utf-8")
        assert "\\ud55c" in raw
        assert KOREAN not in raw
        assert json.loads(raw)["studies"][0]["note"] == KOREAN

    def test_should_leave_no_temp_file_behind_when_the_write_succeeds(self, store: Path) -> None:
        write_store(store, {"studies": []})

        assert not store.with_suffix(".tmp").exists()

    def test_should_leave_the_original_intact_when_serialization_fails(self, store: Path) -> None:
        """An interrupted write must not truncate the store. json.dump raises partway
        through an unserializable payload, and the rename never happens."""
        before = store.read_text(encoding="utf-8")

        with pytest.raises(TypeError):
            write_store(store, {"studies": [{"id": 1, "bad": object()}]})

        assert store.read_text(encoding="utf-8") == before
        assert json.loads(before)["studies"][0]["note"] == KOREAN

    def test_should_hold_the_lock_the_service_takes_while_it_writes(
        self, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The lock has to be held DURING serialization, which is the window a
        concurrent service write would land in. Asserting on the lock file afterwards
        proves nothing: filelock removes it on release."""
        lock_path = store.with_name(store.name + ".lock")
        held: list[bool] = []
        real_dump = json.dump

        def spy(*args: object, **kwargs: object) -> object:
            held.append(lock_path.exists())
            return real_dump(*args, **kwargs)

        monkeypatch.setattr(json, "dump", spy)
        write_store(store, {"studies": []})

        assert held == [True]
