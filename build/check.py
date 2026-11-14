"""Self-check the built site against the answer pack.

check_site(out, data) -> list of problems (one actionable line each).
Runnable: python3 build/check.py site/ [--answers answers/]
The pack is reloaded through load.py; the renderer is never trusted.
"""
from __future__ import annotations

import os
import re
import sys
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Set, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from load import COMPARISON, GAPMAP, LoadError, SiteData, load_all, slug  # noqa: E402

DIR_WORDS = {
    'Increase': 'increase', 'Decrease': 'decrease', 'Mixed': 'mixed', 'No effect': 'no_effect',
    'Unclear': 'unclear', 'Below reference': 'below_reference', 'Comparable': 'comparable',
    'Above reference': 'above_reference',
    'Behind': 'below_reference', 'Matches': 'comparable', 'Ahead': 'above_reference',  # plain words (Q2 chart)
}
CERT_WORDS = {}
for _k, _w in (('high', 'High'), ('moderate', 'Moderate'), ('low', 'Low'), ('very_low', 'Very low')):
    CERT_WORDS[_w] = _k
    CERT_WORDS[_w + ' certainty'] = _k

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}
YEARS_RE = re.compile(r'\d+ years?')


def norm(s: str) -> str:
    return ' '.join(s.split())


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: Set[str] = set()
        self.links: List[Tuple[str, str]] = []  # (attr, value)
        self.claims: Set[str] = set()
        self.claim_list: List[str] = []  # in page order, with repeats
        self.checks: List[Tuple[str, str]] = []
        self.ev_boxes = 0
        self.edge_ids: Set[str] = set()
        self.classes_td: Dict[str, int] = {}
        self.free_text: List[str] = []
        self._stack: List[Tuple[str, bool]] = []  # (tag, exempt)
        self._caps: List[List[Any]] = []  # [depth, path, buf]

    def _exempt(self) -> bool:
        return any(e for _, e in self._stack)

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        a = {k: (v or '') for k, v in attrs}
        self._attrs(tag, a)
        if tag in VOID:
            return
        cls = a.get('class', '').split()
        exempt = 'data-check' in a or (tag == 'blockquote' and 'quote' in cls)
        self._stack.append((tag, exempt))
        if 'data-check' in a:
            self._caps.append([len(self._stack), a['data-check'], []])

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self._attrs(tag, {k: (v or '') for k, v in attrs})

    def _attrs(self, tag: str, a: Dict[str, str]) -> None:
        if 'id' in a:
            self.ids.add(a['id'])
        for k in ('href', 'src'):
            if k in a:
                self.links.append((k, a[k]))
        if 'data-claim' in a:
            self.claims.add(a['data-claim'])
            self.claim_list.append(a['data-claim'])
        cls = a.get('class', '').split()
        if tag == 'details' and 'ev' in cls:
            self.ev_boxes += 1
        if tag == 'a' and 'edge' in cls and 'id' in a:
            self.edge_ids.add(a['id'])
        if tag == 'td':
            for c in cls:
                self.classes_td[c] = self.classes_td.get(c, 0) + 1

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                depth = i + 1
                while self._caps and self._caps[-1][0] >= depth:
                    d, path, buf = self._caps.pop()
                    self.checks.append((path, norm(''.join(buf))))
                    if self._caps:
                        self._caps[-1][2].append(''.join(buf))
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if self._caps:
            self._caps[-1][2].append(data)
        if not self._exempt():
            self.free_text.append(data)


def parse(path: str) -> Page:
    p = Page()
    with open(path, encoding='utf-8') as fh:
        p.feed(fh.read())
    p.close()
    return p


# --------------------------------------------------------------- expected values

class Unknown(Exception):
    pass


def _finding_by_slug(items, s):
    for f in items:
        if f.slug == s:
            return f
    raise Unknown('no finding with slug %s' % s)


def _quote_field(evidence: Dict[str, Any], edge_id: str, field: str) -> Any:
    if edge_id not in evidence:
        raise Unknown('no claim %s' % edge_id)
    q = evidence[edge_id]
    if field not in ('subject', 'object', 'year', 'quote', 'title', 'doi'):
        raise Unknown('claim field %s' % field)
    return getattr(q, field)


def _pooled_field(item: Dict[str, Any], rest: List[str]) -> Tuple[str, Any]:
    field = rest[0]
    if field in ('direction', 'certainty', 'studies', 'claims'):
        return field, item[field]
    if field in ('study_directions', 'claim_directions', 'time_points') and len(rest) == 2:
        v = item.get(field)
        if field == 'time_points':
            return 'text', v[int(rest[1])]
        if field == 'study_directions' and v is not None:
            # the pack leaves out a direction no study found; the graph shows it as 0 ("↑0 ↓0")
            return 'int', v.get(rest[1], 0)
        return 'int', v[rest[1]]
    raise Unknown('field %s' % '/'.join(rest))


def expected(path: str, data: SiteData) -> Tuple[str, Any]:
    """Return (kind, value) where kind in direction|certainty|int|text|studies|claims."""
    parts = path.split('/')
    head, rest = parts[0], parts[1:]
    if head == 'manifest':
        v: Any = data.manifest
        for p in rest:
            v = v[p]
        return ('int' if isinstance(v, int) else 'text'), v
    if head.endswith('graph') and head[:-len('graph')] in data.questions:
        g = data.graphs.get(head[:-len('graph')])  # e.g. q1graph -> the graph of q1
        if g is None:
            raise Unknown('no graph')
        if rest[0] == 'count':
            return 'int', len({'nodes': g.nodes, 'edges': g.edges, 'gaps': g.gaps}[rest[1]])
        if rest[0] == 'limitations':
            return 'text', g.limitations[int(rest[1])]
        if rest[0] == 'claim':
            return 'auto', _quote_field(g.evidence, rest[1], rest[2])
        for e in g.edges:
            if slug(e['id']) == rest[0]:
                return _pooled_field(e, rest[1:])
        raise Unknown('no graph edge with slug %s' % rest[0])
    q = data.questions.get(head)
    if q is None:
        raise Unknown('no question %s' % head)
    if rest[0] == 'summary':
        return 'int', q.extra['summary'][rest[1]]
    if rest[0] == 'limitations':
        return 'text', q.limitations[int(rest[1])]
    if rest[0] == 'short_answer':
        v = q.extra['short_answer'][rest[1]]
        if len(rest) > 2:
            v = v[int(rest[2])]
        return 'text', v
    if rest[0] == 'interactions':
        return _pooled_field(q.extra['interactions'][int(rest[1])], rest[2:])
    if rest[0] == 'claim':
        return 'auto', _quote_field(q.evidence, rest[1], rest[2])
    f = _finding_by_slug(q.all_findings(), rest[0])
    return _pooled_field(f.raw, rest[1:])


def compare(kind: str, page_text: str, pack: Any) -> Optional[Any]:
    """Return the page value as read if it differs from the pack, else None."""
    if kind == 'auto':
        kind = 'int' if isinstance(pack, int) else 'text'
    if kind == 'direction':
        got = DIR_WORDS.get(page_text, page_text)
        return None if got == pack else page_text
    if kind == 'certainty':
        got = CERT_WORDS.get(page_text, page_text)
        return None if got == pack else page_text
    if kind in ('int', 'studies', 'claims'):
        try:
            got = int(page_text.replace(',', ''))
        except ValueError:
            return page_text
        return None if got == pack else got
    return None if page_text == norm(str(pack)) else page_text


# --------------------------------------------------------------- checks

def check_site(out: str, data: SiteData, answers_dir: str = 'answers/') -> List[str]:
    try:
        data = load_all(answers_dir)  # reload: never trust what the renderer was given
    except LoadError as exc:
        return ['pack failed to load: %s' % str(exc).splitlines()[0]]
    problems: List[str] = []
    pages: Dict[str, Page] = {}
    if not os.path.isdir(out):
        return ['site directory %s does not exist: run ./build.sh %s first' % (out, out)]
    for name in sorted(os.listdir(out)):
        if name.endswith('.html'):
            pages[name] = parse(os.path.join(out, name))
    if 'index.html' not in pages:
        problems.append('no index.html in %s' % out)

    # 1. every data-check value equals the pack
    n_checked = 0
    for name, p in pages.items():
        for path, text in p.checks:
            n_checked += 1
            try:
                kind, pack = expected(path, data)
            except (Unknown, KeyError, IndexError, ValueError) as exc:
                problems.append('%s data-check "%s": cannot resolve in pack (%s)' % (name, path, exc))
                continue
            bad = compare(kind, text, pack)
            if bad is not None:
                problems.append('%s %s: page says %s, pack says %s' % (name, path, bad, pack))
    if n_checked == 0:
        problems.append('no data-check spans found: numbers are unverified')

    # 2. every finding and trend has id f-{slug} on its page
    for qid, q in data.questions.items():
        pname = '%s.html' % qid
        p = pages.get(pname)
        if p is None:
            problems.append('%s missing for question %s' % (pname, qid))
            continue
        for f in q.all_findings():
            if 'f-' + f.slug not in p.ids:
                problems.append('%s: no element with id="f-%s" for %s' % (pname, f.slug, f.id))
        for gp in q.gaps:
            if 'gap-' + gp.slug not in p.ids:
                problems.append('%s: no gap marker id="gap-%s" for %s' % (pname, gp.slug, gp.id))

    # 3 + 4. graph edges and evidence boxes
    for gq in data.graph_qids():  # every question that has a *_graph.json
        g = data.graphs[gq]
        gname = '%s-graph.html' % gq
        p = pages.get(gname)
        if p is None:
            problems.append('%s missing' % gname)
        else:
            for e in g.edges:
                s = slug(e['id'])
                if 'edge-' + s not in p.edge_ids:
                    problems.append('%s: SVG has no <a class="edge" id="edge-%s">' % (gname, s))
                if 'e-' + s not in p.ids:
                    problems.append('%s: no evidence section id="e-%s"' % (gname, s))
            if len(p.edge_ids) != len(g.edges):
                problems.append('%s: %d SVG edges, pack has %d' % (gname, len(p.edge_ids), len(g.edges)))
            for gp in g.gaps:
                if 'e-' + slug(gp['id']) not in p.ids:
                    problems.append('%s: no gap panel id="e-%s"' % (gname, slug(gp['id'])))
            # each arrow's quotes are on its own page, sources-e-<slug>.html, and that page
            # must show exactly this arrow's claims (not another arrow's), each once
            for e in g.edges:
                sname = 'sources-e-%s.html' % slug(e['id'])
                sp = pages.get(sname)
                if sp is None:
                    problems.append('%s missing for graph arrow %s' % (sname, e['id']))
                    continue
                want = sorted(e.get('edge_ids') or [])
                if sorted(sp.claim_list) != want:
                    problems.append('%s: shows claims %s, arrow %s has %s'
                                    % (sname, sorted(sp.claim_list), e['id'], want))

    # 5. gap-map cells (Q3 today; any question with that shape)
    for gq, kind in data.kinds.items():
        pname = '%s.html' % gq
        if kind != GAPMAP or pname not in pages:
            continue
        s = data.questions[gq].extra['summary']
        td = pages[pname].classes_td
        filled = sum(td.get('d-' + k, 0) for k in ('thin', 'some', 'dense'))
        for label, got, want in (('filled', filled, s['filled']), ('single-study', td.get('d-thin', 0), s['thin']),
                                 ('empty', td.get('empty', 0), s['empty'])):
            if got != want:
                problems.append('%s gap map: %d %s cells, pack summary says %d' % (pname, got, label, want))

    # 6 + 7. links
    for name, p in pages.items():
        for attr, val in p.links:
            if re.match(r'https?://', val):
                if not (attr == 'href' and val.startswith('https://doi.org/')):
                    problems.append('%s: external %s %s (only https://doi.org/ links allowed)' % (name, attr, val))
                continue
            if re.match(r'^[a-z]+:', val):
                problems.append('%s: unexpected %s scheme %s' % (name, attr, val))
                continue
            target, _, frag = val.partition('#')
            tname = target or name
            tpath = os.path.join(out, tname)
            if not os.path.exists(tpath):
                problems.append('%s: %s="%s" points to missing file %s' % (name, attr, val, tname))
                continue
            if frag:
                tp = pages.get(tname)
                if tp is None or frag not in tp.ids:
                    problems.append('%s: link %s has no matching id="%s" in %s' % (name, val, frag, tname))

    # 8. Q2 says what it cannot answer, and invents no durations (on q2.html and on the
    #    sources-q2--*.html pages that hold its quotes)
    for cq, kind in data.kinds.items():  # Q2 today; any comparison-shaped question
        pname = '%s.html' % cq
        if kind != COMPARISON or pname not in pages:
            continue
        p = pages[pname]
        note = (data.questions[cq].extra.get('short_answer') or {}).get('time_to_reference_note')
        alltext = norm(' '.join(t for _, t in p.checks) + ' ' + ' '.join(p.free_text))
        if note and norm(note) not in alltext:
            problems.append('%s: the pack\'s time_to_reference_note is missing' % pname)
        for name in sorted(n for n in pages if n == pname or n.startswith('sources-%s--' % cq)):
            free = norm(' '.join(pages[name].free_text))
            for m in YEARS_RE.finditer(free):
                ctx = free[max(0, m.start() - 40):m.end() + 20]
                problems.append('%s: "%s" outside a data-check span or quote: ...%s...' % (name, m.group(0), ctx))

    # 9. each finding's source page shows exactly that finding's claims
    for qid, q in data.questions.items():
        for f in q.all_findings():
            sname = 'sources-%s.html' % f.slug
            sp = pages.get(sname)
            if sp is None:
                continue  # sources shown on the answer page itself; check 9b covers them
            if sorted(sp.claim_list) != sorted(f.edge_ids):
                problems.append('%s: shows claims %s, finding %s cites %s'
                                % (sname, sorted(sp.claim_list), f.id, sorted(f.edge_ids)))

    # 9b. every cited claim is on some page
    shown: Set[str] = set()
    for p in pages.values():
        shown |= p.claims
    for q in data.questions.values():
        for f in q.all_findings():
            for eid in f.edge_ids:
                if eid not in shown:
                    problems.append('%s: claim %s cited by %s is not shown on any page' % (q.qid, eid, f.id))
    return problems


def main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description='Check a built site against the answer pack.')
    ap.add_argument('out', nargs='?', default='site/')
    ap.add_argument('--answers', default=os.path.join(os.path.dirname(HERE), 'answers'))
    args = ap.parse_args(argv)
    try:
        data = load_all(args.answers)
    except LoadError as exc:
        for line in str(exc).splitlines():
            print('[check] LOAD ERROR %s' % line)
        return 2
    problems = check_site(args.out, data, args.answers)
    for p in problems:
        print('[check] FAIL %s' % p)
    print('[check] %d problems' % len(problems))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
