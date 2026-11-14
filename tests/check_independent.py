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
                   certainty, studies (data-check spans), rationale, and its sources or a
                   link to sources-<slug>.html, the page that holds its quotes
  id="gap-<slug>"  one element per gap
  id="edge-<slug>" one SVG <a> per graph edge; id="e-<slug>" its evidence section.
                   Its <path class="vis c-<certainty>"> line shows the certainty (line style);
                   its label shows the study count (data-check .../studies)
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

    def own_text(self) -> str:
        """Text written by the site, leaving out pack values (data-check) and quoted sentences."""
        parts: List[str] = []

        def walk(n: 'Node') -> None:
            for c in n.children:
                if isinstance(c, Node):
                    if 'data-check' in c.attrs or (c.tag == 'blockquote' and 'quote' in c.cls()):
                        continue
                    walk(c)
                    parts.append(' ')
                else:
                    parts.append(c)
        walk(self)
        return norm(''.join(parts))


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


REQUIRED_FIELDS = ('direction', 'certainty', 'studies', 'claims')


def shown_value(field: str, text: str) -> str:
    """Page text -> pack value. Counts must be the whole text, so "11" never passes for 1."""
    if field in ('studies', 'claims'):
        return norm(text).replace(',', '')
    return word_to_code(text)


# Attributes that make the browser fetch something. Only <a href="https://doi.org/...">
# may point off-site; anything else breaks the offline requirement.
FETCH_ATTRS = ('src', 'href', 'xlink:href', 'srcset', 'data', 'poster', 'action', 'formaction',
               'background', 'manifest', 'ping')
EXTERNAL = re.compile(r'(?:^|[\s,(\'"])(?:https?:)?//', re.I)
CSS_EXTERNAL = re.compile(r'url\(\s*["\']?\s*(?:https?:)?//|@import\s+(?:url\()?\s*["\']?\s*(?:https?:)?//', re.I)


# ------------------------------------------------------------------ checker

SOURCES_PAGE = re.compile(r'^sources-[a-z0-9-]+\.html$')


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
        """The finding's own block shows all its pooled values, its rationale and time points."""
        found = {}
        for n in el.iter():
            dc = n.attrs.get('data-check', '')
            for field in REQUIRED_FIELDS:
                if dc.endswith('/' + field) and '/claim/' not in dc and field not in found:
                    found[field] = n.text()
        for field in REQUIRED_FIELDS:
            if not self.ok(field in found, f'{where}: no {field} shown'):
                continue
            want = item[field]
            got = shown_value(field, found[field])
            self.ok(str(got) == str(want), f'{where}: {field} shows "{found[field]}", pack says "{want}"')
        text = el.text()
        self.ok(norm(item['certainty_rationale']) in text, f'{where}: certainty rationale missing or altered')
        # Time points by their own element and exact value (a text search would be fooled
        # by the same words inside the finding's source quotes).
        tps = {n.attrs['data-check'].rsplit('/', 1)[-1]: n.text() for n in el.iter()
               if '/time_points/' in n.attrs.get('data-check', '')}
        for i, tp in enumerate(item.get('time_points') or []):
            self.ok(tps.get(str(i)) == norm(str(tp)),
                    f'{where}: time point {i} should read "{tp}", page shows "{tps.get(str(i), "nothing")}"')

    def check_every_value(self, name: str, root: Node, prefix: str, items: List[dict],
                          interactions: Optional[List[dict]] = None) -> None:
        """Every number/grade shown ANYWHERE on the page (summary lists, tables, graph
        labels) equals the pack: direction, certainty, studies, claims and the
        per-direction study splits (study_directions/<dir>)."""
        by_slug = {slug(i['id']).split('--', 1)[-1] if prefix != 'q1graph' else slug(i['id']): i for i in items}
        by_slug.update({slug(i['id']): i for i in items})
        for n in root.iter():
            dc = n.attrs.get('data-check', '')
            parts = dc.split('/')
            if not dc or parts[0] != prefix or len(parts) < 3 or parts[1] == 'claim':
                continue
            split = None
            if parts[1] == 'interactions':
                if interactions is None or len(parts) != 4 or parts[3] not in REQUIRED_FIELDS:
                    continue
                idx = int(parts[2]) if parts[2].isdigit() else -1
                item = interactions[idx] if 0 <= idx < len(interactions) else None
                field = parts[3]
            elif len(parts) == 3 and parts[2] in REQUIRED_FIELDS:
                item, field = by_slug.get(parts[1]), parts[2]
            elif len(parts) == 4 and parts[2] == 'study_directions':
                item, field, split = by_slug.get(parts[1]), 'study_directions', parts[3]
            else:
                continue
            if not self.ok(item is not None, f'{name}: data-check "{dc}" refers to nothing in the pack'):
                continue
            if field not in item:
                continue
            shown = n.text()
            if split is not None:
                want = item['study_directions'].get(split, 0)
                got = shown_value('studies', shown)
            else:
                want, got = item[field], shown_value(field, shown)
            self.ok(str(got) == str(want), f'{name}: "{dc}" shows "{shown}", pack says "{want}"')

    def check_claims(self, where: str, el: Node, edge_ids: List[str], evidence: dict) -> None:
        """Each source must be shown with its finding: inside its block, or on the
        sources-*.html page that the block links to (one click away)."""
        claims: Dict[str, List[Node]] = {}
        roots = [el]
        for a in el.iter():
            href = a.attrs.get('href', '') if a.tag == 'a' else ''
            if SOURCES_PAGE.match(href):
                linked = self.page(href)
                if self.ok(linked is not None, f'{where}: links to missing source page {href}'):
                    roots.append(linked)
        for root in roots:
            for n in root.iter():
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

    def check_gap(self, where: str, el: Optional[Node], gap: dict) -> None:
        if not self.ok(el is not None, f'{where}: gap not shown'):
            return
        t = el.text().lower()
        self.ok('not studied' in t or 'no evidence' in t, f'{where}: gap does not say "Not studied"')
        # Scan only OUR wording: strip the pack's own text (searched_for, labels) first,
        # so neutral pack wording can never trip the check. Whole words only.
        ours = t
        pack_text = [gap.get('searched_for', '')] + [
            (gap.get(k) or {}).get('label', '') if isinstance(gap.get(k), dict) else str(gap.get(k) or '')
            for k in ('subject', 'outcome', 'source', 'target')]
        for s in pack_text:
            if s:
                ours = ours.replace(norm(s).lower(), ' ')
        for w in NEGATIVE_WORDS:
            self.ok(not re.search(r'(?<!\w)' + re.escape(w) + r'(?!\w)', ours),
                    f'{where}: gap is worded as a negative result ("{w}")')
        for n in el.iter():
            dc = n.attrs.get('data-check', '')
            self.ok(not dc.endswith(('/direction', '/certainty')),
                    f'{where}: gap carries a direction/certainty ({dc}), so it looks like a result')

    # sections
    def html_files(self) -> List[str]:
        """Every .html under site/, including subfolders, as paths relative to site/."""
        out = []
        for dirpath, _, files in os.walk(self.site):
            for f in files:
                if f.endswith('.html'):
                    out.append(os.path.relpath(os.path.join(dirpath, f), self.site).replace(os.sep, '/'))
        return sorted(out)

    def check_pages_basic(self) -> None:
        for name in ['index.html', 'q1.html', 'q1-graph.html', 'q2.html', 'q3.html']:
            self.ok(self.page(name) is not None, f'{name}: missing')
        for name in self.html_files():
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
                for attr in FETCH_ATTRS:
                    v = n.attrs.get(attr, '')
                    if v and EXTERNAL.search(v):
                        allowed = (n.tag == 'a' and attr in ('href', 'xlink:href')
                                   and v.strip().startswith('https://doi.org/'))
                        self.ok(allowed, f'{name}: external {n.tag} {attr}={v} (site must work offline)')
                self.ok(not CSS_EXTERNAL.search(n.attrs.get('style', '')),
                        f'{name}: inline style on <{n.tag}> loads an external resource')
                if n.tag == 'meta' and n.attrs.get('http-equiv', '').lower() == 'refresh':
                    self.ok(not EXTERNAL.search(n.attrs.get('content', '')), f'{name}: meta refresh to an external URL')
                if n.tag == 'style':
                    self.ok(not CSS_EXTERNAL.search(n.text()), f'{name}: <style> loads an external resource')
        for dirpath, _, files in os.walk(self.site):
            for f in files:
                if f.endswith(('.css', '.svg')):
                    with open(os.path.join(dirpath, f), encoding='utf-8', errors='replace') as fh:
                        body = fh.read()
                    self.ok(not CSS_EXTERNAL.search(body), f'{f}: loads an external resource')

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
            el = ids.get('gap-' + slug(g['id']))
            self.check_gap(f'{name} {g["id"]}', el, g)
            if el is not None and g.get('searched_for'):
                self.check_searched_for(f'{name} {g["id"]}', el, g)
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

    def check_searched_for(self, where: str, el: Node, gap: dict) -> None:
        """The pack's "searched for" sentence must be shown: in the gap marker itself, or once for
        its row as data-template with {outcome} standing for this gap's outcome."""
        want = norm(gap['searched_for'])
        if want in el.text():
            return
        outcome = (gap.get('outcome') or {}).get('label', '')
        sec = el.parent
        while sec is not None and not (sec.tag == 'section'):
            sec = sec.parent
        notes = [n for n in (sec.iter() if sec is not None else []) if 'data-template' in n.attrs]
        ok = any(norm(n.attrs['data-template'].replace('{outcome}', outcome)) == want
                 and norm(n.attrs['data-template'].replace('{outcome}', 'that outcome')) in n.text()
                 for n in notes)
        self.ok(ok, f'{where}: what was searched for ("{gap["searched_for"]}") is not shown')

    def check_q2_honesty(self) -> None:
        root = self.page('q2.html')
        if root is None:
            return
        # No made-up time spans: "N years" may appear only inside a pack value or a quoted
        # sentence, on q2.html and on the source pages that hold its quotes.
        for name in ['q2.html'] + [n for n in self.html_files() if n.startswith('sources-q2--')]:
            r = self.page(name)
            for m in re.finditer(r'\d+\s*(?:-|–|to)?\s*\d*\s*years?', r.own_text() if r else ''):
                self.ok(False, f'{name}: "{m.group(0)}" written by the site, not from the pack or a quote')
        sa = self.load('q2')['short_answer']
        text = root.text()
        self.ok(sa['time_to_reference'] is None, 'q2 pack: time_to_reference is no longer null; recheck the Q2 page')
        note = norm(sa['time_to_reference_note'])
        # Compare ELEMENT order in the document (not text search, which repeated text can fool):
        # the innermost element holding the note must come before the first finding.
        order = {id(n): i for i, n in enumerate(root.iter())}
        holders = [n for n in root.iter() if note in n.text()]
        innermost = [n for n in holders if not any(c is not n and note in c.text() for c in n.iter())]
        if self.ok(bool(innermost), 'q2.html: "no study says how long" note missing'):
            first = next((n for n in root.iter() if n.attrs.get('id', '').startswith('f-')), None)
            if first is not None:
                self.ok(order[id(innermost[0])] < order[id(first)],
                        'q2.html: the "how long" answer must come before the findings')
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
                # Visible on the arrow itself (no hover). Studies: the exact number from the
                # label's data-check span, so "1" can't pass for "11". Certainty: the line's own
                # style (thickness + dashes, explained in the legend), so the drawn line must
                # carry exactly the pack's grade, c-low can't pass for c-very_low.
                shown = {}
                for n in a.iter():
                    dc = n.attrs.get('data-check', '')
                    for field in ('certainty', 'studies'):
                        if dc.endswith('/' + field) and field not in shown:
                            shown[field] = n.text()
                if e['direction'] == 'mixed' and e['kind'] != 'moderation':
                    # A mixed arrow shows how many studies went up and down ("⇅ ↑5 ↓1"); the
                    # values themselves are checked against the pack by check_every_value.
                    dcs = {n.attrs.get('data-check', '') for n in a.iter()}
                    for d_ in ('increase', 'decrease'):
                        self.ok(f'q1graph/{s}/study_directions/{d_}' in dcs,
                                f'{where}: mixed arrow does not show how many studies found {d_}')
                elif self.ok('studies' in shown, f'{where}: studies not visible on the arrow (needs hover?)'):
                    self.ok(str(shown_value('studies', shown['studies'])) == str(e['studies']),
                            f'{where}: arrow shows studies "{shown["studies"]}", pack says "{e["studies"]}"')
                if 'certainty' in shown:
                    self.ok(str(shown_value('certainty', shown['certainty'])) == str(e['certainty']),
                            f'{where}: arrow shows certainty "{shown["certainty"]}", pack says "{e["certainty"]}"')
                lines = [n for n in a.iter() if n.tag == 'path' and 'vis' in n.cls()]
                styles = {c[2:] for v in lines for c in v.cls() if c.startswith('c-')}
                self.ok(styles == {e['certainty']},
                        f'{where}: arrow line drawn as certainty {sorted(styles) or "none"}, pack says '
                        f'"{e["certainty"]}"')
                self.ok('d-' + e['direction'] in a.cls(), f'{where}: arrow not styled with its direction')
                # Screen-reader name: the exact phrase, anchored by ": " and ", " on each side.
                label = norm(a.attrs.get('aria-label', '')).lower()
                n_studies = e['studies']
                phrase = ': %s, certainty %s, %d %s' % (e['direction'].replace('_', ' '),
                                                        e['certainty'].replace('_', ' '), n_studies,
                                                        'study' if n_studies == 1 else 'studies')
                self.ok(phrase in label, f'{where}: accessible name should contain "{phrase}", got "{label}"')
                self.ok(a.tag == 'a' and a.attrs.get('href', '').startswith('#'),
                        f'{where}: arrow is not a keyboard-reachable link to its evidence')
            sec = ids.get('e-' + s)
            if self.ok(sec is not None, f'{where}: no evidence section'):
                self.check_values(where, sec, e)
                self.check_claims(where, sec, e['edge_ids'], g['evidence'])
        self.ok(any(e['kind'] == 'moderation' and ('edge-' + slug(e['id'])) in svg_ids for e in g['edges']),
                f'{name}: moderation edge not drawn')
        for gap in g['gaps']:
            self.check_gap(f'{name} {gap["id"]}', ids.get('e-' + slug(gap['id'])), gap)
            # The specific gap arrow must be drawn, and named as "no evidence", not a result.
            ga = svg_ids.get('gapedge-' + slug(gap['id']))
            if self.ok(ga is not None, f'{name} {gap["id"]}: "no evidence" arrow not drawn in the SVG'):
                gl = (ga.attrs.get('aria-label', '') + ' ' + ga.text()).lower()
                self.ok('no evidence' in gl or 'not studied' in gl,
                        f'{name} {gap["id"]}: gap arrow not labelled "no evidence"')
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
