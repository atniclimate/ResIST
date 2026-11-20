"""Metadata-only regressions: damaged policy sources cannot grant admission."""

import pytest

from resist.errors import InvalidConfig
from resist.models import DocRef
from resist.services import policy

SHA = "a" * 64
ATNI = f"sha256,status,source,local_path\n{SHA},fetched,atni-table,x.pdf\n"


@pytest.mark.parametrize("bad", [
    b"\xff",
    b"",
    b"wrong_header\n",
    b"sha256,sha256\n",
    b'sha256\n"unterminated',
    b"sha256\na,b\n",
])
@pytest.mark.parametrize("limit", ["T0", "T3"])
def test_invalid_ncai_manifest_never_admits_atni_member(tmp_path, bad, limit):
    (tmp_path / "manifest-atni.csv").write_text(ATNI, encoding="utf-8")
    (tmp_path / "manifest-ncai.csv").write_bytes(bad)
    with pytest.raises(InvalidConfig, match="^manifests-unreadable-or-invalid$"):
        policy.require_admissible(DocRef(SHA, "application/pdf", "atni", "T0"), limit, tmp_path)


def test_unreadable_manifest_does_not_activate_absent_exception(tmp_path, monkeypatch):
    path = tmp_path / "manifest-ncai.csv"
    path.write_text(f"sha256\n{SHA}\n", encoding="utf-8")

    def denied(_path, _content):
        raise PermissionError("private diagnostic")

    monkeypatch.setattr(policy, "_rows", denied)
    with pytest.raises(InvalidConfig, match="^manifests-unreadable-or-invalid$"):
        policy.require_admissible(DocRef(SHA, "application/pdf", "atni", "T0"), "T3", tmp_path)


def test_manifest_directory_is_not_absent(tmp_path):
    (tmp_path / "manifest-ncai.csv").mkdir()
    with pytest.raises(InvalidConfig):
        policy.load_manifests(tmp_path)


def test_incomplete_atni_policy_columns_refused(tmp_path):
    (tmp_path / "manifest-atni.csv").write_text(
        f"sha256,status,source,local_path\n{SHA},fetched,atni-media-library\n", encoding="utf-8")
    with pytest.raises(InvalidConfig):
        policy.source_policy(SHA, tmp_path)


def test_truly_absent_manifests_keep_fresh_clone_contract(tmp_path):
    assert not policy.load_manifests(tmp_path).present
    policy.require_admissible(DocRef(SHA, "application/pdf", "atni", "T0"), "T0", tmp_path)


@pytest.mark.parametrize("manifest", ["atni", "ncai"])
@pytest.mark.parametrize("sha,status", [
    ("a" * 63, "fetched"),
    ("g" * 64, "pending"),
    ("a" * 65, "pending"),
    ("", "fetched"),
    ("  ", " fetched "),
])
def test_invalid_row_hash_refuses_admission(tmp_path, manifest, sha, status):
    (tmp_path / "manifest-atni.csv").write_text(ATNI, encoding="utf-8")
    (tmp_path / f"manifest-{manifest}.csv").write_text(
        f"sha256,status,source,local_path\n{sha},{status},atni-table,x.pdf\n", encoding="utf-8")
    with pytest.raises(InvalidConfig, match="^manifests-unreadable-or-invalid$"):
        policy.require_admissible(DocRef(SHA, "application/pdf", "atni", "T0"), "T3", tmp_path)


def test_normalized_hash_and_unfetched_blank_preserve_quarantine(tmp_path):
    (tmp_path / "manifest-atni.csv").write_text(ATNI, encoding="utf-8")
    (tmp_path / "manifest-ncai.csv").write_text(
        f"sha256,status\n {SHA.upper()} ,pending\n ,pending\n", encoding="utf-8")
    assert policy.source_policy(SHA, tmp_path).quarantined


def test_unfetched_blank_atni_hash_is_not_a_member(tmp_path):
    (tmp_path / "manifest-atni.csv").write_text(
        "sha256,status,source,local_path\n ,pending,atni-table,x.pdf\n", encoding="utf-8")
    assert policy.load_manifests(tmp_path).atni == {}
