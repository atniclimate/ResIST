"""R2.25 source policy (design 1.10, 4.4): tier from manifest MEMBERSHIP by SHA-256, never a tier string.

Inputs: the four committed fixtures, the real manifests (metadata only), the pool through mode=ro, and tmp
manifests built from real headers. Messages hold counts and SHA-256 values only.
"""

import csv
from collections import Counter
from pathlib import Path

import pytest

from resist.errors import BadInput, QuarantinedError, TierRefused
from resist.services import policy
from tests import originals as o

ATNI_HEADER = "source,url,final_url,local_path,sha256,bytes,etag,last_modified,fetched_at,status,table_wdt_ids,tsdf_tier"
NCAI_HEADER = "source,original_url,fetched_url,capture_timestamp,local_path,sha256,bytes,fetched_at,status,tsdf_tier"


def _write(path: Path, header: str, rows: list[dict]) -> None:
    cols = header.split(",")
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def _atni_row(file: str, sha: str, **kw) -> dict:
    url = dict((f, u) for f, _s, u in o.readme_table())[file]
    row = {"source": "atni-table", "url": url, "final_url": url, "local_path": f"atni/{file}", "sha256": sha,
           "status": "fetched", "table_wdt_ids": "", "tsdf_tier": "T0"}
    row.update(kw)
    return row


def _res_dir(tmp_path: Path, atni: list[dict], ncai: list[dict] | None = None) -> Path:
    d = tmp_path / "res"
    d.mkdir()
    _write(d / "manifest-atni.csv", ATNI_HEADER, atni)
    if ncai is not None:
        _write(d / "manifest-ncai.csv", NCAI_HEADER, ncai)
    return d


def _truncated_sha(tmp_path: Path) -> str:
    _sha, path = o.fixture("Res-26-34.pdf")
    data = path.read_bytes()
    cut = tmp_path / "truncated.pdf"
    cut.write_bytes(data[: len(data) // 2])
    return o.sha256_file(cut)


@pytest.mark.parametrize("bad", ["", "abc", "A" * 64, "g" * 64, "0" * 63])
def test_bad_sha_rejected(bad):
    with pytest.raises(BadInput):
        policy.source_policy(bad)


def test_unknown_sha_is_T3_D038(tmp_path):
    sha = _truncated_sha(tmp_path)
    p = policy.source_policy(sha)
    assert (p.tier, p.decision_id, p.rights, p.quarantined, p.org) == ("T3", "D-038", "unreleased", False, "unknown")
    assert not policy.admissible(p, "T1")
    with pytest.raises(TierRefused):
        o.original(sha)


def test_manifests_absent_fail_closed(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert policy.load_manifests(empty).present is False
    for sha in o.fixtures():
        p = policy.source_policy(sha, empty)
        assert (p.tier, p.decision_id, p.quarantined) == ("T3", "D-038", False), sha


def test_manifest_tier_strings_ignored(tmp_path):
    a_sha, _ = o.fixture("Res-23-40.pdf")
    n_sha, _ = o.fixture("Res-2021-20.pdf")
    d = _res_dir(tmp_path, [_atni_row("Res-23-40.pdf", a_sha, tsdf_tier="T3")],
                 [{"source": "ncai", "local_path": "ncai/x.pdf", "sha256": n_sha, "status": "fetched", "tsdf_tier": "T0"}])
    a = policy.source_policy(a_sha, d)
    assert (a.tier, a.decision_id, a.quarantined) == ("T0", "D-052", False)
    n = policy.source_policy(n_sha, d)
    assert (n.org, n.tier, n.decision_id, n.quarantined) == ("ncai", "T1", "D-040", True)
    assert not policy.admissible(n, "T3")


def test_ncai_wins_over_atni(tmp_path):
    sha, _ = o.fixture("Res-23-40.pdf")
    d = _res_dir(tmp_path, [_atni_row("Res-23-40.pdf", sha)],
                 [{"source": "ncai", "local_path": "ncai/x.pdf", "sha256": sha, "status": "present"}])
    p = policy.source_policy(sha, d)
    assert (p.org, p.quarantined, p.decision_id) == ("ncai", True, "D-040")


def test_convention_shaped_media_path_is_T3_D064(tmp_path):
    conv, _ = o.fixture("Res-23-40.pdf")
    plain, _ = o.fixture("Res-26-34.pdf")
    table, _ = o.fixture("Res-2021-20.pdf")
    d = _res_dir(tmp_path, [
        _atni_row("Res-23-40.pdf", conv, source="atni-media-library", local_path="atni/2019 Winter Agenda.pdf"),
        _atni_row("Res-26-34.pdf", plain, source="atni-media-library"),
        _atni_row("Res-2021-20.pdf", table, local_path="atni/Committee Report.pdf"),  # a table row always wins
        _atni_row("Res-12-41.pdf", o.fixture("Res-12-41.pdf")[0], status="error: not a PDF (magic bytes)"),
    ])
    c = policy.source_policy(conv, d)
    assert (c.tier, c.decision_id, c.genre_hint, c.series) == ("T3", "D-064", "convention-material", "atni-media-library")
    p = policy.source_policy(plain, d)
    assert (p.tier, p.decision_id, p.series) == ("T0", "D-052", "atni-media-library")
    t = policy.source_policy(table, d)
    assert (t.tier, t.series) == ("T0", "atni-resolution-table")
    e = policy.source_policy(o.fixture("Res-12-41.pdf")[0], d)
    assert (e.tier, e.decision_id) == ("T3", "D-038")  # a non-fetched row is not ATNI-fetched


def _real_manifests() -> policy.Manifests:
    m = policy.load_manifests()
    if not m.present:
        pytest.skip("manifests absent")
    return m


def test_live_pool_documents_all_admissible():
    db = o.pool_db()
    _real_manifests()
    con = o.ro(db)
    try:
        shas = [r[0] for r in con.execute("select document_id from resolution")]
    finally:
        con.close()
    pols = [policy.source_policy(s) for s in shas]
    tiers = Counter(p.tier for p in pols)
    series = Counter(p.series for p in pols)
    quarantined = sum(p.quarantined for p in pols)
    print(f"pool documents={len(pols)} tiers={dict(tiers)} series={dict(series)} quarantined={quarantined}")
    assert len(pols) > 0
    assert tiers["T0"] == len(pols), f"T0={tiers['T0']} of {len(pols)}"
    assert quarantined == 0 and tiers["T3"] == 0, f"quarantined={quarantined} T3={tiers['T3']}"
    assert all(policy.admissible(p, "T0") for p in pols)


def test_real_ncai_rows_quarantined():
    m = _real_manifests()
    if not m.ncai:
        pytest.skip("no NCAI manifest rows")
    bad = [s for s in m.ncai if not policy.source_policy(s).quarantined]
    print(f"ncai shas={len(m.ncai)} not-quarantined={len(bad)}")
    assert not bad, f"{len(bad)} NCAI SHA-256 values not quarantined"
    assert not any(policy.admissible(policy.source_policy(s), "T3") for s in m.ncai)


def test_fixture_readme_rows_match_bytes():
    fx = o.fixtures()  # raises naming the file on a mismatch
    assert len(fx) == 4
    assert {p.name for p in fx.values()} == {p.name for p in o.FIXTURES.glob("*.pdf")}


def test_fixture_readme_cites_release():
    assert "D-052" in o.README.read_text(encoding="utf-8")
    rows = o.readme_table()
    assert len(rows) == 4
    for f, _sha, url in rows:
        assert url.startswith("https://atnitribes.org/"), f


def test_fixture_shas_in_t0_manifest():
    _real_manifests()
    for sha in o.fixtures():
        p = policy.source_policy(sha)
        assert (p.org, p.tier, p.decision_id, p.quarantined) == ("atni", "T0", "D-052", False), sha


def test_fixture_text_has_no_contact_pattern():
    import pymupdf

    count = 0
    for path in o.fixtures().values():
        with pymupdf.open(path) as doc:
            count += sum(len(o.CONTACT.findall(page.get_text())) for page in doc)
    assert count == 0, f"contact-pattern matches in fixtures: {count}"


def test_original_committed_path():
    for f, sha in o.readme_rows().items():
        assert o.original(sha) == o.FIXTURES / f


def test_original_raises_for_quarantined():
    m = _real_manifests()
    if not m.ncai:
        pytest.skip("no NCAI manifest rows")
    with pytest.raises(QuarantinedError):
        o.original(sorted(m.ncai)[0])
