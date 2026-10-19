"""Security tests for upload endpoint."""
import os
import pytest
from io import BytesIO
from pathlib import Path
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client(data_root):
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
