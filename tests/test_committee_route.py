"""The committee-report route is registered and refusal-only (design 1.5, tests 4.2; D-064 item 2, LG14).

No committee or convention text is ingested or read: refusals use the four committed ATNI fixtures, a truncated
copy written at test time, manifests derived from real headers, the pool's SHA-256 values through mode=ro, and
NCAI manifest metadata only (the functions take a SHA-256, never a path). Messages carry counts and hashes only.
"""
import pytest

from resist.errors import BadInput, QuarantinedError, TierRefused
from resist.services import genres, policy
from tests import originals as o
from tests.test_policy import _atni_row, _res_dir

ABSENT = "docs/resolutions table or manifests absent (gitignored; fresh clone)"


@pytest.fixture(autouse=True)
def pool_t0(data_root, monkeypatch):
    """pool_max_tier from the scratch pool (no pool.yaml: T0), never the real datapool's."""
    monkeypatch.setenv("RESIST_DATA_DIR", str(data_root))


def _mismatch(sha: str, res_dir=None) -> None:
    with pytest.raises(BadInput) as e:
        genres.committee_report(sha, res_dir)
    assert not isinstance(e.value, TierRefused) and str(e.value) == "genre-mismatch: resolution", sha


def test_committee_report_route_registered():
    assert "committee_report" in genres.ROUTES and "resolution" in genres.ROUTES


def test_committee_report_refuses_t0_resolution():
    if not policy.load_manifests().present:
        pytest.skip(ABSENT)
    for sha in o.fixtures():
        assert policy.source_policy(sha).tier == "T0", sha
        _mismatch(sha)
        assert genres.route(sha) == genres.ROUTES["resolution"]


def test_committee_report_refuses_unknown_sha(tmp_path):
    sha, _path = o.truncated_copy("Res-26-34.pdf", tmp_path)
    assert policy.source_policy(sha).tier == "T3"  # in no manifest (D-038)
    with pytest.raises(TierRefused):
        genres.committee_report(sha)
    with pytest.raises(TierRefused):
        genres.route(sha)


def test_committee_report_refuses_convention_material(tmp_path):
    sha, _path = o.fixture("Res-23-40.pdf")
    res = _res_dir(tmp_path, [_atni_row("Res-23-40.pdf", sha, source="atni-media-library",
                                        local_path="media/convention/committee-report.pdf")])
    assert policy.source_policy(sha, res).tier == "T3"  # D-064: convention-shaped media-library row
    with pytest.raises(TierRefused):
        genres.committee_report(sha, res)
    with pytest.raises(TierRefused):
        genres.route(sha, res)


def test_committee_report_refuses_ncai_metadata_only():
    ncai = policy.load_manifests().ncai
    if not ncai:
        pytest.skip("NCAI manifest absent")
    sha = sorted(ncai)[0]
    with pytest.raises(QuarantinedError):
        genres.committee_report(sha)
    with pytest.raises(QuarantinedError):
        genres.route(sha)


def test_pool_documents_never_committee_reports():
    db = o.pool_db()
    if not policy.load_manifests().present:
        pytest.skip(ABSENT)
    con = o.ro(db)
    try:
        shas = [s for (s,) in con.execute("select document_id from resolution")]
    finally:
        con.close()
    for s in shas:
        _mismatch(s)
    assert len(shas) == 1157  # report 07 section 4: every pool document is a resolution
