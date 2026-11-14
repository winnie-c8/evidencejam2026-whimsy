"""Draw the Q1 causal graph as inline SVG and insert it into q1-graph.html.

Layout is deterministic (rounded to 1 decimal) so builds are byte-identical.
Every edge is an <a> to its evidence panel; all labels are SVG <text>.
"""
from __future__ import annotations

import html
import os
from typing import Any, Dict, List, Tuple

from load import Graph, slug

VIEW_W = 1000
COL_X = (24, 404, 784)
NODE_W = 192
COMB_X, COMB_W = 228, 152
NODE_PAD, LINE_H, ROW_GAP, BAND_GAP = 12, 18, 28, 56
CHAR_W = 7.8          # px per char at 14 px
LBL_CHAR_W = 7.0      # px per char at 12 px bold
LBL_H = 20
TOP = 48
T_CANDIDATES = tuple([0.5] + [round(0.5 + s * k * 0.025, 3) for k in range(1, 17) for s in (-1, 1)])

SYM = {'increase': '↑', 'decrease': '↓', 'mixed': '⇅', 'no_effect': '–', 'unclear': '?'}
WORD = {'increase': 'increase', 'decrease': 'decrease', 'mixed': 'mixed', 'no_effect': 'no effect',
        'unclear': 'unclear'}
CERT = {'high': 'High', 'moderate': 'Moderate', 'low': 'Low', 'very_low': 'Very low'}
ARROW = {'increase': 'increase', 'decrease': 'decrease', 'mixed': 'mixed', 'no_effect': 'none',
         'unclear': 'none'}


def esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


def f1(v: float) -> str:
    s = '%.1f' % v
    return '0.0' if s == '-0.0' else s


def wrap(label: str, width: float) -> List[str]:
    max_chars = max(4, int((width - 2 * NODE_PAD) // CHAR_W))
    lines: List[str] = []
    cur = ''
    for w in label.split():
        cand = (cur + ' ' + w).strip()
        if len(cand) <= max_chars or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


class Box:
    def __init__(self, node: Dict[str, Any], x: float, w: float):
        self.node = node
        self.id = node['id']
        self.x = x
        self.w = w
        self.lines = wrap(node['label'], w)
        self.h = 2 * NODE_PAD + LINE_H * len(self.lines)
        self.y = 0.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def right(self) -> float:
        return self.x + self.w


def bezier(p0, p1, p2, p3, t: float) -> Tuple[float, float]:
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def curve(x1: float, y1: float, x2: float, y2: float):
    dx = max(60.0, (x2 - x1) * 0.45)
    pts = ((x1, y1), (x1 + dx, y1), (x2 - dx, y2), (x2, y2))
    d = 'M%s,%s C%s,%s %s,%s %s,%s' % tuple(f1(v) for p in pts for v in p)
    return d, pts


def layout(g: Graph) -> Dict[str, Box]:
    boxes: Dict[str, Box] = {}
    kind = lambda k: [n for n in g.nodes if n.get('kind') == k]  # noqa: E731

    # column 1: planting stock, band gap, site treatments
    y = 0.0
    stock = kind('planting_stock')
    treat = kind('site_treatment')
    band_y = None
    for i, n in enumerate(stock):
        b = Box(n, COL_X[0], NODE_W)
        b.y = y
        boxes[b.id] = b
        y += b.h + ROW_GAP
    if stock and treat:
        y += BAND_GAP - ROW_GAP
        band_y = y - BAND_GAP / 2
    for n in treat:
        b = Box(n, COL_X[0], NODE_W)
        b.y = y
        boxes[b.id] = b
        y += b.h + ROW_GAP
    col1_h = y - ROW_GAP
    if band_y is None:
        band_y = col1_h / 2
    for n in kind('combination'):
        b = Box(n, COMB_X, COMB_W)
        members = [boxes[m] for m in n.get('members') or [] if m in boxes]
        b.y = band_y - b.h / 2
        boxes[b.id] = b

    def sources_mean(node_id: str) -> float:
        ys = [boxes[e['source']].cy for e in g.edges
              if e.get('target') == node_id and e['source'] in boxes]
        return sum(ys) / len(ys) if ys else 0.0

    def stack(nodes: List[Dict[str, Any]], x: float) -> None:
        order = sorted(nodes, key=lambda n: (sources_mean(n['id']), n['id']))
        bs = [Box(n, x, NODE_W) for n in order]
        total = sum(b.h for b in bs) + ROW_GAP * max(0, len(bs) - 1)
        yy = col1_h / 2 - total / 2
        for b in bs:
            b.y = yy
            yy += b.h + ROW_GAP
            boxes[b.id] = b

    stack(kind('condition'), COL_X[1])
    stack(kind('outcome'), COL_X[2])
    # any node kind we don't know goes in the middle column after the rest
    for n in g.nodes:
        if n['id'] not in boxes:
            b = Box(n, COL_X[1], NODE_W)
            b.y = max([bb.y + bb.h for bb in boxes.values() if bb.x == COL_X[1]] + [0]) + ROW_GAP
            boxes[b.id] = b
    top = min(b.y for b in boxes.values())
    for b in boxes.values():
        b.y += TOP - top
    return boxes


def ports(items: List[Tuple[str, float]], box: Box) -> Dict[str, float]:
    """Spread attachment points over the middle 70 % of a side, ordered by the other end's y."""
    items = sorted(items, key=lambda t: (t[1], t[0]))
    n = len(items)
    out = {}
    for i, (key, _) in enumerate(items):
        if n == 1:
            out[key] = box.cy
        else:
            out[key] = box.y + 0.15 * box.h + i * (0.7 * box.h / (n - 1))
    return out


def build_svg(g: Graph, edge_index: Dict[str, Any]) -> str:
    boxes = layout(g)
    effects = [e for e in g.edges if e.get('kind') == 'effect']
    mods = [e for e in g.edges if e.get('kind') == 'moderation']
    links = [('e', e) for e in effects] + [('g', gp) for gp in g.gaps]

    # ports: outgoing on right side (effects, gaps, moderations), incoming on left side
    out_items: Dict[str, List[Tuple[str, float]]] = {}
    in_items: Dict[str, List[Tuple[str, float]]] = {}
    for kind, e in links:
        out_items.setdefault(e['source'], []).append((e['id'], boxes[e['target']].cy))
        in_items.setdefault(e['target'], []).append((e['id'], boxes[e['source']].cy))
    for m in mods:
        t = g.edge(m['target_edge'])
        ty = (boxes[t['source']].cy + boxes[t['target']].cy) / 2
        out_items.setdefault(m['source'], []).append((m['id'], ty))
    out_y: Dict[str, float] = {}
    in_y: Dict[str, float] = {}
    for nid, items in out_items.items():
        out_y.update(ports(items, boxes[nid]))
    for nid, items in in_items.items():
        in_y.update(ports(items, boxes[nid]))

    geo: Dict[str, Any] = {}
    for kind, e in links:
        s, t = boxes[e['source']], boxes[e['target']]
        d, pts = curve(s.right, out_y[e['id']], t.x, in_y[e['id']])
        geo[e['id']] = (d, pts)
    for m in mods:
        tp = geo[m['target_edge']][1]
        mx = (tp[0][0] + 3 * tp[1][0] + 3 * tp[2][0] + tp[3][0]) / 8
        my = (tp[0][1] + 3 * tp[1][1] + 3 * tp[2][1] + tp[3][1]) / 8
        s = boxes[m['source']]
        d, pts = curve(s.right, out_y[m['id']], mx, my)
        geo[m['id']] = (d, pts)

    # labels
    labels: Dict[str, Dict[str, Any]] = {}
    for kind, e in links + [('m', m) for m in mods]:
        pts = geo[e['id']][1]
        mx, my = bezier(*pts, 0.5)
        if kind == 'g':
            text_len = len('no evidence')
            lines = 1
        else:
            text_len = len('%s %s · %d' % (SYM[e['direction']], CERT[e['certainty']], e['studies']))
            lines = 1
            if kind == 'm':
                text_len = max(text_len, len('changes this effect'))
                lines = 2
        w = text_len * LBL_CHAR_W + 12
        h = LBL_H + (lines - 1) * 14
        labels[e['id']] = {'x': mx - w / 2, 'y': my - h / 2, 'w': w, 'h': h, 'pts': pts,
                           'span': pts[3][0] - pts[0][0]}

    def hits(a: Dict[str, Any], rects: List[Tuple[float, float, float, float]]) -> bool:
        return any(a['x'] < x + w and x < a['x'] + a['w'] and a['y'] < y + h and y < a['y'] + a['h']
                   for x, y, w, h in rects)

    node_rects = [(b.x - 2, b.y - 2, b.w + 4, b.h + 4) for b in boxes.values()]
    # Short edges first: they have the fewest clear spots along their curve.
    order = sorted(labels, key=lambda k: (labels[k]['span'], labels[k]['y'], k))
    placed: List[str] = []
    for k in order:
        a = labels[k]
        # Prefer the midpoint; otherwise slide along the same curve to the first spot
        # clear of nodes and other labels, so every label stays on its own line.
        taken = [(labels[p]['x'], labels[p]['y'], labels[p]['w'], labels[p]['h']) for p in placed]
        cands = []
        for t in T_CANDIDATES:
            cx, cy = bezier(*a['pts'], t)
            cands.append(dict(a, x=cx - a['w'] / 2, y=cy - a['h'] / 2))
        best = next((c for c in cands if not hits(c, node_rects) and not hits(c, taken)), None) or \
            next((c for c in cands if not hits(c, node_rects)), None)
        if best is not None:
            a['x'], a['y'] = best['x'], best['y']
        # Fallback (spec rule): push the lower label down by the overlap + 4 px.
        moved = True
        while moved:
            moved = False
            for p in placed:
                b = labels[p]
                if a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w'] and \
                        a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h']:
                    a['y'] += (b['y'] + b['h']) - a['y'] + 4
                    moved = True
        placed.append(k)

    bottom = max([b.y + b.h for b in boxes.values()] + [l['y'] + l['h'] for l in labels.values()])
    height = bottom + 24

    out: List[str] = []
    n_eff, n_mod = len(effects), len(mods)
    out.append('<svg viewBox="0 0 %d %s" width="100%%" role="group" '
               'aria-labelledby="g-title g-desc">' % (VIEW_W, f1(height)))
    out.append('<title id="g-title">Tree planting: what acts on seedling survival and growth</title>')
    out.append('<desc id="g-desc">%d boxes and %d effect %s, %d moderation %s and %d %s marked as not '
               'studied. Planting-stock traits and site treatments are on the left, the conditions they '
               'change in the middle, seedling survival and growth on the right. Each arrow links to its '
               'evidence.</desc>'
               % (len(g.nodes), n_eff, 'arrow' if n_eff == 1 else 'arrows', n_mod,
                  'arrow' if n_mod == 1 else 'arrows', len(g.gaps), 'pairing' if len(g.gaps) == 1 else 'pairings'))
    out.append('<defs>')
    for a in ('increase', 'decrease', 'mixed', 'none'):
        out.append('<marker id="ah-%s" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="10" '
                   'markerHeight="10" markerUnits="userSpaceOnUse" orient="auto">'
                   '<path d="M0,0 L10,5 L0,10 z" class="ah-%s"/></marker>' % (a, a))
    out.append('</defs>')

    # column headings
    heads = ('Planting stock & site treatments', 'Conditions they change', 'Seedling outcomes')
    for x, t in zip(COL_X, heads):
        out.append('<text class="colhead" x="%s" y="24">%s</text>' % (f1(x), esc(t)))

    # combination member lines (undirected)
    for b in boxes.values():
        for m in b.node.get('members') or []:
            mb = boxes.get(m)
            if mb is None:
                continue
            out.append('<line class="member" x1="%s" y1="%s" x2="%s" y2="%s"/>'
                       % (f1(mb.right), f1(mb.cy), f1(b.x), f1(b.cy)))

    # nodes
    for b in boxes.values():
        out.append('<g class="node k-%s" id="n-%s"><rect x="%s" y="%s" width="%s" height="%s" rx="6"/>'
                   % (esc(b.node.get('kind', '')), esc(slug(b.id)), f1(b.x), f1(b.y), f1(b.w), f1(b.h)))
        out.append('<text>')
        for i, line in enumerate(b.lines):
            out.append('<tspan x="%s" y="%s">%s</tspan>'
                       % (f1(b.x + NODE_PAD), f1(b.y + NODE_PAD + 14 + i * LINE_H), esc(line)))
        out.append('</text></g>')

    def label_svg(key: str, parts: List[str], cls: str = 'lbl') -> str:
        l = labels[key]
        texts = ''.join('<text x="%s" y="%s" text-anchor="middle">%s</text>'
                        % (f1(l['x'] + l['w'] / 2), f1(l['y'] + 14 + i * 14), p) for i, p in enumerate(parts))
        return ('<g class="%s"><rect x="%s" y="%s" width="%s" height="%s" rx="4"/>%s</g>'
                % (cls, f1(l['x']), f1(l['y']), f1(l['w']), f1(l['h']), texts))

    def name(nid: str) -> str:
        return g.node(nid)['label']

    # gaps
    for gp in g.gaps:
        gs = slug(gp['id'])
        d = geo[gp['id']][0]
        out.append('<a href="#e-%s" class="gap-link" id="gapedge-%s" aria-label="%s to %s: no evidence, '
                   'not studied in this body of research. Opens details.">'
                   % (gs, gs, esc(name(gp['source'])), esc(name(gp['target']))))
        out.append('<path class="hit" d="%s"/><path class="vis" d="%s"/>' % (d, d))
        out.append(label_svg(gp['id'], ['no evidence']))
        out.append('</a>')

    # effect and moderation edges
    for e in effects + mods:
        es = slug(e['id'])
        d = geo[e['id']][0]
        n = e['studies']
        studies = '%d %s' % (n, 'study' if n == 1 else 'studies')
        if e.get('kind') == 'moderation':
            t = g.edge(e['target_edge'])
            aria = '%s changes the effect of %s on %s: %s, %s certainty, %s. Opens evidence.' % (
                name(e['source']), name(t['source']), name(t['target']), WORD[e['direction']],
                CERT[e['certainty']].lower(), studies)
            cls = 'edge mod d-%s c-%s' % (e['direction'], e['certainty'])
        else:
            aria = '%s to %s: %s, %s certainty, %s. Opens evidence.' % (
                name(e['source']), name(e['target']), WORD[e['direction']], CERT[e['certainty']].lower(), studies)
            cls = 'edge d-%s c-%s' % (e['direction'], e['certainty'])
        out.append('<a href="#e-%s" class="%s" id="edge-%s" aria-label="%s">' % (es, cls, es, esc(aria)))
        out.append('<path class="hit" d="%s"/>' % d)
        if e.get('kind') == 'moderation':
            out.append('<path class="vis" d="%s"/>' % d)
            end = geo[e['id']][1][3]
            out.append('<circle class="ring" cx="%s" cy="%s" r="5"/>' % (f1(end[0]), f1(end[1])))
        else:
            out.append('<path class="vis c-%s" d="%s" marker-end="url(#ah-%s)"/>'
                       % (e['certainty'], d, ARROW[e['direction']]))
        main = ('<tspan aria-hidden="true">%s</tspan> <tspan data-check="q1graph/%s/certainty">%s</tspan> · '
                '<tspan data-check="q1graph/%s/studies">%d</tspan>'
                % (SYM[e['direction']], es, CERT[e['certainty']], es, n))
        parts = [main]
        if e.get('kind') == 'moderation':
            parts.append('changes this effect')
        out.append(label_svg(e['id'], parts))
        out.append('</a>')

    out.append('</svg>')
    return '\n'.join(out)


def write_graph(graph: Graph, edge_index: Dict[str, Any], out: str) -> None:
    path = os.path.join(out, 'q1-graph.html')
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    if '<!--GRAPH-->' not in text:
        raise RuntimeError('q1-graph.html has no <!--GRAPH--> placeholder')
    text = text.replace('<!--GRAPH-->', build_svg(graph, edge_index), 1)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)
