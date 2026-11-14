#!/usr/bin/env python3
"""Independent check of the built site against the answer pack.

    python3 tests/check_independent.py site/ [--answers answers/] [--max-page-kb N]

Why a second checker: build/check.py shares build/load.py with the renderer, so a
loader bug could fool both. This script imports nothing from build/: it reads the
raw JSON in answers/ and the HTML in site/ with the standard library only, and
checks that every required item is present, complete and correct.

Exit code 0 = PASS, 1 = at least one problem.

Page contract it relies on (from the MVP renderer):
  id="f-<slug>"    one element per finding/trend, containing its direction,
                   certainty, studies (data-check spans), rationale and sources
  id="gap-<slug>"  one element per gap
  id="edge-<slug>" one SVG <a> per graph edge; id="e-<slug>" its evidence section
  data-claim="<edge id>" on each source; data-check="<...>/direction|certainty|studies"
If the renderer changes these names, this script fails loudly (that's intended).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from html.parser import HTMLParser
from typing import Dict, Iterator, List, Optional
from urllib.parse import unquote

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
        'source', 'track', 'wbr'}
PAGES = {'q1': 'q1.html', 'q2': 'q2.html', 'q3': 'q3.html'}
FILES = {'q1': 'q1_tree_planting.json', 'q2': 'q2_created_marshes.json',
         'q3': 'q3_grassland_gaps.json', 'graph': 'q1_tree_planting_graph.json'}
# Phrases that would present a gap as a tested negative result. ("not evidence of no
# effect" is the right message, so bare "no effect" is deliberately not listed.)
NEGATIVE_WORDS = ('ineffective', 'does not work', "doesn't work", 'fails to', 'harmful',
                  'has no effect', 'had no effect', 'no effect (tested)', 'decreases', 'increases')


# ------------------------------------------------------------------ tiny DOM

class Node:
    __slots__ = ('tag', 'attrs', 'children', 'parent')

    def __init__(self, tag: str, attrs: Dict[str, str], parent: Optional['Node']):
        self.tag, self.attrs, self.children, self.parent = tag, attrs, [], parent

    def iter(self) -> Iterator['Node']:
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.iter()

    def text(self) -> str:
        parts: List[str] = []

        def walk(n: 'Node') -> None:
            for c in n.children:
                if isinstance(c, Node):
                    walk(c)
                    parts.append(' ')
                else:
                    parts.append(c)
        walk(self)
        return norm(''.join(parts))

    def cls(self) -> List[str]:
        return self.attrs.get('class', '').split()


class Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node('#root', {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k: (v or '') for k, v in attrs}, self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, {k: (v or '') for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def norm(s: str) -> str:
    return ' '.join(s.split())


def slug(s: str) -> str:
    """Re-implemented on purpose (not imported) so the two sides stay independent."""
    s = (s.lower().replace('~>', '--mod--').replace('->', '--to--')
         .replace('+', '--and--').replace(':', '--'))
    return re.sub(r'[^a-z0-9-]+', '-', s.replace('_', '-')).strip('-')


def word_to_code(text: str) -> str:
    t = norm(text).lower()
    t = re.sub(r'\s*certainty$', '', t)
    return t.replace(' ', '_')


# ------------------------------------------------------------------ checker

class Checker:
    def __init__(self, site: str, answers: str) -> None:
        self.site, self.answers = site, answers
        self.problems: List[str] = []
        self.n = 0
        self.dom: Dict[str, Node] = {}
        self.ids: Dict[str, Dict[str, Node]] = {}
        self.raw: Dict[str, str] = {}

    # helpers
    def ok(self, cond: bool, msg: str) -> bool:
        self.n += 1
        if not cond:
            self.problems.append(msg)
        return cond

    def page(self, name: str) -> Optional[Node]:
        if name not in self.dom:
            path = os.path.join(self.site, name)
            if not os.path.isfile(path):
                return None
            with open(path, encoding='utf-8') as fh:
                self.raw[name] = fh.read()
            b = Builder()
            b.feed(self.raw[name])
            self.dom[name] = b.root
            ids: Dict[str, Node] = {}
            for n in b.root.iter():
                i = n.attrs.get('id')
                if i:
                    self.ok(i not in ids, f'{name}: duplicate id="{i}"')
                    ids[i] = n
            self.ids[name] = ids
        return self.dom[name]

    def load(self, key: str) -> dict:
        with open(os.path.join(self.answers, FILES[key]), encoding='utf-8') as fh:
            return json.load(fh)

    def check_values(self, where: str, el: Node, item: dict) -> None:
        found = {}
        for n in el.iter():
            dc = n.attrs.get('data-check', '')
            for field in ('direction', 'certainty', 'studies'):
                if dc.endswith('/' + field) and '/claim/' not in dc and field not in found:
                    found[field] = n.text()
        for field in ('direction', 'certainty', 'studies'):
            if not self.ok(field in found, f'{where}: no {field} shown'):
                continue
            want = item[field]
            got = found[field].replace(',', '') if field == 'studies' else word_to_code(found[field])
            self.ok(str(got) == str(want), f'{where}: {field} shows "{found[field]}", pack says "{want}"')
        rationale = norm(item['certainty_rationale'])
        self.ok(rationale in el.text(), f'{where}: certainty rationale missing or altered')

    def check_every_value(self, name: str, root: Node, prefix: str, items: List[dict],
                          interactions: Optional[List[dict]] = None) -> None:
        """Every direction/certainty/studies value shown ANYWHERE on the page (summary
        lists, tables, graph labels), not just inside each finding's own block."""
        by_slug = {slug(i['id']).split('--', 1)[-1] if prefix != 'q1graph' else slug(i['id']): i for i in items}
        by_slug.update({slug(i['id']): i for i in items})
        for n in root.iter():
            dc = n.attrs.get('data-check', '')
            parts = dc.split('/')
            if not dc or parts[0] != prefix or parts[-1] not in ('direction', 'certainty', 'studies'):
                continue
            field = parts[-1]
            if len(parts) == 3:
                item = by_slug.get(parts[1])
            elif len(parts) == 4 and parts[1] == 'interactions' and interactions is not None:
                idx = int(parts[2]) if parts[2].isdigit() else -1
                item = interactions[idx] if 0 <= idx < len(interactions) else None
            else:
                continue
            if not self.ok(item is not None, f'{name}: data-check "{dc}" refers to nothing in the pack'):
                continue
            if field not in item:
                continue
            shown = n.text()
            got = shown.replace(',', '') if field == 'studies' else word_to_code(shown)
            self.ok(str(got) == str(item[field]), f'{name}: "{dc}" shows "{shown}", pack says "{item[field]}"')

    def check_claims(self, where: str, el: Node, edge_ids: List[str], evidence: dict) -> None:
        claims: Dict[str, List[Node]] = {}
        for n in el.iter():
            c = n.attrs.get('data-claim')
            if c:
                claims.setdefault(c, []).append(n)
        for eid in edge_ids:
            if not self.ok(eid in claims, f'{where}: source {eid} not shown with this finding'):
                continue
            ev = evidence[eid]
            box = claims[eid][0]
            self.ok(norm(ev['quote']) in box.text(), f'{where}: quote for {eid} missing or altered')
            if ev.get('doi'):
                doi = ev['doi'].strip().lower()
                hrefs = [unquote(a.attrs.get('href', '')).lower() for a in box.iter() if a.tag == 'a']
                self.ok(any(h.startswith('https://doi.org/') and h.endswith(doi) for h in hrefs),
                        f'{where}: DOI link for {eid} ({ev["doi"]}) missing')

    def check_gap(self, where: str, el: Optional[Node]) -> None:
        if not self.ok(el is not None, f'{where}: gap not shown'):
            return
        t = el.text().lower()
        self.ok('not studied' in t or 'no evidence' in t, f'{where}: gap does not say "Not studied"')
        for w in NEGATIVE_WORDS:
            self.ok(w not in t, f'{where}: gap is worded as a negative result ("{w}")')
        for n in el.iter():
            dc = n.attrs.get('data-check', '')
            self.ok(not dc.endswith(('/direction', '/certainty')),
                    f'{where}: gap carries a direction/certainty ({dc}), so it looks like a result')

    # sections
    def check_pages_basic(self) -> None:
        for name in ['index.html', 'q1.html', 'q1-graph.html', 'q2.html', 'q3.html']:
            if not self.ok(self.page(name) is not None, f'{name}: missing'):
                continue
        for name in sorted(os.listdir(self.site)):
            if not name.endswith('.html'):
                continue
            root = self.page(name)
            tags = [n for n in root.iter()]
            html_el = [n for n in tags if n.tag == 'html']
            self.ok(bool(html_el) and html_el[0].attrs.get('lang'), f'{name}: <html> has no lang')
            self.ok(sum(n.tag == 'h1' for n in tags) == 1, f'{name}: must have exactly one <h1>')
            titles = [n for n in tags if n.tag == 'title' and n.parent is not None and n.parent.tag == 'head']
            self.ok(bool(titles) and titles[0].text(), f'{name}: no <title>')
            self.ok(any(n.tag == 'main' for n in tags), f'{name}: no <main>')
            self.ok(any(n.tag == 'meta' and n.attrs.get('name') == 'viewport' for n in tags),
                    f'{name}: no viewport meta')
            self.ok(not any(n.tag == 'canvas' for n in tags), f'{name}: uses <canvas> (labels must be DOM text)')
            for n in tags:
                for attr in ('src', 'href', 'srcset', 'data', 'poster'):
                    v = n.attrs.get(attr, '')
                    if re.match(r'\s*(https?:)?//', v):
                        allowed = n.tag == 'a' and attr == 'href' and v.startswith('https://doi.org/')
                        self.ok(allowed, f'{name}: external {n.tag} {attr}={v} (site must work offline)')
                if n.tag == 'style':
                    self.ok(not re.search(r'url\(\s*["\']?(https?:)?//|@import', n.text()),
                            f'{name}: <style> loads an external resource')
        for dirpath, _, files in os.walk(self.site):
            for f in files:
                if f.endswith('.css'):
                    with open(os.path.join(dirpath, f), encoding='utf-8') as fh:
                        css = fh.read()
                    self.ok(not re.search(r'url\(\s*["\']?(https?:)?//|@import\s+["\']?(https?:)?//', css),
                            f'{f}: CSS loads an external resource')

    def check_index(self) -> None:
        root = self.page('index.html')
        if root is None:
            return
        hrefs = {a.attrs.get('href', '').split('#')[0] for a in root.iter() if a.tag == 'a'}
        for target in ['q1.html', 'q1-graph.html', 'q2.html', 'q3.html']:
            self.ok(target in hrefs, f'index.html: no link to {target}')

    def check_question(self, qid: str) -> None:
        name = PAGES[qid]
        root = self.page(name)
        if root is None:
            return
        data = self.load(qid)
        ids = self.ids[name]
        self.ok(norm(data['question']) in root.text(), f'{name}: question text missing')
        items = data['findings'] + data.get('with_time', [])
        for f in items:
            where = f'{name} {f["id"]}'
            el = ids.get('f-' + slug(f['id']))
            if not self.ok(el is not None, f'{where}: finding not shown'):
                continue
            self.check_values(where, el, f)
            self.check_claims(where, el, f['edge_ids'], data['evidence'])
            if f.get('lags'):
                self.ok('lag' in el.text().lower(), f'{where}: lagging attribute not marked as lagging')
        self.check_every_value(name, root, qid, items, data.get('interactions'))
        self.ok(sum(i.startswith('f-') for i in ids) == len(items),
                f'{name}: {sum(i.startswith("f-") for i in ids)} findings shown, pack has {len(items)}')
        for g in data['gaps']:
            self.check_gap(f'{name} {g["id"]}', ids.get('gap-' + slug(g['id'])))
        self.ok(sum(i.startswith('gap-') for i in ids) == len(data['gaps']),
                f'{name}: {sum(i.startswith("gap-") for i in ids)} gaps shown, pack has {len(data["gaps"])}')
        text = root.text()
        for i, lim in enumerate(data['limitations']):
            self.ok(norm(lim) in text, f'{name}: limitation {i} missing')
        for it in data.get('interactions', []):
            boxes = [n for n in root.iter() if n.attrs.get('data-claim') == it['edge_id']]
            if self.ok(bool(boxes), f'{name}: combined-treatment claim {it["edge_id"]} not shown'):
                self.ok(norm(data['evidence'][it['edge_id']]['quote']) in boxes[0].text(),
                        f'{name}: quote for combined-treatment claim {it["edge_id"]} missing')

    def check_q2_honesty(self) -> None:
        root = self.page('q2.html')
        if root is None:
            return
        sa = self.load('q2')['short_answer']
        text = root.text()
        self.ok(sa['time_to_reference'] is None, 'q2 pack: time_to_reference is no longer null; recheck the Q2 page')
        note = norm(sa['time_to_reference_note'])
        pos_note = text.find(note)
        self.ok(pos_note >= 0, 'q2.html: "no study says how long" note missing')
        first = next((n for n in root.iter() if n.attrs.get('id', '').startswith('f-')), None)
        if pos_note >= 0 and first is not None:
            pos_first = text.find(first.text()[:60])
            self.ok(pos_note < pos_first, 'q2.html: the "how long" answer must come before the findings')
        for a in sa['lagging_attributes']:
            self.ok(norm(a) in text, f'q2.html: lagging attribute "{a}" missing')

    def check_graph(self) -> None:
        name = 'q1-graph.html'
        root = self.page(name)
        if root is None:
            return
        g = self.load('graph')
        ids = self.ids[name]
        svgs = [n for n in root.iter() if n.tag == 'svg' and any(c.tag == 'text' for c in n.iter())]
        if not self.ok(bool(svgs), f'{name}: no SVG graph with text labels'):
            return
        svg = max(svgs, key=lambda s: sum(1 for _ in s.iter()))
        labels = {n.text() for n in svg.iter() if n.tag == 'text'}
        for node in g['nodes']:
            # exact match per <text> element (a substring match would be fooled by
            # "Site preparation" inside the combination box's label)
            self.ok(norm(node['label']) in labels, f'{name}: node label "{node["label"]}" is not SVG text')
        self.check_every_value(name, root, 'q1graph', g['edges'])
        svg_ids = {n.attrs.get('id'): n for n in svg.iter() if n.attrs.get('id')}
        page_text = root.text()
        for e in g['edges']:
            s = slug(e['id'])
            where = f'{name} {e["id"]}'
            a = svg_ids.get('edge-' + s)
            if self.ok(a is not None, f'{where}: arrow not drawn in the SVG'):
                visible = a.text()
                cert = e['certainty'].replace('_', ' ')
                self.ok(cert in visible.lower(), f'{where}: certainty not visible on the arrow (needs hover?)')
                self.ok(str(e['studies']) in visible, f'{where}: study count not visible on the arrow')
                self.ok('d-' + e['direction'] in a.cls(), f'{where}: arrow not styled with its direction')
                label = a.attrs.get('aria-label', '').lower()
                self.ok(e['direction'].replace('_', ' ') in label and cert in label,
                        f'{where}: arrow has no accessible name with direction and certainty')
                self.ok(a.tag == 'a' and a.attrs.get('href', '').startswith('#'),
                        f'{where}: arrow is not a keyboard-reachable link to its evidence')
            sec = ids.get('e-' + s)
            if self.ok(sec is not None, f'{where}: no evidence section'):
                self.check_values(where, sec, e)
                self.check_claims(where, sec, e['edge_ids'], g['evidence'])
        self.ok(any(e['kind'] == 'moderation' and ('edge-' + slug(e['id'])) in svg_ids for e in g['edges']),
                f'{name}: moderation edge not drawn')
        for gap in g['gaps']:
            self.check_gap(f'{name} {gap["id"]}', ids.get('e-' + slug(gap['id'])))
            self.ok(any('gap' in ' '.join(n.cls()) for n in svg.iter()), f'{name}: gap not drawn in the SVG')
        for sa in g.get('set_aside', []):
            self.ok(norm(sa['why']) in page_text, f'{name}: set-aside claim {sa["edge_id"]} and its reason missing')
            if sa['edge_id'] in g['evidence']:
                self.ok(norm(g['evidence'][sa['edge_id']]['quote']) in page_text,
                        f'{name}: set-aside claim {sa["edge_id"]} quote missing')
        for i, lim in enumerate(g['limitations']):
            self.ok(norm(lim) in page_text, f'{name}: limitation {i} missing')
        rows = max((sum(1 for r in t.iter() if r.tag == 'tr') for t in root.iter() if t.tag == 'table'), default=0)
        self.ok(rows >= len(g['edges']), f'{name}: no text table listing all {len(g["edges"])} arrows')

    def weights(self, max_kb: Optional[int]) -> List[str]:
        out = []
        for name in sorted(self.raw):
            kb = len(self.raw[name].encode('utf-8')) // 1024
            out.append(f'{name} {kb} KB')
            if max_kb is not None:
                self.ok(kb <= max_kb, f'{name}: {kb} KB is over the {max_kb} KB page budget')
        return out

    def run(self, max_kb: Optional[int] = None) -> List[str]:
        if not os.path.isdir(self.site):
            return [f'{self.site} does not exist: run ./build.sh {self.site} first']
        self.check_pages_basic()
        self.check_index()
        for qid in PAGES:
            self.check_question(qid)
        self.check_q2_honesty()
        self.check_graph()
        self.page_weights = self.weights(max_kb)
        return self.problems


def main(argv: Optional[List[str]] = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('site', nargs='?', default='site/')
    ap.add_argument('--answers', default=os.path.join(os.path.dirname(here), 'answers'))
    ap.add_argument('--max-page-kb', type=int, default=None, help='fail if any page is larger')
    args = ap.parse_args(argv)
    c = Checker(args.site, args.answers)
    problems = c.run(args.max_page_kb)
    for p in problems:
        print(f'[independent] FAIL {p}')
    for w in getattr(c, 'page_weights', []):
        print(f'[independent] size {w}')
    if problems:
        print(f'[independent] FAIL: {len(problems)} of {c.n} checks')
        return 1
    print(f'[independent] PASS: {c.n} checks')
    return 0


if __name__ == '__main__':
    sys.exit(main())
