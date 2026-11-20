"""Resolver lifecycle and export parity using neutral markers, never resolution fixtures."""

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest

from resist import refs
from resist.errors import DependencyError
from resist.models import Availability, ClauseText, RefCandidate, Span
from resist.refs.link import link
from scripts import build_pages


class MarkerResolver:
    version = "1"

    def __init__(self, name, available=True):
        self.name = name
        self.ok = available
        self.availability_calls = 0
        self.find_calls = 0

    def available(self):
        self.availability_calls += 1
        return Availability(self.ok, "marker-unavailable", "marker-remediation")

    def find(self, text):
        self.find_calls += 1
        digest = hashlib.sha256(text.text.encode()).hexdigest()
        found = []
        for token, family, issuer in (("beta", "ncai_resolution", "ncai"),
                                      ("alpha", "atni_resolution", "atni")):
            start = text.text.find(token)
            if start >= 0:
                found.append(RefCandidate(
                    Span(text.sha256, digest, text.page, start, start + len(token), token),
                    family, "unlinked", (self.name,), f"{issuer}:res:marker", issuer=issuer,
                    number="marker", logical_id=f"{issuer}:res:marker"))
        return found


def test_resolvers_are_constructed_and_checked_once_for_a_batch(monkeypatch):
    made = []

    def get(kind, name):
        assert kind == "resolver"
        resolver = MarkerResolver(name)
        made.append(resolver)
        return resolver

    monkeypatch.setattr(refs.registry, "names", lambda kind: ["b", "a"])
    monkeypatch.setattr(refs.registry, "get", get)
    resolvers = refs.load_resolvers()
    text = ClauseText("0" * 64, "alpha beta")
    first = refs.find_with(text, resolvers)
    second = refs.find_with(text, resolvers)
    assert first == second
    assert len(made) == 2
    assert [r.availability_calls for r in made] == [1, 1]
    assert [r.find_calls for r in made] == [2, 2]
    assert [c.span.quote for c in first] == ["alpha", "beta"]
    assert all(c.extractors == ("a", "b") for c in first)


def test_missing_dependency_refuses_batch(monkeypatch):
    unavailable = MarkerResolver("missing", available=False)
    monkeypatch.setattr(refs.registry, "get", lambda *_: unavailable)
    with pytest.raises(DependencyError, match="marker-unavailable"):
        refs.load_resolvers(["missing"])
    assert unavailable.find_calls == 0


def test_find_all_keeps_selection_and_result_contract(monkeypatch):
    chosen = []

    def get(kind, name):
        chosen.append((kind, name))
        return MarkerResolver(name)

    monkeypatch.setattr(refs.registry, "get", get)
    text = ClauseText("0" * 64, "alpha")
    assert refs.find_all(text, ["a"]) == MarkerResolver("a").find(text)
    assert chosen == [("resolver", "a")]
    assert refs.find_all(text, []) == []


def alias_schema(con):
    con.execute("create table issuer_alias (work_id text, issuer text, number text, source text, "
                "logical_id text)")


def test_optional_linking_preserves_ambiguity_and_quarantine():
    with closing(sqlite3.connect(":memory:")) as con:
        alias_schema(con)
        con.execute("insert into issuer_alias values ('work-a', 'atni', 'marker', 'pool', "
                    "'atni:res:marker')")
        text = ClauseText("0" * 64, "alpha beta")
        resolvers = [MarkerResolver("a")]
        raw = refs.find_with(text, resolvers)
        linked = refs.find_with(text, resolvers, con)
        assert linked[0] == replace(raw[0], state="resolved", registry_id="work-a")
        assert linked[1] == raw[1]
        con.execute("insert into issuer_alias values ('work-b', 'atni', 'marker', 'atni-table', "
                    "'atni:res:marker')")
        assert refs.find_with(text, resolvers, con)[0].state == "ambiguous"


def test_linking_requires_alias_schema():
    with closing(sqlite3.connect(":memory:")) as con, pytest.raises(DependencyError, match="no-issuer-alias"):
        refs.find_with(ClauseText("0" * 64, "alpha"), [MarkerResolver("a")], con)


def export_rows(dst):
    dst.execute("create table resolution (id integer, document_id text, resolution_number text)")
    dst.executemany("insert into resolution values (?, ?, ?)", [(1, "0" * 64, None), (2, "1" * 64, None)])
    dst.execute("create table statement (id integer, resolution_id integer, text text, page_number integer)")
    dst.execute("insert into statement values (1, 1, ?, 1)", ("🙂 alpha beta",))
    dst.execute("create table citation (id integer, resolution_id integer, text text, citation_type text, "
                "linked_resolution_id integer)")
    dst.executemany("insert into citation values (?, 1, ?, ?, 2)",
                    [(1, "alpha", "prior_atni_resolution"), (2, "beta", "prior_atni_resolution"),
                     (3, "gamma", "other")])


@pytest.mark.parametrize("linking", [False, True])
def test_public_cite_rows_match_previous_orchestration(monkeypatch, linking):
    def previous(text, resolvers, con=None):
        found = refs.merge(*(r.find(text) for r in resolvers))
        return link(found, con) if con is not None else found

    with closing(sqlite3.connect(":memory:")) as src, closing(sqlite3.connect(":memory:")) as dst:
        if linking:
            alias_schema(src)
            src.execute("create table document (work_id text, sha256 text)")
            src.execute("insert into document values ('work-a', ?)", ("1" * 64,))
            src.execute("insert into issuer_alias values ('work-a', 'atni', 'marker', 'pool', "
                        "'atni:res:marker')")
        export_rows(dst)
        resolvers = [MarkerResolver("b"), MarkerResolver("a")]
        actual = build_pages._cites(src, dst, resolvers)
        rows = dst.execute("select * from cite order by id").fetchall()
        dst.execute("drop table cite")
        monkeypatch.setattr(build_pages, "find_with", previous)
        expected = build_pages._cites(src, dst, resolvers)
        assert actual == expected
        assert rows == dst.execute("select * from cite order by id").fetchall()
        assert rows[0][3:5] == (3, 8)  # UTF-16 presentation stays in the export adapter.
        assert rows[1][-1] is None  # NCAI never inherits a legacy link.
        assert actual["rows"] == 3


def test_builder_uses_shared_loader(monkeypatch):
    resolvers = [MarkerResolver("a")]
    monkeypatch.setattr(build_pages, "load_resolvers", lambda: resolvers)
    assert build_pages._resolvers() is resolvers
