"""Load and validate the Lane 3 answer pack.

load_all(answers_dir) -> SiteData. Raises LoadError on any validation failure.
"""
from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

EFFECT_DIRECTIONS = ("increase", "decrease", "mixed", "no_effect", "unclear")
REFERENCE_DIRECTIONS = ("below_reference", "comparable", "above_reference", "mixed", "unclear")
CERTAINTIES = ("high", "moderate", "low", "very_low")
REQUIRED_FINDING_FIELDS = ("id", "direction", "certainty", "studies", "claims", "subject", "outcome")


class LoadError(Exception):
    pass


def slug(s: str) -> str:
    s = (s.lower().replace('~>', '--mod--').replace('->', '--to--')
         .replace('+', '--and--').replace(':', '--'))
    return re.sub(r'[^a-z0-9-]+', '-', s.replace('_', '-')).strip('-')


def clean_doi(doi: Optional[str]) -> Optional[str]:
    if doi is None:
        return None
    d = str(doi).strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.lower().startswith(prefix):
            d = d[len(prefix):]
    return d or None


def uses_reference_vocab(item: Dict[str, Any]) -> bool:
    """Reference vocabulary only if 'reference' appears in direction_meaning (spec bug fix)."""
    return "reference" in str(item.get("direction_meaning") or "")


@dataclass(frozen=True)
class Quote:
    edge_id: str
    quote: str
    title: str
    year: Optional[int]
    doi: Optional[str]
    subject: str
    predicate: str
    object: str
    negated: bool
    direction: str
    certainty_grade: str  # the claim's own grade, NOT the finding's certainty
    evidence_types: Tuple[str, ...]
    comparator: Optional[str]
    ecosystem_context: Optional[str]
    causal_language: Optional[str]
    document_id: Optional[str]
    raw: Dict[str, Any] = field(compare=False, hash=False, repr=False)


@dataclass(frozen=True)
class Finding:
    id: str
    slug: str
    question: str
    kind: str  # 'finding' or 'trend'
    subject_id: str
    subject_label: str
    outcome_id: str
    outcome_label: str
    direction: str
    certainty: str
    certainty_rationale: Optional[str]
    studies: int
    claims: int
    study_directions: Dict[str, int]
    claim_directions: Dict[str, int]
    edge_ids: Tuple[str, ...]
    quotes: Tuple[Quote, ...]
    reference: bool
    raw: Dict[str, Any] = field(compare=False, hash=False, repr=False)

    @property
    def label(self) -> str:
        return "%s: %s" % (self.subject_label, self.outcome_label)


@dataclass(frozen=True)
class Gap:
    id: str
    slug: str
    question: str
    subject_id: str
    subject_label: str
    outcome_id: str
    outcome_label: str
    searched_for: str
    raw: Dict[str, Any] = field(compare=False, hash=False, repr=False)

    @property
    def label(self) -> str:
        return "%s × %s" % (self.subject_label, self.outcome_label)


@dataclass(frozen=True)
class Graph:
    id: str
    nodes: Tuple[Dict[str, Any], ...]
    edges: Tuple[Dict[str, Any], ...]
    gaps: Tuple[Dict[str, Any], ...]
    set_aside: Tuple[Dict[str, Any], ...]
    limitations: Tuple[str, ...]
    evidence: Dict[str, Quote]
    raw: Dict[str, Any] = field(compare=False, hash=False, repr=False)

    def node(self, node_id: str) -> Dict[str, Any]:
        for n in self.nodes:
            if n["id"] == node_id:
                return n
        raise KeyError(node_id)

    def edge(self, edge_id: str) -> Dict[str, Any]:
        for e in self.edges:
            if e["id"] == edge_id:
                return e
        raise KeyError(edge_id)


@dataclass(frozen=True)
class Question:
    qid: str
    file: str
    id: str
    text: str
    rule: Optional[str]
    how_built: Optional[str]
    findings: Tuple[Finding, ...]
    trends: Tuple[Finding, ...]
    gaps: Tuple[Gap, ...]
    limitations: Tuple[str, ...]
    evidence: Dict[str, Quote]
    extra: Dict[str, Any]
    raw: Dict[str, Any] = field(compare=False, hash=False, repr=False)

    def all_findings(self) -> Tuple[Finding, ...]:
        return self.findings + self.trends


@dataclass(frozen=True)
class SiteData:
    questions: Dict[str, Question]
    kinds: Dict[str, str]                                # qid -> layout, from detect_kind()
    graphs: Dict[str, Graph]                             # qid -> its *_graph.json, if any
    edge_index: Dict[str, Dict[str, Tuple[Quote, ...]]]  # qid -> graph edge id -> quotes
    graph_join: Dict[str, str]                           # finding slug -> graph edge id (slugs carry the qid)
    grids: Dict[str, Dict[str, Any]]                     # qid -> gap-map grid, for "gapmap" questions
    manifest: Dict[str, Any]
    warnings: Tuple[str, ...]

    def graph_qids(self) -> List[str]:
        """Questions that have a graph page, in question order."""
        return [qid for qid in self.questions if qid in self.graphs]


# ---------------------------------------------------------------- shape
# The page layout follows what the answer file contains, not its id, so a new question
# dropped into answers/ gets the right layout with no code change. Checked in this order:
GAPMAP, COMPARISON, EFFECTS, GENERIC = 'gapmap', 'comparison', 'effects', 'generic'
SUMMARY_COUNTS = ('cells', 'filled', 'thin', 'empty')


def detect_kind(q: 'Question') -> str:
    """gapmap: a summary with cell counts and findings that carry a density (study counts per cell).
    comparison: compared with a reference (time_to_reference, reference directions) or over time.
    effects: plain findings that increase, decrease or are mixed.
    generic: anything else."""
    summary = q.extra.get('summary') or {}
    if (all(_is_count(summary.get(k)) for k in SUMMARY_COUNTS) and q.findings
            and all(f.raw.get('density') for f in q.findings)):
        return GAPMAP
    sa = q.extra.get('short_answer') or {}
    if 'time_to_reference' in sa or any(f.reference for f in q.findings) or q.trends:
        return COMPARISON
    if any(f.direction in ('increase', 'decrease', 'mixed') for f in q.findings):
        return EFFECTS
    return GENERIC


# ---------------------------------------------------------------- helpers

def _is_count(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _quote(edge_id: str, d: Dict[str, Any]) -> Quote:
    year = d.get("year")
    return Quote(
        edge_id=edge_id,
        quote=" ".join(str(d.get("quote") or "").split()),
        title=" ".join(str(d.get("title") or "").split()),
        year=year if isinstance(year, int) else None,
        doi=clean_doi(d.get("doi")),
        subject=str(d.get("subject") or ""),
        predicate=str(d.get("predicate") or ""),
        object=str(d.get("object") or ""),
        negated=bool(d.get("negated")),
        direction=str(d.get("direction") or ""),
        certainty_grade=str(d.get("certainty_grade") or ""),
        evidence_types=tuple(d.get("evidence_types") or ()),
        comparator=d.get("comparator"),
        ecosystem_context=d.get("ecosystem_context"),
        causal_language=d.get("causal_language"),
        document_id=d.get("document_id"),
        raw=d,
    )


def _check_pooled(where: str, item: Dict[str, Any], evidence: Dict[str, Any], errors: List[str]) -> None:
    for k in REQUIRED_FINDING_FIELDS:
        if k not in item:
            errors.append("%s: missing field '%s'" % (where, k))
    vocab = REFERENCE_DIRECTIONS if uses_reference_vocab(item) else EFFECT_DIRECTIONS
    if item.get("direction") not in vocab:
        errors.append("%s: direction %r not in %s" % (where, item.get("direction"), list(vocab)))
    if item.get("certainty") not in CERTAINTIES:
        errors.append("%s: unknown certainty %r" % (where, item.get("certainty")))
    for k in ("studies", "claims"):
        if k in item and not _is_count(item[k]):
            errors.append("%s: %s must be a non-negative int, got %r" % (where, k, item[k]))
    for k in ("study_directions", "claim_directions"):
        for dk, dv in (item.get(k) or {}).items():
            if not _is_count(dv):
                errors.append("%s: %s.%s must be a non-negative int, got %r" % (where, k, dk, dv))
    for eid in item.get("edge_ids") or ():
        if eid not in evidence:
            errors.append("%s: edge_id %s not in evidence" % (where, eid))


def _finding(qid: str, kind: str, d: Dict[str, Any], quotes: Dict[str, Quote]) -> Finding:
    return Finding(
        id=d["id"], slug=slug(d["id"]), question=qid, kind=kind,
        subject_id=d["subject"]["id"], subject_label=d["subject"]["label"],
        outcome_id=d["outcome"]["id"], outcome_label=d["outcome"]["label"],
        direction=d["direction"], certainty=d["certainty"],
        certainty_rationale=d.get("certainty_rationale"),
        studies=d["studies"], claims=d["claims"],
        study_directions=dict(d.get("study_directions") or {}),
        claim_directions=dict(d.get("claim_directions") or {}),
        edge_ids=tuple(d.get("edge_ids") or ()),
        quotes=tuple(quotes[e] for e in d.get("edge_ids") or () if e in quotes),
        reference=uses_reference_vocab(d),
        raw=d,
    )


def _read_json(path: str, errors: List[str]) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        errors.append("%s: not valid JSON (%s)" % (path, exc))
        return None


# ---------------------------------------------------------------- questions

def _load_question(path: str, errors: List[str], warnings: List[str]) -> Optional[Question]:
    name = os.path.basename(path)
    qid = name.split("_", 1)[0]
    d = _read_json(path, errors)
    if d is None:
        return None
    if not isinstance(d.get("findings"), list):
        errors.append("%s: no 'findings' list" % name)
        return None
    evidence_raw = d.get("evidence") or {}
    quotes = {k: _quote(k, v) for k, v in evidence_raw.items()}
    null_dois = sum(1 for q in quotes.values() if q.doi is None)
    if null_dois:
        warnings.append("%s: %d quotes have no DOI" % (name, null_dois))

    seen_ids = set()
    seen_slugs: Dict[str, str] = {}

    def register(where: str, item_id: str) -> None:
        if item_id in seen_ids:
            errors.append("%s: duplicate id %s" % (where, item_id))
        seen_ids.add(item_id)
        s = slug(item_id)
        if s in seen_slugs and seen_slugs[s] != item_id:
            errors.append("%s: slug collision %s (%s vs %s)" % (where, s, item_id, seen_slugs[s]))
        seen_slugs[s] = item_id

    def pooled(items: List[Dict[str, Any]], kind: str) -> Tuple[Finding, ...]:
        out = []
        for i, f in enumerate(items):
            where = "%s %s[%d] %s" % (name, kind, i, f.get("id"))
            n_err = len(errors)
            _check_pooled(where, f, evidence_raw, errors)
            if len(errors) > n_err:
                continue
            if not f.get("certainty_rationale"):
                warnings.append("%s: no certainty_rationale" % where)
            register(name, f["id"])
            out.append(_finding(qid, kind, f, quotes))
        return tuple(out)

    findings = pooled(d["findings"], "finding")
    trends = pooled(d.get("with_time") or [], "trend")

    gaps = []
    for g in d.get("gaps") or []:
        try:
            register(name, g["id"])
            gaps.append(Gap(
                id=g["id"], slug=slug(g["id"]), question=qid,
                subject_id=g["subject"]["id"], subject_label=g["subject"]["label"],
                outcome_id=g["outcome"]["id"], outcome_label=g["outcome"]["label"],
                searched_for=g.get("searched_for") or "", raw=g))
        except (KeyError, TypeError) as exc:
            errors.append("%s: malformed gap %r (%s)" % (name, g.get("id"), exc))

    extra: Dict[str, Any] = {}
    for k in ("short_answer", "summary", "interactions"):
        if k in d:
            extra[k] = d[k]
    for i, it in enumerate(extra.get("interactions") or []):
        if it.get("edge_id") not in evidence_raw:
            errors.append("%s: interactions[%d] edge_id %s not in evidence" % (name, i, it.get("edge_id")))
        if it.get("direction") not in EFFECT_DIRECTIONS:
            errors.append("%s: interactions[%d] direction %r unknown" % (name, i, it.get("direction")))

    summary = extra.get("summary")
    if summary is not None:
        for k in ("cells", "filled", "thin", "empty"):
            if not _is_count(summary.get(k)):
                errors.append("%s: summary.%s must be a non-negative int" % (name, k))
        if not errors:
            if len(findings) + len(gaps) != summary["cells"]:
                errors.append("%s: findings+gaps = %d but summary.cells = %d"
                              % (name, len(findings) + len(gaps), summary["cells"]))
            if len(findings) != summary["filled"]:
                errors.append("%s: findings = %d but summary.filled = %d" % (name, len(findings), summary["filled"]))
            thin = sum(1 for f in findings if f.studies == 1)
            if thin != summary["thin"]:
                errors.append("%s: single-study findings = %d but summary.thin = %d" % (name, thin, summary["thin"]))
            if len(gaps) != summary["empty"]:
                errors.append("%s: gaps = %d but summary.empty = %d" % (name, len(gaps), summary["empty"]))
            ids = {f.id for f in findings}
            for c in summary.get("densest") or []:
                if c not in ids:
                    errors.append("%s: summary.densest names unknown finding %s" % (name, c))

    return Question(
        qid=qid, file=name, id=d.get("id", qid), text=d.get("question", ""),
        rule=d.get("rule"), how_built=d.get("how_built"),
        findings=findings, trends=trends, gaps=tuple(gaps),
        limitations=tuple(d.get("limitations") or ()),
        evidence=quotes, extra=extra, raw=d)


# ---------------------------------------------------------------- graph

def _load_graph(path: str, errors: List[str], warnings: List[str]) -> Optional[Graph]:
    name = os.path.basename(path)
    d = _read_json(path, errors)
    if d is None:
        return None
    evidence_raw = d.get("evidence") or {}
    quotes = {k: _quote(k, v) for k, v in evidence_raw.items()}
    node_ids = {n["id"] for n in d.get("nodes") or []}
    edge_ids = set()
    slugs: Dict[str, str] = {}
    for i, e in enumerate(d.get("edges") or []):
        where = "%s edges[%d] %s" % (name, i, e.get("id"))
        _check_pooled(where, dict(e, subject=e.get("source"), outcome=e.get("target")), evidence_raw, errors)
        if e.get("id") in edge_ids:
            errors.append("%s: duplicate edge id" % where)
        edge_ids.add(e.get("id"))
        s = slug(e.get("id", ""))
        if s in slugs:
            errors.append("%s: slug collision %s" % (where, s))
        slugs[s] = e.get("id")
        if e.get("source") not in node_ids:
            errors.append("%s: unknown source node %s" % (where, e.get("source")))
        if e.get("kind") == "effect" and e.get("target") not in node_ids:
            errors.append("%s: unknown target node %s" % (where, e.get("target")))
    for e in d.get("edges") or []:
        if e.get("kind") == "moderation" and e.get("target_edge") not in edge_ids:
            errors.append("%s: moderation edge %s targets unknown edge %s" % (name, e["id"], e.get("target_edge")))
    for n in d.get("nodes") or []:
        for m in n.get("members") or []:
            if m not in node_ids:
                errors.append("%s: combination %s names unknown member %s" % (name, n["id"], m))
    for g in d.get("gaps") or []:
        if slug(g["id"]) in slugs:
            errors.append("%s: gap slug collides with an edge: %s" % (name, g["id"]))
    return Graph(
        id=d.get("id", ""), nodes=tuple(d.get("nodes") or ()), edges=tuple(d.get("edges") or ()),
        gaps=tuple(d.get("gaps") or ()), set_aside=tuple(d.get("set_aside") or ()),
        limitations=tuple(d.get("limitations") or ()), evidence=quotes, raw=d)


def _join_graph(q: Question, g: Graph, errors: List[str]) -> Dict[str, str]:
    join: Dict[str, str] = {}
    by_pair = {(e["source"], e["target"]): e for e in g.edges if e.get("kind") == "effect"}
    for f in q.findings:
        e = by_pair.get((f.subject_id, f.outcome_id))
        if e is None:
            errors.append("graph join: finding %s has no graph edge %s->%s" % (f.id, f.subject_id, f.outcome_id))
            continue
        for k in ("direction", "certainty", "studies", "claims"):
            if e.get(k) != getattr(f, k):
                errors.append("graph join: %s %s: finding says %r, graph edge %s says %r"
                              % (f.id, k, getattr(f, k), e["id"], e.get(k)))
        if set(e.get("edge_ids") or ()) != set(f.edge_ids):
            errors.append("graph join: %s edge_ids differ from graph edge %s" % (f.id, e["id"]))
        join[f.slug] = e["id"]
    return join


def _grid(q: Question, errors: List[str]) -> Dict[str, Any]:
    rows: List[Tuple[str, str]] = []
    cols: List[Tuple[str, str]] = []
    for item in list(q.findings) + list(q.gaps):
        if item.subject_id not in [r[0] for r in rows]:
            rows.append((item.subject_id, item.subject_label))
        if item.outcome_id not in [c[0] for c in cols]:
            cols.append((item.outcome_id, item.outcome_label))
    cells: Dict[Tuple[str, str], Any] = {}
    for item in list(q.findings) + list(q.gaps):
        key = (item.subject_id, item.outcome_id)
        if key in cells:
            errors.append("%s grid: cell %s x %s has more than one entry" % ((q.qid,) + key))
        cells[key] = item
    for r, _ in rows:
        for c, _ in cols:
            if (r, c) not in cells:
                errors.append("%s grid: cell %s x %s is neither a finding nor a gap" % (q.qid, r, c))
    return {"rows": rows, "cols": cols, "cells": cells}


# ---------------------------------------------------------------- entry

def load_all(answers_dir: str = "answers") -> SiteData:
    errors: List[str] = []
    warnings: List[str] = []
    files = sorted(glob.glob(os.path.join(answers_dir, "*.json")))
    if not files:
        raise LoadError("no answer files in %s" % answers_dir)
    questions: Dict[str, Question] = {}
    graphs: Dict[str, Graph] = {}
    for path in files:
        name = os.path.basename(path)
        qid = name.split("_", 1)[0]
        if name.endswith("_graph.json"):
            g = _load_graph(path, errors, warnings)
            if g is not None:
                graphs[qid] = g
            continue
        if qid in questions:
            errors.append("two answer files share the prefix %s" % qid)
            continue
        q = _load_question(path, errors, warnings)
        if q is not None:
            questions[qid] = q
    for qid in graphs:
        if qid not in questions:
            errors.append("graph file for %s has no matching answer file" % qid)

    kinds = {qid: detect_kind(q) for qid, q in questions.items()}
    edge_index: Dict[str, Dict[str, Tuple[Quote, ...]]] = {}
    graph_join: Dict[str, str] = {}
    for qid, g in graphs.items():
        if qid not in questions:
            continue
        join = _join_graph(questions[qid], g, errors)
        graph_join.update(join)
        idx = {e["id"]: tuple(g.evidence[x] for x in e.get("edge_ids") or () if x in g.evidence) for e in g.edges}
        edge_index[qid] = idx
        total = sum(len(v) for v in idx.values())
        if total != len(g.evidence):
            errors.append("%s edge index: %d quotes across edges but graph evidence has %d"
                          % (qid, total, len(g.evidence)))
        unmatched = [e["id"] for e in g.edges if e["id"] not in join.values()]
        if len(unmatched) + len(join) != len(g.edges):
            errors.append("%s graph join: edge accounting mismatch" % qid)

    grids = {qid: _grid(q, errors) for qid, q in questions.items() if kinds[qid] == GAPMAP}

    manifest: Dict[str, Any] = {}
    mpath = os.path.join(os.path.dirname(os.path.abspath(answers_dir)), "manifest.json")
    if os.path.exists(mpath):
        m = _read_json(mpath, errors)
        manifest = m or {}

    if errors:
        raise LoadError("\n".join(errors))
    return SiteData(questions=questions, kinds=kinds, graphs=graphs, edge_index=edge_index,
                    graph_join=graph_join, grids=grids, manifest=manifest, warnings=tuple(warnings))
