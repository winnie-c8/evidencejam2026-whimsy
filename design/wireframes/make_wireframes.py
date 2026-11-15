"""Greyscale wireframes for 2.1A (finding card), 2.3A (Q1) and 2.6A (Q3), from the real pack.

python3 design/wireframes/make_wireframes.py  ->  design/wireframes/out/*.html

Each page is written twice: desktop (1440 wide) and phone (375 wide), so each can be
captured into Figma as its own frame. Content follows the PR #51 hand-off; layout
borrows the editorial grid of the inspiration site (numbered sections, 1px rules,
big serif question, small uppercase labels, square corners). Not part of the site build.
"""
from __future__ import annotations

import html
import os
import re
import sys
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'build'))
from load import Finding, Gap, load_all  # noqa: E402

OUT = os.path.join(HERE, 'out')

DIR = {
    'increase': ('▲', 'Increases'), 'decrease': ('▼', 'Decreases'), 'mixed': ('⇅', 'Mixed'),
    'no_effect': ('–', 'No effect'), 'unclear': ('?', 'Unclear'),
}
VOTE = {'increase': 'up', 'decrease': 'down', 'mixed': 'mixed', 'no_effect': 'none', 'unclear': 'unclear'}
CERT_N = {'high': 4, 'moderate': 3, 'low': 2, 'very_low': 1}
CERT_W = {'high': 'High', 'moderate': 'Moderate', 'low': 'Low', 'very_low': 'Very low'}
START = {'high': 'Proper experiments (treated vs. untreated plots)', 'moderate': 'Other experiments or controlled studies',
         'low': 'Observational studies', 'very low': 'Models or case studies'}
STEP = [
    (r'studies disagree', "Studies didn't all agree"),
    (r'single study', 'Only one study'),
    (r'no comparator', 'Most claims have no comparison group'),
    (r'(\d+) studies agree', r'\1 studies agree'),
    (r'mechanistic', 'Shows how it works, not just that it works'),
]


def e(s: Any) -> str:
    return html.escape('' if s is None else str(s), quote=True)


def plural(n: int, one: str, many: str) -> str:
    return '%d %s' % (n, one if n == 1 else many)


# ---------------------------------------------------------------- pieces

def chip(d: str) -> str:
    sym, word = DIR[d]
    return '<span class="chip chip-%s"><span aria-hidden="true">%s</span> %s</span>' % (d, sym, word)


def bars(c: str) -> str:
    n = CERT_N[c]
    cells = ''.join('<i class="%s"></i>' % ('on' if i < n else 'off') for i in range(4))
    return '<span class="bars" aria-hidden="true">%s</span> <b>%s</b>' % (cells, CERT_W[c])


def agreement(f: Finding) -> str:
    sd = f.study_directions
    order = [k for k in ('increase', 'decrease', 'mixed', 'no_effect', 'unclear') if sd.get(k)]
    segs = ''.join('<i class="seg seg-%s" style="flex:%d"></i>' % (k, sd[k]) for k in order)
    words = ' · '.join('%d %s' % (sd[k], VOTE[k]) for k in order)
    return ('<span class="agree"><span class="aggbar" aria-hidden="true">%s</span>'
            '<span>%s: %s</span></span>' % (segs, plural(f.studies, 'study', 'studies'), words))


def agree_word(f: Finding) -> str:
    r = f.certainty_rationale or ''
    if 'disagree' in r:
        return "✗ Studies didn't all agree"
    m = re.search(r'(\d+) studies agree', r)
    if m:
        return '✓ %s studies agree' % m.group(1)
    if f.studies == 1:
        return '– Only one study'
    return '✓ No disagreement'


def checklist(f: Finding) -> Tuple[str, str]:
    r = f.certainty_rationale or ''
    m = re.match(r'start ([a-z ]+?) \(', r)
    start = m.group(1) if m else 'high'
    pts = {'high': 4, 'moderate': 3, 'low': 2, 'very low': 1}.get(start, 4)
    rows = ['<li class="ok"><span>✓ For: %s</span><span>start %d</span></li>' % (e(START.get(start, start)), pts)]
    first_ok, first_bad = START.get(start, start), None
    for sign, txt in re.findall(r'; ([+-])1 ([^;]+?)(?= ->|;|$)', r):
        word = txt
        for pat, rep in STEP:
            if re.search(pat, txt):
                word = re.sub(r'.*?' + pat + r'.*', rep, txt)
                break
        good = sign == '+'
        if not good and first_bad is None:
            first_bad = word
        rows.append('<li class="%s"><span>%s %s: %s</span><span>%s1</span></li>'
                    % ('ok' if good else 'bad', '✓' if good else '✗', 'For' if good else 'Against', e(word),
                       '+' if good else '−'))
    rows.append('<li class="sum"><span>= %s</span><span>%d</span></li>' % (CERT_W[f.certainty], CERT_N[f.certainty]))
    summary = '%s: %s%s.' % (CERT_W[f.certainty], first_ok.lower(),
                             ', though %s' % first_bad[0].lower() + first_bad[1:] if first_bad else '')
    return summary, '<ul class="checks">%s</ul>' % ''.join(rows)


def papers(f: Finding) -> "OrderedDict[str, List[Any]]":
    groups: "OrderedDict[str, List[Any]]" = OrderedDict()
    for q in f.quotes:
        groups.setdefault(q.doi or q.title, []).append(q)
    return groups


def sources_panel(f: Finding, n_show: int = 2) -> str:
    groups = papers(f)
    years = sorted({qs[0].year for qs in groups.values() if qs[0].year})
    undated = sum(1 for qs in groups.values() if not qs[0].year)
    span = ('%d' % years[0] if len(years) == 1 else '%d to %d' % (years[0], years[-1])) if years else 'no years given'
    types: Dict[str, int] = {}
    for qs in groups.values():
        t = (qs[0].evidence_types or ('not given',))[0].replace('_', ' ')
        types[t] = types.get(t, 0) + 1
    tline = ', '.join('%d %s' % (n, t) for t, n in sorted(types.items(), key=lambda x: -x[1]))
    summary = '%s, %s%s: %s.' % (plural(len(groups), 'paper', 'papers'), span,
                                 ' (%d undated)' % undated if undated and years else '', tline)
    items = []
    for qs in list(groups.values())[:n_show]:
        q = qs[0]
        items.append('<li><blockquote>%s</blockquote><p class="cite"><a href="#">%s</a> · %s · %s</p></li>'
                     % (e(q.quote[:220] + ('…' if len(q.quote) > 220 else '')), e(q.title), q.year or 'no year',
                        e((q.evidence_types or ('',))[0].replace('_', ' ').capitalize())))
    return ('<p class="psum">%s</p><ul class="quotes">%s</ul><a class="more" href="#">All %s, %s →</a>'
            % (e(summary), ''.join(items), plural(len(groups), 'paper', 'papers'),
               plural(len(f.quotes), 'quote', 'quotes')))


def pathways(data: Any, f: Finding) -> Optional[str]:
    g = data.q1_graph
    if g is None:
        return None
    by = {(x['source'], x['target']): x for x in g.edges if x.get('kind') == 'effect'}
    conds = [n for n in g.nodes if n.get('kind') == 'condition']
    routes = [(c, by[(f.subject_id, c['id'])], by[(c['id'], f.outcome_id)]) for c in conds
              if (f.subject_id, c['id']) in by and (c['id'], f.outcome_id) in by]
    if not routes:
        return ('<p class="psum">None in this research.</p><p class="note">No study here linked this factor to '
                'seedlings through a condition.</p>')

    def step(x: Dict[str, Any]) -> str:
        sym, word = DIR[x['direction']]
        return '<div class="step">↓ %s %s · %s certainty · %s</div>' % (
            sym, word, CERT_W[x['certainty']], plural(x['studies'], 'study', 'studies'))
    chains = ''.join('<div class="chain"><div class="node">%s</div>%s<div class="node">%s</div>%s'
                     '<div class="node">%s</div></div>' % (e(f.subject_label), step(a), e(c['label']), step(b),
                                                          e(f.outcome_label)) for c, a, b in routes)
    names = ' and '.join('through %s' % c['label'].lower() for c, _, _ in routes)
    return ('<p class="psum">%s: %s.</p><p class="note">Each step is separate evidence, mostly from different '
            'papers. Not one tested chain.</p><div class="chains">%s</div><a class="more" href="#">See on the '
            'graph →</a>' % (plural(len(routes), 'possible route', 'possible routes'), e(names), chains))


def card(data: Any, f: Finding, idx: int, open_: bool = False, state: str = '', title: Optional[str] = None,
         with_paths: bool = True) -> str:
    title = title or '%s → %s' % (f.subject_label, f.outcome_label.lower())
    head = ('<div class="card-head"><span class="idx">%02d</span>%s<span class="ctitle">%s</span>'
            '<span class="cert">%s <span class="muted">certainty</span></span><span class="aw">%s</span>%s'
            '<button class="btn %s" type="button">%s</button></div>'
            % (idx, chip(f.direction), e(title), bars(f.certainty), e(agree_word(f)), agreement(f), state,
               'Close ▴' if open_ else 'Details ▾'))
    if not open_:
        return '<article class="card %s">%s</article>' % (state, head)
    why_sum, why = checklist(f)
    panels = ['<section class="panel"><h4>Why “%s”? <button class="q" type="button">?</button></h4>'
              '<p class="psum">%s</p>%s<p class="rule">exact rule text ▸</p></section>'
              % (CERT_W[f.certainty], e(why_sum), why),
              '<section class="panel"><h4>Sources</h4>%s</section>' % sources_panel(f)]
    p = pathways(data, f) if with_paths else None
    if p:
        panels.append('<section class="panel"><h4>Possible pathways</h4>%s</section>' % p)
    return '<article class="card open %s">%s<div class="panels n%d">%s</div></article>' % (
        state, head, len(panels), ''.join(panels))


def gap_card(g: Gap, idx: Optional[int] = None) -> str:
    i = '<span class="idx">%02d</span>' % idx if idx else ''
    return ('<article class="gapcard">%s<span class="gchip">? Not studied</span><span class="ctitle">%s → %s</span>'
            '<span class="searched">Searched for: %s</span></article>'
            % (i, e(g.subject_label), e(g.outcome_label.lower()), e(g.searched_for)))


def section(num: int, label: str, body: str, aside: str = '') -> str:
    return ('<section class="sec"><div class="sec-label"><span class="num">%02d</span><h2>%s</h2>%s</div>'
            '<div class="sec-body">%s</div></section>' % (num, e(label), aside, body))


def limits(q: Any) -> str:
    items = ''.join('<li>%s</li>' % e(t) for t in q.limitations)
    return ('<ol class="limits">%s</ol><details class="built"><summary>How this answer was built ▸</summary>'
            '</details>' % items)


def page(title: str, kind: str, phone: bool, body: str, label: str) -> str:
    nav = ''.join('<a href="#"%s>%s</a>' % (' aria-current="page"' if n == label else '', n)
                  for n in ('Home', 'Q1 · Tree planting', 'Q1 graph', 'Q2 · Created marshes', 'Q3 · Grassland gaps',
                            'Method'))
    navblock = ('<button class="menu" type="button">Menu ☰</button>' if phone else '<nav>%s</nav>' % nav)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width, initial-scale=1"><title>%s</title><link rel="stylesheet" href="wf.css">'
            '</head><body class="%s"><div class="frame"><header class="top"><span class="brand">Restoration '
            'evidence</span>%s</header><main>%s</main><footer class="foot"><span>Data: Evidence Jam 2026 Lane 3 '
            'pack</span><span>Method</span><span>MIT licence</span></footer></div></body></html>'
            % (e(title), 'phone' if phone else 'desktop', navblock, body))


def hero(tag: str, question: str, short: str, facts: List[Tuple[str, str]]) -> str:
    fl = ''.join('<div><dt>%s</dt><dd>%s</dd></div>' % (e(k), e(v)) for k, v in facts)
    return ('<section class="hero"><p class="tag">%s</p><h1>%s</h1><div class="hero-side"><p class="short">%s</p>'
            '<dl class="facts">%s</dl></div></section>' % (e(tag), e(question), short, fl))


# ---------------------------------------------------------------- pages

def order(fs: List[Finding]) -> List[Finding]:
    return sorted(fs, key=lambda f: (-CERT_N[f.certainty], -f.studies, f.subject_label))


def q1(data: Any, phone: bool) -> str:
    q = data.questions['q1']
    outs = OrderedDict((f.outcome_id, f.outcome_label) for f in q.findings)
    papers_n = len({did for f in q.findings for did in f.raw.get('document_ids', [])})
    body = hero('Q1 · Tree planting', q.text,
                'Each finding below shows its direction, certainty and number of studies; open one to read the '
                'studies behind it.',
                [('Findings', str(len(q.findings))), ('Not studied', str(len(q.gaps))), ('Papers', str(papers_n)),
                 ('Combined-treatment claims', str(len(q.extra.get('interactions', []))))])
    body += section(1, 'Read this first', limits(q))
    # at a glance
    factors = OrderedDict()
    for f in order(list(q.findings)):
        factors.setdefault(f.subject_id, f.subject_label)
    cells = {(f.subject_id, f.outcome_id): f for f in q.findings}
    gaps = {(g.subject_id, g.outcome_id): g for g in q.gaps}
    if phone:
        rows = ''
        for sid, lbl in factors.items():
            parts = ''
            for oid, olbl in outs.items():
                f = cells.get((sid, oid))
                parts += ('<div class="gl-cell"><span class="muted">%s</span>%s</div>'
                          % (e(olbl.replace('Seedling ', '').capitalize()),
                             '%s <span>%s · %s</span>' % (chip(f.direction), CERT_W[f.certainty],
                                                          plural(f.studies, 'study', 'studies'))
                             if f else '<span class="gchip">? Not studied</span>'))
            rows += '<div class="gl-row"><b>%s</b>%s</div>' % (e(lbl), parts)
        glance = '<div class="glance-list">%s</div>' % rows
    else:
        th = ''.join('<th scope="col">%s</th>' % e(o) for o in outs.values())
        trs = ''
        for i, (sid, lbl) in enumerate(factors.items()):
            tds = ''
            for j, oid in enumerate(outs):
                f = cells.get((sid, oid))
                st = ' class="st-hover"' if (i, j) == (0, 1) else (' class="st-focus"' if (i, j) == (1, 1) else '')
                tds += ('<td%s><a href="#">%s <span>%s · %s</span></a></td>'
                        % (st, chip(f.direction), CERT_W[f.certainty], plural(f.studies, 'study', 'studies'))
                        if f else '<td class="gapcell"><span class="gchip">? Not studied</span></td>')
            trs += '<tr><th scope="row">%s</th>%s</tr>' % (e(lbl), tds)
        glance = ('<table class="glance"><thead><tr><th scope="col">Factor</th>%s</tr></thead><tbody>%s</tbody>'
                  '</table><p class="annot">Row 1 shows a hovered cell, row 2 a keyboard-focused cell.</p>' % (th, trs))
    body += section(2, 'At a glance', '<p class="lede">What each factor does to seedlings. Select a cell for the '
                    'details.</p>' + glance, '<button class="q" type="button">?</button>')
    num = 3
    for oid, olbl in outs.items():
        fs = order([f for f in q.findings if f.outcome_id == oid])
        cards = ''
        for i, f in enumerate(fs):
            cards += card(data, f, i + 1, open_=(i == 0 and oid == 'survival'),
                          state='st-hover' if (i == 1 and oid == 'survival') else '',
                          title='%s →' % f.subject_label)
        for g in q.gaps:
            if g.outcome_id == oid:
                cards += gap_card(g, len(fs) + 1)
        body += section(num, olbl, '<p class="lede">Strongest evidence first.</p>' + cards,
                        '<span class="count">%s</span>' % plural(len(fs), 'finding', 'findings'))
        num += 1
    inter = q.extra.get('interactions', [])
    rows = ''
    for i, it in enumerate(inter):
        qt = q.evidence[it['edge_id']]
        rows += ('<li class="ix"><span class="idx">%02d</span>%s<blockquote>%s</blockquote><p class="cite">%s · %s</p>'
                 '</li>' % (i + 1, chip(it['direction']), e(qt.quote[:200] + ('…' if len(qt.quote) > 200 else '')),
                            e(qt.title), qt.year or 'no year'))
    body += section(num, 'Combined treatments', '<p class="lede">Claims about two treatments together, or one '
                    'changing another\'s effect. Listed one by one, not pooled.</p><ul class="ixs">%s</ul>' % rows)
    body += '<a class="cta" href="#">See this as a causal graph →</a>'
    return page('2.3A Q1' + (' phone' if phone else ''), 'q1', phone, body, 'Q1 · Tree planting')


def q3(data: Any, phone: bool) -> str:
    q = data.questions['q3']
    s = q.extra['summary']
    grid = data.q3_grid
    body = hero('Q3 · Grassland gaps', q.text,
                '<b>%d of %d</b> combinations have been studied; <b>%d</b> of those by a single study. Most '
                'combinations have not been studied.' % (s['filled'], s['cells'], s['thin']),
                [('Studied', str(s['filled'])), ('Single study', str(s['thin'])), ('Not studied', str(s['empty'])),
                 ('Interventions × outcomes', '%d × %d' % (len(grid['rows']), len(grid['cols'])))])
    body += section(1, 'Read this first', limits(q))
    key = ('<dl class="key"><div><dt><span class="sw sw-empty">–</span></dt><dd>Not studied</dd></div>'
           '<div><dt><span class="sw sw-thin">1</span></dt><dd>thin · 1 study</dd></div>'
           '<div><dt><span class="sw sw-some">2</span></dt><dd>some · 2–3 studies</dd></div>'
           '<div><dt><span class="sw sw-dense">4</span></dt><dd>dense · 4+ studies</dd></div></dl>')
    ncols = 4 if phone else len(grid['cols'])
    th = ''.join('<th scope="col"><span>%s</span></th>' % e(l) for _, l in grid['cols'][:ncols])
    trs = ''
    nrows = 8 if phone else len(grid['rows'])
    for ri, (rid, rl) in enumerate(grid['rows'][:nrows]):
        tds = ''
        for ci, (cid, _) in enumerate(grid['cols'][:ncols]):
            it = grid['cells'][(rid, cid)]
            st = ' st-hover' if (ri, ci) == (0, 1) else (' st-focus' if (ri, ci) == (1, 0) else '')
            if isinstance(it, Gap):
                tds += '<td class="c-empty%s" aria-label="Not studied">–</td>' % st
            else:
                d = it.raw.get('density', '')
                tds += '<td class="c-%s%s"><a href="#">%d</a></td>' % (d, st, it.studies)
        trs += '<tr><th scope="row">%s</th>%s</tr>' % (e(rl), tds)
    more = ('<div class="scrollhint">Scroll for more outcomes →</div>' +
            ('<p class="annot">Phone frame shows the first 8 rows × 4 columns; the rest scroll inside the box. '
             'Names stay pinned.</p>' if phone else ''))
    gm = ('<div class="mapbox"><table class="gapmap"><thead><tr><th class="corner">Intervention ↓ · Outcome →</th>'
          '%s</tr></thead><tbody>%s</tbody></table></div>%s<p class="annot">Sticky header row and first column. '
          'Row 1 shows a hovered cell, row 2 a focused cell. Shading repeats the number; it is never the only cue.</p>'
          % (th, trs, more))
    body += section(2, 'Gap map', '<p class="lede">Each number is how many studies tested that pairing. Select a '
                    'cell to open its finding.</p>' + key + gm)
    by_id = {f.id: f for f in q.findings}
    dense = ''
    for i, fid in enumerate(s.get('densest', [])):
        f = by_id[fid]
        dense += ('<li><span class="idx">%02d</span><span class="ctitle">%s × %s</span>%s<span class="cert">%s'
                  '</span><span>%s</span></li>' % (i + 1, e(f.subject_label), e(f.outcome_label), chip(f.direction),
                                                   bars(f.certainty), plural(f.studies, 'study', 'studies')))
    body += section(3, 'Most studied', '<p class="lede">The ten most-studied combinations, in the pack\'s order. '
                    'Study counts measure research effort, not effect size.</p><ol class="dense">%s</ol>' % dense)
    groups = ''
    for gi, (rid, rl) in enumerate(grid['rows'][:6 if phone else 8]):
        items = [grid['cells'][(rid, cid)] for cid, _ in grid['cols']]
        fs = [x for x in items if not isinstance(x, Gap)]
        gs = [x for x in items if isinstance(x, Gap)]
        inner = ''
        if gi == 0:
            for i, f in enumerate(order(fs)[:3]):
                inner += card(data, f, i + 1, open_=(i == 0), title=f.outcome_label, with_paths=False)
            inner += '<p class="annot">…%d more studied outcomes</p>' % max(0, len(fs) - 3)
            inner += gap_card(gs[0]) if gs else ''
            inner += '<p class="annot">…%d more not studied</p>' % max(0, len(gs) - 1)
        groups += ('<details class="group"%s><summary><span class="gname">%s</span><span class="muted">%d studied · '
                   '%d not studied</span><span class="btn%s">%s</span></summary>%s</details>'
                   % (' open' if gi == 0 else '', e(rl), len(fs), len(gs), ' st-focus' if gi == 2 else '',
                      'Close ▴' if gi == 0 else 'Open ▾', inner))
    body += section(4, 'By intervention', '<p class="lede">Closed by default; selecting a map cell opens the right '
                    'one. Row 3 shows keyboard focus.</p>' + groups +
                    '<p class="annot">…%d more interventions</p>' % (len(grid['rows']) - (6 if phone else 8)))
    return page('2.6A Q3' + (' phone' if phone else ''), 'q3', phone, body, 'Q3 · Grassland gaps')


def card_sheet(data: Any, phone: bool) -> str:
    q = data.questions['q1']
    f = next(x for x in q.findings if x.id == 'q1:fertilization_at_planting:growth')
    f2 = next(x for x in q.findings if x.id == 'q1:site_preparation:survival')
    states = ''
    for st, lbl in (('', 'Normal'), ('st-hover', 'Hover'), ('st-selected', 'Selected (open)'), ('st-focus', 'Keyboard focus')):
        states += '<div class="state"><p class="tag">%s</p>%s</div>' % (lbl, card(data, f, 1, state=st))
    body = ('<section class="hero"><p class="tag">2.1A · Component sheet</p><h1>Finding card</h1><div class="hero-side">'
            '<p class="short">Closed card, its four states, the open card with Why / Sources / Pathways, and the '
            '“Not studied” card. Real data: Q1.</p></div></section>')
    body += section(1, 'Closed card · states', states)
    body += section(2, 'Open card', card(data, f2, 1, open_=True, state='st-selected'))
    body += section(3, 'Not studied', gap_card(q.gaps[0]) + '<p class="annot">Grey dashed outline, no bars, no '
                    'direction. Same height as a closed card. Never styled as a weak or negative result.</p>')
    btns = ''.join('<span class="btn %s">Details ▾</span>' % s for s in ('', 'st-hover', 'st-selected', 'st-focus'))
    links = ''.join('<a href="#" class="%s">All 7 papers, 38 quotes →</a>' % s for s in ('', 'st-hover', 'st-focus'))
    body += section(4, 'Buttons and links', '<div class="row">%s</div><div class="row">%s</div><p class="annot">'
                    'Normal · hover · selected · focus (3px outline, 2px offset).</p>' % (btns, links))
    return page('2.1A Finding card' + (' phone' if phone else ''), 'card', phone, body, '')


def main() -> None:
    data = load_all(os.path.join(ROOT, 'answers'))
    os.makedirs(OUT, exist_ok=True)
    pages = {'2.1A-finding-card': card_sheet, '2.3A-q1': q1, '2.6A-q3': q3}
    for name, fn in pages.items():
        for phone in (False, True):
            path = os.path.join(OUT, '%s%s.html' % (name, '-phone' if phone else ''))
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(fn(data, phone))
    with open(os.path.join(HERE, 'wf.css'), encoding='utf-8') as src, \
            open(os.path.join(OUT, 'wf.css'), 'w', encoding='utf-8') as dst:
        dst.write(src.read())
    index = ''.join('<li><a href="%s.html">%s</a> · <a href="%s-phone.html">phone</a></li>' % (n, n, n) for n in pages)
    with open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8') as fh:
        fh.write('<!doctype html><meta charset="utf-8"><title>Wireframes</title><link rel="stylesheet" href="wf.css">'
                 '<body class="desktop"><div class="frame"><main><h1>Wireframes</h1><ul>%s</ul></main></div>' % index)
    print('wrote %d wireframes to %s' % (len(pages) * 2, OUT))


if __name__ == '__main__':
    main()
