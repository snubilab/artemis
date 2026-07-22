import threading
import time

from src.services.tte_store import TTEStore


def _study_payload(name: str) -> dict[str, object]:
    return {
        "name": name,
        "description": "Concurrent store write regression test",
        "studyType": "comparative",
        "comparisonMode": "explicit_comparator",
        "status": "draft",
        "createdBy": {"name": "pytest"},
        "treatmentArms": [
            {"id": 1, "name": "Treatment"},
            {"id": 2, "name": "Comparator"},
        ],
    }


def test_concurrent_creates_no_lost_updates(tmp_path, monkeypatch):
    store_path = tmp_path / "tte" / "studies.json"
    seed_store = TTEStore(str(store_path))
    seed_store._write(seed_store._initial_state())

    original_read = TTEStore._read

    def delayed_read(self):
        payload = original_read(self)
        time.sleep(0.05)
        return payload

    monkeypatch.setattr(TTEStore, "_read", delayed_read)

    start_barrier = threading.Barrier(10)
    errors: list[BaseException] = []
    error_lock = threading.Lock()

    def worker(index: int) -> None:
        local_store = TTEStore(str(store_path))
        try:
            start_barrier.wait(timeout=5)
            local_store.create_study(_study_payload(f"Concurrent Study {index}"))
        except BaseException as exc:  # pragma: no cover - only used for assertion plumbing
            with error_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors, errors

    studies = TTEStore(str(store_path)).list_studies()
    created_names = {study["name"] for study in studies if study["name"].startswith("Concurrent Study")}
    assert len(created_names) == 10
    assert created_names == {f"Concurrent Study {index}" for index in range(10)}


def test_file_lock_attribute_exists(tmp_path):
    store = TTEStore(str(tmp_path / "tte" / "studies.json"))
    assert hasattr(store, "_file_lock") is True
