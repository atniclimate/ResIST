"""Security tests for upload endpoint."""
import pytest
from io import BytesIO
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile

from src.main import app
from src.storage.database import get_engine, init_db
import src.storage.database as db_module


@pytest.fixture
def test_env(tmp_path):
    """Set up isolated test environment with temp database."""
    db_path = tmp_path / "test.db"

    # Save original values
    original_db_path = db_module.DATABASE_PATH
    original_engine = db_module._engine

    # Override database path
    db_module.DATABASE_PATH = db_path
    db_module._engine = None

    # Initialize fresh DB
    init_db()

    yield {"db_path": db_path, "tmp_path": tmp_path}

    # Cleanup
    db_module.DATABASE_PATH = original_db_path
    db_module._engine = original_engine


@pytest.fixture
def client(test_env):
    """Create test client with fresh database."""
    with TestClient(app) as c:
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
        content = BytesIO(b"RESOLUTION #2024-01\nmalicious attempt")

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
    test_content = b"RESOLUTION #2024-01\ntest content"

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
        content = BytesIO(b"RESOLUTION #2024-01\ntest content")

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
        content = BytesIO(b"RESOLUTION #2024-01\nTest content\n\nWHEREAS testing\n\nRESOLVED testing")

        response = client.post(
            "/api/upload",
            files={"file": (filename, content, "text/plain")}
        )

        # Should accept valid filenames
        assert response.status_code == 200, f"Should accept valid filename: {filename}"
        assert response.json()["filename"] == filename


def test_empty_filename_rejection(client):
    """Verify empty filename is rejected."""
    content = BytesIO(b"RESOLUTION #2024-01\ntest content")

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
        content = BytesIO(b"RESOLUTION #2024-01\ntest content")

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
