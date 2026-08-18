from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime
from pathlib import Path
from threading import Event, Thread

import httpx
import pytest
from PySide6.QtGui import QImage

from app.api.client import AIClient, AIRequestCancelled, _clean_thumbnail_data_url, extract_limited_text
from app.core import secret_store
from app.models.schemas import AIResult, AppSettings, FileRecord
from app.utils import paths as path_utils


def make_record(path: Path, mime: str = "text/plain") -> FileRecord:
    now = datetime.now()
    return FileRecord(
        path=path,
        name=path.name,
        suffix=path.suffix,
        size=path.stat().st_size,
        created_at=now,
        modified_at=now,
        mime_type=mime,
    )


def test_text_read_is_bounded_and_bad_pdf_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    text_file = tmp_path / "large.txt"
    text_file.write_text("A" * 100_000, encoding="utf-8")

    def forbidden_read_text(*_args, **_kwargs):
        raise AssertionError("Path.read_text would load the entire file")

    monkeypatch.setattr(Path, "read_text", forbidden_read_text)
    assert extract_limited_text(text_file, 123) == "A" * 123

    bad_pdf = tmp_path / "broken.pdf"
    bad_pdf.write_bytes(b"not a valid pdf")
    assert extract_limited_text(bad_pdf, 5000) == ""


def test_batch_payload_has_hard_character_cap_and_hides_absolute_path(tmp_path: Path):
    source = tmp_path / "private-folder" / "notes.txt"
    source.parent.mkdir()
    source.write_text(("秘密\x01" * 50_000), encoding="utf-8")
    records = [make_record(source) for _ in range(8)]
    settings = AppSettings(api_max_batch_chars=8000, max_text_chars=100_000, ai_send_full_path=False)
    payload = AIClient(settings, "test-key")._metadata_json(records)
    assert len(payload) <= 8000
    assert str(tmp_path) not in payload
    assert any("text_excerpt" in item for item in json.loads(payload))


def test_content_sending_can_be_disabled(tmp_path: Path):
    source = tmp_path / "secret.txt"
    source.write_text("never send this", encoding="utf-8")
    payload = AIClient(AppSettings(ai_send_text_content=False), "test-key")._metadata_json([make_record(source)])
    assert "never send this" not in payload
    assert "text_excerpt" not in json.loads(payload)[0]


def test_vision_uses_bounded_metadata_free_thumbnail(tmp_path: Path):
    source = tmp_path / "source.png"
    image = QImage(1600, 1200, QImage.Format_RGB32)
    image.fill(0xFF336699)
    image.setText("Comment", "GPS-secret-metadata")
    assert image.save(str(source), "PNG")

    data_url = _clean_thumbnail_data_url(source, 512, 5 * 1024**2)
    assert data_url and data_url.startswith("data:image/jpeg;base64,")
    raw = base64.b64decode(data_url.split(",", 1)[1])
    assert b"GPS-secret-metadata" not in raw and b"Exif" not in raw
    thumbnail = QImage.fromData(raw, "JPEG")
    assert not thumbnail.isNull()
    assert max(thumbnail.width(), thumbnail.height()) <= 512


def test_transient_http_retries_are_finite(monkeypatch: pytest.MonkeyPatch):
    calls: list[int] = []

    class FakeStream:
        def __init__(self):
            request = httpx.Request("POST", "https://example.com/v1/chat/completions")
            self.response = httpx.Response(429, headers={"Retry-After": "0"}, request=request)

        def __enter__(self):
            return self.response

        def __exit__(self, *_args):
            return False

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream(self, *_args, **_kwargs):
            calls.append(1)
            return FakeStream()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setattr("app.api.client.time.sleep", lambda _seconds: None)
    client = AIClient(AppSettings(api_base_url="https://example.com/v1", api_max_retries=2), "key")
    with pytest.raises(httpx.HTTPStatusError):
        client._request_json("POST", client.endpoint, {})
    assert len(calls) == 3


def test_cancel_closes_an_inflight_http_stream(monkeypatch: pytest.MonkeyPatch):
    stream_started = Event()
    connection_closed = Event()

    class BlockingResponse:
        headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            stream_started.set()
            if not connection_closed.wait(5):  # pragma: no cover - failure guard
                raise AssertionError("cancel() did not close the HTTP client")
            request = httpx.Request("POST", "https://example.com/v1/chat/completions")
            raise httpx.ReadError("closed", request=request)
            yield b""  # pragma: no cover - make this a generator

    class BlockingClient:
        def __init__(self, **_kwargs):
            pass

        def stream(self, *_args, **_kwargs):
            return BlockingResponse()

        def close(self):
            connection_closed.set()

    monkeypatch.setattr(httpx, "Client", BlockingClient)
    client = AIClient(AppSettings(api_base_url="https://example.com/v1", api_max_retries=0), "key")
    errors: list[Exception] = []

    def request():
        try:
            client._request_json("POST", client.endpoint, {})
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=request)
    thread.start()
    assert stream_started.wait(1)
    started = time.perf_counter()
    client.cancel()
    thread.join(1)
    assert not thread.is_alive()
    assert time.perf_counter() - started < 0.5
    assert len(errors) == 1 and isinstance(errors[0], AIRequestCancelled)


def test_retry_backoff_is_interruptible():
    client = AIClient(AppSettings(), "key")
    errors: list[Exception] = []
    thread = Thread(target=lambda: _capture_exception(lambda: client._wait_with_cancel(30), errors))
    thread.start()
    time.sleep(0.05)
    started = time.perf_counter()
    client.cancel()
    thread.join(1)
    assert not thread.is_alive()
    assert time.perf_counter() - started < 0.5
    assert len(errors) == 1 and isinstance(errors[0], AIRequestCancelled)


def _capture_exception(function, errors: list[Exception]):
    try:
        function()
    except Exception as exc:
        errors.append(exc)


def test_analyze_many_does_not_wait_for_stubborn_executor_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "pending.txt"
    source.write_text("content", encoding="utf-8")
    record = make_record(source)
    client = AIClient(AppSettings(api_concurrency=1), "key")
    stopped = Event()
    job_started = Event()
    release_job = Event()
    job_finished = Event()

    def stubborn_job(_kind, _batch, _stopped):
        job_started.set()
        release_job.wait(2)
        job_finished.set()
        return [AIResult(category="late result", confidence=0.9, reason="too late")]

    monkeypatch.setattr(client, "_analyze_job", stubborn_job)

    def stop_after_start():
        if job_started.wait(1):
            stopped.set()

    stopper = Thread(target=stop_after_start)
    stopper.start()
    started = time.perf_counter()
    try:
        client.analyze_many([record], stopped=stopped.is_set)
        elapsed = time.perf_counter() - started
        assert elapsed < 0.7
        assert not job_finished.is_set()
        assert record.category == "待确认"
    finally:
        release_job.set()
        stopper.join(1)
        job_finished.wait(1)


def test_connection_falls_back_to_minimal_chat_when_models_is_unsupported(monkeypatch: pytest.MonkeyPatch):
    client = AIClient(AppSettings(api_base_url="https://example.com/v1", api_max_retries=0), "key")
    calls: list[tuple[str, str, dict | None]] = []

    def request(method: str, url: str, payload: dict | None = None) -> dict:
        calls.append((method, url, payload))
        if method == "GET":
            response = httpx.Response(404, request=httpx.Request(method, url))
            raise httpx.HTTPStatusError("missing", request=response.request, response=response)
        return {"choices": [{"message": {"content": "OK"}}]}

    monkeypatch.setattr(client, "_request_json", request)
    model, latency = client.test_connection()
    assert model == client.settings.api_model and latency >= 0
    assert [item[0] for item in calls] == ["GET", "POST"]
    assert calls[1][2] and calls[1][2]["max_tokens"] == 1


def test_connection_fallback_rejects_false_positive(monkeypatch: pytest.MonkeyPatch):
    client = AIClient(AppSettings(api_base_url="https://example.com/v1"), "key")
    monkeypatch.setattr(client, "_request_json", lambda method, _url, _payload=None: {} if method == "GET" else {"ok": True})
    with pytest.raises(ValueError, match="choices"):
        client.test_connection()


def test_dynamic_batches_fit_base_metadata_budget():
    now = datetime.now()
    long_parent = Path("C:/") / ("private-" * 80)
    records = [
        FileRecord(
            path=long_parent / f"{'n' * 500}-{index}.txt",
            name=f"{'n' * 500}-{index}.txt",
            suffix=".txt",
            size=1,
            created_at=now,
            modified_at=now,
            mime_type="text/plain",
        )
        for index in range(8)
    ]
    client = AIClient(
        AppSettings(api_max_batch_chars=8000, ai_send_full_path=True, ai_send_text_content=False),
        "key",
    )
    batches = client._normal_batches(records)
    assert len(batches) > 1
    assert [item for batch in batches for item in batch] == records
    assert all(len(client._metadata_json(batch)) <= 8000 for batch in batches)


def test_batch_failure_falls_back_to_individual_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    paths = [tmp_path / f"item-{index}.txt" for index in range(3)]
    for path in paths:
        path.write_text("content", encoding="utf-8")
    records = [make_record(path) for path in paths]
    client = AIClient(AppSettings(api_concurrency=1), "key")
    monkeypatch.setattr(client, "analyze_batch", lambda _batch: (_ for _ in ()).throw(ValueError("bad batch")))
    monkeypatch.setattr(
        client,
        "analyze_one",
        lambda record: AIResult(category=record.name, confidence=0.9, reason="individual"),
    )
    client.analyze_many(records)
    assert [record.category for record in records] == [path.name for path in paths]
    assert all(record.status == "AI 已分析" for record in records)


def test_estimated_cost_uses_configured_rates_and_unknown_usage():
    client = AIClient(
        AppSettings(input_cost_per_million=2.0, output_cost_per_million=8.0),
        "key",
    )
    client.input_tokens, client.output_tokens = 1_000_000, 250_000
    assert client.estimated_cost == pytest.approx(4.0)
    client.usage_known = False
    assert client.estimated_cost is None


def test_api_keys_are_isolated_by_normalized_origin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(secret_store, "keyring", None)
    secret_store._SESSION_KEYS.clear()
    assert secret_store.set_api_key("key-a", "https://api-a.example/v1") is False
    assert secret_store.set_api_key("key-b", "https://api-b.example/compatible/v1") is False
    assert secret_store.get_api_key("https://API-A.example:443/other") == "key-a"
    assert secret_store.get_api_key("https://api-b.example/v1") == "key-b"
    assert secret_store.get_api_key("https://api.openai.com/v1") == ""


def test_nonlocal_http_is_rejected_but_loopback_is_allowed():
    with pytest.raises(ValueError):
        AppSettings(api_base_url="http://api.example.com/v1")
    assert AppSettings(api_base_url="http://localhost:11434/v1").api_base_url.startswith("http://localhost")
    assert AppSettings(api_base_url="http://127.0.0.1:8080/v1").api_base_url.startswith("http://127.0.0.1")
    with pytest.raises(ValueError):
        AIResult(category=" ", confidence=0.9)


def test_frozen_state_is_kept_out_of_executable_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    executable_dir = tmp_path / "shared-dist"
    executable_dir.mkdir()
    local = tmp_path / "local-app-data"
    monkeypatch.setattr(path_utils.sys, "frozen", True, raising=False)
    monkeypatch.setattr(path_utils.sys, "executable", str(executable_dir / "AI File Organizer.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    app_paths = path_utils.ensure_app_dirs()
    assert app_paths.root == executable_dir.resolve()
    assert app_paths.data.is_relative_to(local.resolve())
    assert not app_paths.data.is_relative_to(executable_dir.resolve())


@pytest.mark.skipif(os.name != "nt", reason="Windows protected-root behavior")
def test_windows_system_directory_is_protected():
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    assert path_utils.is_protected_location(windows / "System32")
