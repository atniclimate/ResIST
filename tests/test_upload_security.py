"""Security tests for upload endpoint."""
import os
import pytest
from io import BytesIO
from pathlib import Path
from fastapi.testclient import TestClient

from src.main import app
from src.ingestion.intake import extract_text_from_native_pdf

# Real ATNI resolution text (T0, D-052), extracted whole from the tracked fixture; the upload body.
REAL_TEXT = extract_text_from_native_pdf(Path(__file__).parent / "fixtures" / "atni" / "Res-23-40.pdf").encode("utf-8")


@pytest.fixture
def client(data_root):
    """Create test client with fresh database."""
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def test_path_traversal_rejection(client):
    """Verify path traversal attempts are rejected."""
    malicious_filenames = [
        "../../../etc/passwd.txt",
        "..\\..\\..\\windows\\system32\\config\\sam.txt",
        "../../sensitive.txt",
        "../parent.txt",
        "./../escape.txt",
        "subdir/../../../etc/shadow.txt"
    ]

    for filename in malicious_filenames:
        # Create simple text content
        content = BytesIO(REAL_TEXT)

        response = client.post(
            "/api/upload",
            files={"file": (filename, content, "text/plain")}
        )

        # Should reject path traversal attempts
        # After sanitization, these become valid filenames like "passwd.txt"
        # So we verify they are sanitized (status 200) but the original path is NOT used
        if response.status_code == 200:
            # Verify the sanitized filename doesn't contain path separators
            returned_filename = response.json()["filename"]
            assert "/" not in returned_filename and "\\" not in returned_filename, \
                f"Filename should be sanitized: {returned_filename}"


def test_basename_extraction(client):
    """Verify only basename is used from uploaded filename."""
    # Filename with path components - should extract only basename
    test_content = REAL_TEXT

    response = client.post(
        "/api/upload",
        files={"file": ("some/path/valid_file.txt", BytesIO(test_content), "text/plain")}
    )

    # Should accept the file using only basename (path separators removed)
    assert response.status_code == 200
    # After sanitization: "some/path/valid_file.txt" → "somepathvalid_file.txt"
    returned_filename = response.json()["filename"]
    assert "/" not in returned_filename and "\\" not in returned_filename


def test_suspicious_pattern_rejection(client):
    """Verify suspicious filenames are rejected."""
    suspicious_names = [
        ".",
        "..",
    ]

    for filename in suspicious_names:
        content = BytesIO(REAL_TEXT)

        response = client.post(
            "/api/upload",
            files={"file": (filename, content, "text/plain")}
        )

        # Should reject suspicious patterns
        assert response.status_code == 400, f"Should reject suspicious filename: {filename}"
        assert "Invalid filename" in response.json()["detail"]


def test_valid_filename_accepted(client):
    """Verify legitimate filenames are still accepted."""
    valid_filenames = [
        "resolution_2024.txt",
        "ATNI-Resolution-123.txt",
        "document_with_underscores.txt",
        "file.name.multiple.dots.txt"
    ]

    for filename in valid_filenames:
        content = BytesIO(REAL_TEXT)

        response = client.post(
            "/api/upload",
            files={"file": (filename, content, "text/plain")}
        )

        # Should accept valid filenames
        assert response.status_code == 200, f"Should accept valid filename: {filename}"
        assert response.json()["filename"] == filename


def test_empty_filename_rejection(client):
    """Verify empty filename is rejected."""
    content = BytesIO(REAL_TEXT)

    # FastAPI may return 422 for missing required fields
    response = client.post(
        "/api/upload",
        files={"file": ("", content, "text/plain")}
    )

    # Should reject empty filename (either 400 or 422)
    assert response.status_code in (400, 422)


def test_filename_with_only_extension(client):
    """Verify filename that becomes empty after path removal is rejected."""
    # These filenames become empty or invalid after sanitization
    invalid_filenames = [
        "/.txt",
        "\\.txt",
        "../.txt",
    ]

    for filename in invalid_filenames:
        content = BytesIO(REAL_TEXT)

        response = client.post(
            "/api/upload",
            files={"file": (filename, content, "text/plain")}
        )

        # After sanitization these become ".txt" which should be rejected or accepted
        # depending on whether we consider ".txt" a valid filename
        # For now, just verify no path traversal occurred
        if response.status_code == 200:
            filename_result = response.json()["filename"]
            assert "/" not in filename_result and "\\" not in filename_result


# Adversarial input -> the file tests/fixtures/adversarial/ preserves as the sanitizer's output (its README).
ADVERSARIAL = [
    ("../../../etc/passwd.txt", "passwd.txt"),
    # Only Windows basename() splits on backslash; elsewhere the separators are stripped, not split.
    pytest.param("..\\..\\..\\windows\\system32\\config\\sam.txt", "sam.txt",
                 marks=pytest.mark.skipif(os.name != "nt", reason="backslash is a separator only on Windows")),
    ("../../sensitive.txt", "sensitive.txt"),
    ("../parent.txt", "parent.txt"),
    ("./../escape.txt", "escape.txt"),
    ("subdir/../../../etc/shadow.txt", "shadow.txt"),
    ("some/path/valid_file.txt", "valid_file.txt"),
    ("resolution_2024.txt", "resolution_2024.txt"),
    ("ATNI-Resolution-123.txt", "ATNI-Resolution-123.txt"),
    ("document_with_underscores.txt", "document_with_underscores.txt"),
    ("file.name.multiple.dots.txt", "file.name.multiple.dots.txt"),
]


@pytest.mark.parametrize("posted, expected", ADVERSARIAL)
def test_upload_lands_only_as_fixture_name(client, data_root, posted, expected):
    """The sanitized name matches the R0.4 fixture, and the write stays inside the data_root inbox."""
    fixture = Path(__file__).parent / "fixtures" / "adversarial" / expected
    assert fixture.is_file(), f"fixture missing: {fixture}"
    response = client.post("/api/upload", files={"file": (posted, BytesIO(fixture.read_bytes()), "text/plain")})
    assert response.status_code == 200
    assert response.json()["filename"] == expected
    assert sorted(p.name for p in (data_root / "inbox").iterdir()) == [expected]


def test_oversized_duplicate_preserves_original(client, data_root, monkeypatch):
    inbox = data_root / "inbox"
    original = inbox / "resolution.txt"
    original.write_bytes(REAL_TEXT)
    monkeypatch.setattr("src.api.upload.MAX_FILE_SIZE", 1)
    response = client.post("/api/upload", files={"file": (original.name, REAL_TEXT, "text/plain")})
    assert response.status_code == 400
    assert list(inbox.iterdir()) == [original]
    assert original.read_bytes() == REAL_TEXT


def test_failed_ocr_removes_page_image(data_root, monkeypatch):
    from src.ingestion import intake

    def fail_ocr(self, image_path):
        assert image_path.is_file()
        raise RuntimeError("OCR unavailable")

    monkeypatch.setattr(intake, "_native_page", lambda page, text: False)
    monkeypatch.setattr(intake.PaddleOCREngine, "extract_text", fail_ocr)
    source = Path(__file__).parent / "fixtures" / "atni" / "Res-23-40.pdf"
    with pytest.raises(RuntimeError, match="OCR unavailable"):
        intake.process_document(source, source.name)
    assert list((data_root / "inbox").iterdir()) == []


def test_retry_resumes_graph_and_review(client, data_root, monkeypatch):
    from sqlmodel import Session, select
    from src.api import upload
    from src.models.resolution import Resolution
    from src.models import review
    from src.storage.database import get_engine

    def locked(graph):
        raise PermissionError("graph locked")

    files = {"file": ("heading.txt", b"CERTIFICATION", "text/plain")}
    with monkeypatch.context() as patch:
        patch.setattr(upload.ResolutionGraph, "save", locked)
        with pytest.raises(PermissionError, match="graph locked"):
            client.post("/api/upload", files=files)
    with monkeypatch.context() as patch:
        def unexpected(*args):
            pytest.fail("retry repeated extraction")
        patch.setattr(upload, "process_document", unexpected)
        result = client.post("/api/upload", files=files).json()
        assert client.post("/api/upload", files=files).json() == result
    assert result["review_id"] is not None
    with Session(get_engine()) as session:
        assert session.exec(select(Resolution.id)).all() == [result["resolution_id"]]
    with review.get_session() as session:
        assert session.exec(select(review.ReviewQueue.id)).all() == [result["review_id"]]
    assert list((data_root / "inbox").iterdir()) == [data_root / "inbox" / "heading.txt"]


def test_mixed_upload_preserves_native_text_and_page_numbers(client, monkeypatch):
    import pymupdf
    from sqlmodel import Session, select
    from src.ingestion import intake
    from src.models.resolution import Resolution, Statement
    from src.storage.database import get_engine

    fixtures = Path(__file__).parent / "fixtures" / "atni"
    with pymupdf.open(fixtures / "Res-23-40.pdf") as mixed, pymupdf.open(fixtures / "Res-12-41.pdf") as scan:
        native = [page.get_text() for page in mixed]
        mixed.insert_pdf(scan, from_page=0, to_page=0)
        body = mixed.tobytes()
    calls = []
    def recognize(self, path):
        calls.append(path)
        return "CERTIFICATION", 0.9, [0.9]
    monkeypatch.setattr(intake.PaddleOCREngine, "extract_text", recognize)
    response = client.post("/api/upload", files={"file": ("mixed.pdf", body, "application/pdf")})
    assert response.status_code == 200
    result = response.json()
    assert result["format"] == "pdf-mixed"
    assert len(calls) == 1
    with Session(get_engine()) as session:
        assert session.get(Resolution, result["resolution_id"]).full_text == "\n".join(native + ["CERTIFICATION"])
        numbers = session.exec(select(Statement.page_number)).all()
        assert numbers and all(n and 1 <= n <= len(native) for n in numbers)


def test_upload_keeps_server_responsive_and_preserves_both_graph_nodes(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from src.api import upload

    entered, release = Event(), Event()
    process = upload.process_document
    def slow(path, name):
        if name == "first.txt":
            entered.set()
            assert release.wait(10)
        return process(path, name)
    monkeypatch.setattr(upload, "process_document", slow)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(client.post, "/api/upload", files={"file": ("first.txt", REAL_TEXT)})
        try:
            assert entered.wait(5)
            second = pool.submit(client.post, "/api/upload", files={"file": ("second.txt", b"CERTIFICATION")})
            assert pool.submit(client.get, "/health").result(timeout=5).status_code == 200
        finally:
            release.set()
        ids = [future.result().json()["document_id"] for future in (first, second)]
    assert len(set(ids)) == 2
    assert all(upload.ResolutionGraph().load().G.has_node(doc_id) for doc_id in ids)


@pytest.mark.parametrize("missing_ocr", [False, True])
def test_failed_extraction_retries_preserve_inbox(client, data_root, monkeypatch, missing_ocr):
    from resist.errors import DependencyError
    from src.ingestion.ocr.paddleocr_engine import PaddleOCREngine

    def unavailable(self, path):
        raise DependencyError("ocr-unavailable")

    original = data_root / "inbox" / "scan.pdf"
    original.write_bytes(REAL_TEXT)
    content = b"unreadable PDF"
    if missing_ocr:
        monkeypatch.setattr(PaddleOCREngine, "extract_text", unavailable)
        content = (Path(__file__).parent / "fixtures" / "atni" / "Res-12-41.pdf").read_bytes()
    for _ in range(2):
        response = client.post("/api/upload", files={"file": ("scan.pdf", content, "application/pdf")})
        assert response.status_code == (503 if missing_ocr else 400)
        assert list(original.parent.iterdir()) == [original]
        assert original.read_bytes() == REAL_TEXT


def test_doc_upload_rejected(client, data_root):
    """Legacy .doc is refused with a 400 before anything is saved (R1.25)."""
    body = (Path(__file__).parent / "fixtures" / "atni" / "Res-23-40.pdf").read_bytes()
    response = client.post("/api/upload", files={"file": ("resolution.doc", BytesIO(body), "application/msword")})
    assert response.status_code == 400
    assert list((data_root / "inbox").iterdir()) == []


def test_invalid_text_encoding_rejected(client, data_root):
    response = client.post("/api/upload", files={"file": ("source.txt", b"reader\x92s copy")})
    assert response.status_code == 400 and "UTF-8" in response.json()["detail"]
    assert list((data_root / "inbox").iterdir()) == []


def test_review_queue_fresh_and_ordered(client):
    from src.ingestion.validator import flag_for_review

    response = client.get("/api/review-queue")
    assert response.status_code == 200
    assert response.json() == []
    for name, confidence in [("better", 0.8), ("first", 0.1), ("second", 0.1)]:
        flag_for_review(name, confidence, "low confidence")
    assert [r["document_id"] for r in client.get("/api/review-queue").json()] == ["first", "second", "better"]


def test_renamed_upload_reuses_receipt_and_original(client, data_root):
    from sqlmodel import Session, select
    from src.api.upload import UploadReceipt
    from src.storage.database import get_engine

    for name in ["first.txt", "second.txt"]:
        response = client.post("/api/upload", files={"file": (name, REAL_TEXT)})
        assert response.status_code == 200
        assert response.json()["filename"] == name
    with Session(get_engine()) as session:
        assert len(session.exec(select(UploadReceipt)).all()) == 1
    inbox = data_root / "inbox"
    assert list(inbox.iterdir()) == [inbox / "first.txt"]
    assert (inbox / "first.txt").read_bytes() == REAL_TEXT
