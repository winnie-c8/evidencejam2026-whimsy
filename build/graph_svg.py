"""Draw a question's causal graph as inline SVG and insert it into its <qid>-graph.html.

Layout (deterministic, rounded to 1 decimal, so builds are byte-identical). FLOW picks the
direction; everything below the layout functions works for both.

  FLOW = 'down'  (default) rows, top to bottom:
      row 0: planting stock + site treatments
      row 1: the conditions they change, and any combination box (a hexagon) under its members
      row 2: seedling outcomes
      The left-to-right order in each row is computed for the fewest line crossings
      (order_rows), not fixed by hand.
  FLOW = 'right' columns, left to right, in the same order (combination under its members
      in column 0).

Every arrow ends in a straight "tail" that holds its badge (direction symbol + studies), so
badges sit in one row just above the arrowheads and never pile up: top-down, each arrow into
a box gets a slot as wide as its badge. A mixed arrow's badge shows how many studies went up
and down, a zero left out ("⇅ ↑5 ↓1", "⇅ ↑1", "⇅"). Top-down, an arrow that skips the middle
row runs down an outer channel just left or right of the middle boxes.
One meaning per visual channel: colour = direction, thickness = number of studies, dash
pattern = certainty. A moderation arrow ends in a small ring on the arrow it changes.

static/graph.js re-runs the same routing (route_all below) when a box or arrow is dragged;
keep the two in step. Every edge is an <a> to its evidence panel; all labels are SVG <text>.
"""
from __future__ import annotations

import html
import itertools
import os
from typing import Any, Dict, List, Optional, Tuple

from load import Graph, slug

FLOW = 'down'          # 'down' or 'right'

# shared sizes
NODE_PAD, LINE_H = 12, 18
CHAR_W = 7.8           # px per char at 14 px
GAP_CHAR_W = 6.8       # px per char of the small italic "not studied" tag
LBL_H = 23             # every badge is one small line: "↑ 7" or "⇅ ↑4 ↓1"
BIG_LBL_H = LBL_H
LBL_PAD = 6            # badge padding, left and right
SYM_W = 15             # width of the direction symbol at 17 px
NUM_W = 9.5            # width of one digit at 15 px bold
ARR_W = 10             # width of the ↑ / ↓ before a split count at 14 px
SP_W = 4               # a space
VTAIL = 20             # tail of an arrow entering a box from the side across the flow
HEAD_GAP = 14          # space between a badge and the box, for the arrowhead
PORT_PAD = 8           # free space between two badges side by side above a box
MOD_INSET = 24         # a moderation arrow lands this far into the lane of the arrow it changes
TIER = 0               # badges sit in one row (kept for graph.js, which reads data-tier)

# left to right: columns x, width
X0, W0 = 34, 200
GUTTER = 150           # free space between columns where arrows curve
STRIP_R = 128          # straight tail before a box's left side; holds the arrow's label
X1, W1 = X0 + W0 + GUTTER + STRIP_R, 190
X2, W2 = X1 + W1 + GUTTER + STRIP_R, 170
VIEW_W_R = X2 + W2 + 24
COMB_INDENT = 24       # a combination box is indented so its member bracket fits
PORT_H = 36            # vertical room per labelled incoming arrow
OUT_GAP = 12           # vertical room per outgoing arrow
TOP = 56

# top to bottom
BOX_W = 150            # narrowest box
PORT_W = 54            # (left to right only) vertical room per labelled incoming arrow
OUT_W = 14             # horizontal room per outgoing arrow
IN_MARGIN = 10         # free space at each end of a box's row of incoming badges
STRIP_D = HEAD_GAP + LBL_H + 26   # straight tail above a box; holds one row of badges
GUTTER_D = 150         # free space between rows where arrows curve
LANE_GAP = 34          # outer channels: distance from the middle boxes
LANE_SP = 12           # outer channels: distance between neighbouring lanes
MID_GAP = 40           # space between middle boxes
COMB_TIP = 14          # a combination box is a hexagon; its pointed ends are this deep
LEFT = 104             # margin for the row headings
ROW_GAP_X = 30

STRIP = STRIP_R if FLOW == 'right' else STRIP_D

SYM = {'increase': '↑', 'decrease': '↓', 'mixed': '⇅', 'no_effect': '–', 'unclear': '?'}
WORD = {'increase': 'increase', 'decrease': 'decrease', 'mixed': 'mixed', 'no_effect': 'no effect',
        'unclear': 'unclear'}
CERT = {'high': 'High', 'moderate': 'Moderate', 'low': 'Low', 'very_low': 'Very low'}
ARROW = {'increase': 'increase', 'decrease': 'decrease', 'mixed': 'mixed', 'no_effect': 'none',
         'unclear': 'none'}

Pt = Tuple[float, float]


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
    def __init__(self, node: Dict[str, Any], col: int, x: float, w: float):
        self.node = node
        self.id = node['id']
        self.col = col
        self.x = x
        self.w = w
        # a combination box is a hexagon, so its text needs room clear of the pointed ends
        inset = 2 * COMB_TIP if node.get('kind') == 'combination' else 0
        self.lines = wrap(node['label'], w - inset)
        self.h = 2 * NODE_PAD + LINE_H * len(self.lines)
        self.y = 0.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


def bezier(p0: Pt, p1: Pt, p2: Pt, p3: Pt, t: float) -> Pt:
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


# ------------------------------------------------------------------ layout

def links_of(g: Graph) -> List[Tuple[str, Dict[str, Any]]]:
    """Effect edges and gaps: everything drawn as an arrow from one box to another."""
    return [('e', e) for e in g.edges if e.get('kind') == 'effect'] + [('g', gp) for gp in g.gaps]


def split_counts(e: Dict[str, Any]) -> Tuple[int, int]:
    """Studies that found an increase and a decrease (the pack's study_directions; 0 if absent)."""
    sd = e.get('study_directions') or {}
    return int(sd.get('increase', 0)), int(sd.get('decrease', 0))


GAP_TAG = 'not studied'


def weight_class(studies: int) -> int:
    """Line thickness = number of studies, in four steps (1, 2-3, 4-6, 7+), explained in the legend."""
    return 1 if studies <= 1 else 2 if studies <= 3 else 3 if studies <= 6 else 4


def label_size(kind: str, e: Dict[str, Any]) -> Tuple[float, float]:
    """A badge shows the direction symbol and the study count ("↑ 7"); a mixed arrow shows how many
    studies went up and down instead, leaving out a zero ("⇅ ↑4 ↓1", "⇅ ↑1", "⇅").
    Certainty is the line's dash pattern, the number of studies also its thickness."""
    if kind == 'g':
        return len(GAP_TAG) * GAP_CHAR_W + 2 * LBL_PAD, LBL_H
    w = 2 * LBL_PAD + SYM_W
    if kind == 'e' and e['direction'] == 'mixed':
        for n in split_counts(e):
            if n:
                w += SP_W + ARR_W + NUM_W * len(str(n))
    else:
        w += SP_W + NUM_W * len(str(e['studies']))
    return w, LBL_H


def pack(keys: List[str], desired: Dict[str, float], size: Dict[str, float],
         pairs: List[Tuple[str, str]], box_gap: float = 34,
         weight: Optional[Dict[str, float]] = None, fixed: bool = False) -> Dict[str, float]:
    """Place items along one line as near their desired centre as the gaps allow; return starts.

    With fixed=True the items keep the order of `keys` (already chosen for fewest crossings);
    otherwise the order follows the desired centre, and each same-row pair (an arrow from one
    middle box to another) is kept adjacent. Positions minimise the weighted squared distance
    from the desired centres (pool-adjacent-violators), so a heavy item (a combination box
    under its members) moves least.
    """
    order = list(keys) if fixed else sorted(keys, key=lambda k: (desired[k], k))
    for a, b in ([] if fixed else pairs):
        if a in order and b in order:
            i = min(order.index(a), order.index(b))
            block = sorted([a, b], key=lambda k: (desired[k], k))
            order = [k for k in order if k not in (a, b)]
            order[i:i] = block
    pair_set = {frozenset(p) for p in pairs}

    def gap(a: str, b: str) -> float:
        da, db = a.startswith('lane:'), b.startswith('lane:')
        if da and db:
            return 12
        if da or db:
            return 18
        return 64 if frozenset((a, b)) in pair_set else box_gap

    # offsets: where each item would start if all were packed tight from 0
    offs: List[float] = []
    o = 0.0
    for i, k in enumerate(order):
        if i:
            o += size[order[i - 1]] + gap(order[i - 1], k)
        offs.append(o)
    # z_i = start_i - off_i must not decrease; fit it to the targets (weighted isotonic regression)
    blocks: List[List[float]] = []   # [value, weight, count]
    for i, k in enumerate(order):
        blocks.append([desired[k] - size[k] / 2 - offs[i], (weight or {}).get(k, 1.0), 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            v2, w2, c2 = blocks.pop()
            v1, w1, c1 = blocks.pop()
            blocks.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, c1 + c2])
    z: List[float] = []
    for v, _, c in blocks:
        z += [v] * int(c)
    return {k: z[i] + offs[i] for i, k in enumerate(order)}


def first_row_order(g: Graph) -> List[str]:
    """Planting stock, then site treatments; a combination's members sit together (last of the
    stock, first of the treatments)."""
    combos = [n for n in g.nodes if n.get('kind') == 'combination']
    members = {m for c in combos for m in c.get('members') or []}
    stock = sorted([n for n in g.nodes if n.get('kind') == 'planting_stock'], key=lambda n: n['id'] in members)
    treat = sorted([n for n in g.nodes if n.get('kind') == 'site_treatment'], key=lambda n: n['id'] not in members)
    return [n['id'] for n in stock + treat]


def mean(vals: List[float], default: float) -> float:
    return sum(vals) / len(vals) if vals else default


def layout_right(g: Graph) -> Dict[str, Any]:
    links = links_of(g)
    mods = [e for e in g.edges if e.get('kind') == 'moderation']
    col = {n['id']: {'planting_stock': 0, 'site_treatment': 0, 'combination': 0, 'condition': 1,
                     'outcome': 2}.get(n.get('kind', ''), 1) for n in g.nodes}
    boxes: Dict[str, Box] = {}
    for n in g.nodes:
        c = col[n['id']]
        if n.get('kind') == 'combination':
            boxes[n['id']] = Box(n, 0, X0 + COMB_INDENT, W0 - COMB_INDENT)
        else:
            boxes[n['id']] = Box(n, c, (X0, X1, X2)[c], (W0, W1, W2)[c])
    n_in: Dict[str, int] = {}
    n_out: Dict[str, int] = {}
    for _, e in links:
        if col[e['source']] != col[e['target']]:
            n_in[e['target']] = n_in.get(e['target'], 0) + 1
            n_out[e['source']] = n_out.get(e['source'], 0) + 1
    for m in mods:
        n_out[m['source']] = n_out.get(m['source'], 0) + 1
    for b in boxes.values():
        b.h = max(b.h, PORT_H * (n_in.get(b.id, 0) + 1), OUT_GAP * (n_out.get(b.id, 0) + 1))

    order = first_row_order(g)
    for c in [n for n in g.nodes if n.get('kind') == 'combination']:
        idx = [order.index(m) for m in c.get('members') or [] if m in order]
        order.insert(max(idx) + 1 if idx else len(order), c['id'])
    y = 0.0
    for k, nid in enumerate(order):
        if k and boxes[order[k - 1]].node.get('kind') == 'planting_stock' and \
                boxes[nid].node.get('kind') != 'planting_stock':
            y += 12
        boxes[nid].y = y
        y += boxes[nid].h + 18

    by_col = {c: [b.id for b in boxes.values() if b.col == c] for c in (0, 1, 2)}
    long_links = [e for _, e in links if col[e['source']] == 0 and col[e['target']] == 2]
    pairs = [(e['source'], e['target']) for _, e in links if col[e['source']] == col[e['target']] == 1]
    lane_y: Dict[str, float] = {}

    def neighbours(nid: str, cols: Tuple[int, ...]) -> List[float]:
        return [boxes[b].cy for _, e in links for a, b in ((e['source'], e['target']), (e['target'], e['source']))
                if a == nid and col[b] in cols]

    col0_mid = mean([boxes[k].cy for k in by_col[0]], 0.0)
    for k in by_col[1]:
        boxes[k].y = mean(neighbours(k, (0,)), col0_mid) - boxes[k].h / 2

    def place_outcomes() -> None:
        desired = {k: mean([lane_y.get(e['id'], boxes[e['source']].cy) for _, e in links if e['target'] == k],
                           col0_mid) for k in by_col[2]}
        for k, t in pack(by_col[2], desired, {k: boxes[k].h for k in by_col[2]}, []).items():
            boxes[k].y = t

    def place_middle() -> None:
        desired: Dict[str, float] = {}
        size: Dict[str, float] = {}
        for k in by_col[1]:
            desired[k] = mean(neighbours(k, (0, 2)), col0_mid)
            size[k] = boxes[k].h
        for e in long_links:
            desired['lane:' + e['id']] = (boxes[e['source']].cy + boxes[e['target']].cy) / 2
            size['lane:' + e['id']] = 0.0
        for k, t in pack(list(desired), desired, size, pairs).items():
            if k.startswith('lane:'):
                lane_y[k[5:]] = t
            else:
                boxes[k].y = t

    place_outcomes()
    for _ in range(4):
        place_middle()
        place_outcomes()
    top = min([b.y for b in boxes.values()] + list(lane_y.values()))
    for b in boxes.values():
        b.y += TOP - top
    lanes = {eid: (float(X1 - STRIP_R), float(X1 + W1), ly + TOP - top) for eid, ly in lane_y.items()}
    heads = [(X0, 28, ['Planting stock & site treatments']), (X1, 28, ['Conditions they change']),
             (X2, 28, ['Seedling outcomes'])]
    return {'boxes': boxes, 'lanes': lanes, 'heads': heads, 'width': VIEW_W_R}


def rows_of(g: Graph) -> Dict[str, int]:
    """Top-down row of each box: 0 things you do, 1 conditions (and combinations), 2 outcomes."""
    return {n['id']: {'planting_stock': 0, 'site_treatment': 0, 'combination': 1, 'condition': 1,
                      'outcome': 2}.get(n.get('kind', ''), 1) for n in g.nodes}


def order_rows(g: Graph) -> Tuple[Dict[int, List[str]], Dict[str, str]]:
    """The left-to-right order of the boxes in each row, chosen for the fewest line crossings,
    and the outer channel ('l' or 'r') each arrow that skips the middle row runs down.

    Crossings are counted on the order alone (two arrows between the same pair of rows cross
    when their ends are in opposite orders). An arrow that skips the middle row is counted as
    passing just left or right of the middle row, whichever crosses less. A combination box
    counts as joined to its members, so it ends up under them, and its members side by side.
    The search: every order of the small rows (up to 6 boxes) for the current top row, then
    every swap or move in the top row; repeated until nothing improves. Ties keep the
    current order, so the result is deterministic.
    """
    row = rows_of(g)
    links = links_of(g)
    start = first_row_order(g)
    rows = {0: start + [n['id'] for n in g.nodes if row[n['id']] == 0 and n['id'] not in start],
            1: [n['id'] for n in g.nodes if row[n['id']] == 1],
            2: [n['id'] for n in g.nodes if row[n['id']] == 2]}
    e01 = [(e['source'], e['target']) for _, e in links if row[e['source']] == 0 and row[e['target']] == 1]
    e01 += [(e['target'], e['source']) for _, e in links if row[e['source']] == 1 and row[e['target']] == 0]
    e12 = [(e['source'], e['target']) for _, e in links if row[e['source']] == 1 and row[e['target']] == 2]
    e02 = [(e['id'], e['source'], e['target']) for _, e in links if row[e['source']] == 0 and row[e['target']] == 2]
    e11 = [(e['source'], e['target']) for _, e in links if row[e['source']] == row[e['target']] == 1]
    combos = [(n['id'], [m for m in n.get('members') or [] if row.get(m) == 0])
              for n in g.nodes if n.get('kind') == 'combination' and row[n['id']] == 1]
    for c, ms in combos:
        e01 += [(m, c) for m in ms]

    def crosses(segs: List[Tuple[float, float]], a: float, b: float) -> int:
        return sum(1 for x, y in segs if (x - a) * (y - b) < 0)

    def evaluate(o0: List[str], o1: List[str], o2: List[str]) -> Tuple[float, Dict[str, str]]:
        p0 = {k: i for i, k in enumerate(o0)}
        p1 = {k: i for i, k in enumerate(o1)}
        p2 = {k: i for i, k in enumerate(o2)}
        lo, hi = -1, len(o1)
        s01 = [(p0[a], p1[b]) for a, b in e01]
        s12 = [(p1[a], p2[b]) for a, b in e12]
        chan: Dict[str, str] = {}
        longs: Dict[str, List[Tuple[float, float]]] = {'l': [], 'r': []}
        for eid, a, b in e02:
            cl = crosses(s01, p0[a], lo) + crosses(s12, lo, p2[b])
            cr = crosses(s01, p0[a], hi) + crosses(s12, hi, p2[b])
            near_left = p0[a] / max(1, len(o0) - 1) + p2[b] / max(1, len(o2) - 1) <= 1
            chan[eid] = 'l' if (cl, not near_left) <= (cr, near_left) else 'r'
            longs[chan[eid]].append((p0[a], p2[b]))
        all01 = s01 + [(x, lo) for x, _ in longs['l']] + [(x, hi) for x, _ in longs['r']]
        all12 = s12 + [(lo, y) for _, y in longs['l']] + [(hi, y) for _, y in longs['r']]
        cost = 0.0
        for segs in (all01, all12):
            for i in range(len(segs)):
                for j in range(i + 1, len(segs)):
                    if (segs[i][0] - segs[j][0]) * (segs[i][1] - segs[j][1]) < 0:
                        cost += 1
        for side in 'lr':   # two arrows in one channel cross if they enter and leave in opposite orders
            ls = longs[side]
            for i in range(len(ls)):
                for j in range(i + 1, len(ls)):
                    if (ls[i][0] - ls[j][0]) * (ls[i][1] - ls[j][1]) < 0:
                        cost += 1
        for a, b in e11:    # an arrow inside the middle row: its two boxes side by side
            cost += 2 * (abs(p1[a] - p1[b]) - 1)
        for c, ms in combos:   # a combination's members side by side
            if len(ms) > 1:
                cost += 2 * (max(p0[m] for m in ms) - min(p0[m] for m in ms) - (len(ms) - 1))
        # tie-break: shorter, more vertical arrows
        n0, n1 = max(1, len(o0) - 1), max(1, len(o1) - 1)
        cost += 0.001 * sum(abs(p0[a] / n0 - p1[b] / n1) for a, b in e01)
        return cost, chan

    def small_orders(r: int) -> List[List[str]]:
        return [list(p) for p in itertools.permutations(rows[r])] if len(rows[r]) <= 6 else [rows[r]]

    best, chan = evaluate(rows[0], rows[1], rows[2])
    for _ in range(20):
        improved = False
        for o1 in small_orders(1):
            for o2 in small_orders(2):
                c, ch = evaluate(rows[0], o1, o2)
                if c < best - 1e-9:
                    best, chan, rows[1], rows[2], improved = c, ch, o1, o2, True
        o0 = rows[0]
        cands = []
        for i in range(len(o0)):
            for j in range(len(o0)):
                if i != j:
                    moved = o0[:i] + o0[i + 1:]
                    moved.insert(j, o0[i])
                    cands.append(moved)
                    if i < j:
                        swapped = list(o0)
                        swapped[i], swapped[j] = swapped[j], swapped[i]
                        cands.append(swapped)
        for o in cands:
            c, ch = evaluate(o, rows[1], rows[2])
            if c < best - 1e-9:
                best, chan, rows[0], improved = c, ch, o, True
        if not improved:
            break
    return rows, chan


def layout_down(g: Graph) -> Dict[str, Any]:
    links = links_of(g)
    mods = [e for e in g.edges if e.get('kind') == 'moderation']
    row = rows_of(g)
    orders, channel = order_rows(g)

    # Boxes are wide enough for one badge per arrow coming in from above, side by side, and
    # room for the outgoing arrows.
    top_in: Dict[str, float] = {}
    n_out: Dict[str, int] = {}
    for kind, e in links:
        if row[e['source']] < row[e['target']]:
            top_in[e['target']] = top_in.get(e['target'], 0.0) + label_size(kind, e)[0] + PORT_PAD
        if row[e['source']] != row[e['target']]:
            n_out[e['source']] = n_out.get(e['source'], 0) + 1
    for m in mods:
        n_out[m['source']] = n_out.get(m['source'], 0) + 1
    boxes: Dict[str, Box] = {}
    for n in g.nodes:
        w = max(BOX_W, top_in.get(n['id'], 0.0) + 2 * IN_MARGIN, OUT_W * (n_out.get(n['id'], 0) + 1))
        if n.get('kind') == 'combination':
            w += 2 * COMB_TIP
        b = Box(n, row[n['id']], 0.0, w)
        b.h = max(b.h, 44)
        boxes[n['id']] = b

    by_row = orders
    row_h = {r: max([boxes[k].h for k in by_row[r]] or [44]) for r in (0, 1, 2)}
    row_top = {0: 0.0}
    row_top[1] = row_top[0] + row_h[0] + GUTTER_D + STRIP_D
    row_top[2] = row_top[1] + row_h[1] + GUTTER_D + STRIP_D
    for b in boxes.values():
        b.y = row_top[b.col]

    # top row in the chosen order
    x = 0.0
    for nid in by_row[0]:
        boxes[nid].x = x
        x += boxes[nid].w + ROW_GAP_X
    row0_mid = mean([boxes[k].cx for k in by_row[0]], 0.0)

    long_links = [e for _, e in links if row[e['source']] == 0 and row[e['target']] == 2]
    pairs = [(e['source'], e['target']) for _, e in links if row[e['source']] == row[e['target']] == 1]
    lane_x: Dict[str, float] = {}

    def neighbours(nid: str, rows: Tuple[int, ...]) -> List[float]:
        return [boxes[b].cx for _, e in links for a, b in ((e['source'], e['target']), (e['target'], e['source']))
                if a == nid and row[b] in rows]

    def desired_middle(k: str) -> float:
        n = boxes[k].node
        if n.get('kind') == 'combination':  # right under its members
            return mean([boxes[m].cx for m in n.get('members') or [] if m in boxes], row0_mid)
        return mean(neighbours(k, (0, 2)), row0_mid)

    combos = [k for k in by_row[1] if boxes[k].node.get('kind') == 'combination']

    def place_middle() -> None:
        # the middle boxes side by side in the chosen order, close together; an arrow between
        # two of them gets room for its badge
        desired = {k: desired_middle(k) for k in by_row[1]}
        size = {k: boxes[k].w for k in by_row[1]}
        for k, s in pack(by_row[1], desired, size, pairs, MID_GAP, weight={c: 4.0 for c in combos},
                         fixed=True).items():
            boxes[k].x = s
        # Arrows that skip the middle row run down a channel just outside it, on the side the
        # ordering picked. In a channel the lanes go in the order of where the arrows end, so
        # they fan out to the outcome boxes without crossing each other there.
        lane_x.clear()
        if not by_row[1]:
            return
        lo = min(boxes[k].x for k in by_row[1]) - LANE_GAP
        hi = max(boxes[k].right for k in by_row[1]) + LANE_GAP
        left = [e for e in long_links if channel.get(e['id']) == 'l']
        right_ = [e for e in long_links if channel.get(e['id']) != 'l']

        def spread(e: Dict[str, Any]) -> Tuple[float, float, str]:
            s, t = boxes[e['source']], boxes[e['target']]
            return t.cx, s.cx, e['id']
        left.sort(key=spread)
        right_.sort(key=spread)
        for i, e in enumerate(left):
            lane_x[e['id']] = lo - (len(left) - 1 - i) * LANE_SP
        for i, e in enumerate(right_):
            lane_x[e['id']] = hi + i * LANE_SP

    def place_outcomes() -> None:
        desired = {k: mean([lane_x.get(e['id'], boxes[e['source']].cx) for _, e in links if e['target'] == k],
                           row0_mid) for k in by_row[2]}
        for k, s in pack(by_row[2], desired, {k: boxes[k].w for k in by_row[2]}, [], 60, fixed=True).items():
            boxes[k].x = s

    for k in by_row[1]:
        boxes[k].x = desired_middle(k) - boxes[k].w / 2
    place_middle()
    for _ in range(4):
        place_outcomes()
        place_middle()

    left = min([b.x for b in boxes.values()] + list(lane_x.values()))
    for b in boxes.values():
        b.x += LEFT - left
    u1 = row_top[1] - STRIP_D
    u2 = row_top[1] + row_h[1]
    lanes = {eid: (u1, u2, lx + LEFT - left) for eid, lx in lane_x.items()}
    width = max([b.right for b in boxes.values()] + [v[2] for v in lanes.values()]) + 24
    # headings in the left margin, level with each row
    texts = (['Planting stock', '& site', 'treatments'], ['Conditions', 'they change'], ['Seedling', 'outcomes'])
    heads = [(12.0, row_top[r] + row_h[r] / 2 - 8 * (len(texts[r]) - 1) + 4, texts[r]) for r in (0, 1, 2)]
    # everything starts below a small top margin
    top = 20.0
    for b in boxes.values():
        b.y += top
    lanes = {eid: (v[0] + top, v[1] + top, v[2]) for eid, v in lanes.items()}
    heads = [(x_, y_ + top, t) for x_, y_, t in heads]
    return {'boxes': boxes, 'lanes': lanes, 'heads': heads, 'width': width, 'orders': orders}


def layout(g: Graph) -> Dict[str, Any]:
    return layout_down(g) if FLOW == 'down' else layout_right(g)


# ------------------------------------------------------------------ routing (mirrored in static/graph.js)

DIRS = {'r': (1.0, 0.0), 'l': (-1.0, 0.0), 'b': (0.0, 1.0), 't': (0.0, -1.0)}
INTO = {'l': (1.0, 0.0), 'r': (-1.0, 0.0), 't': (0.0, 1.0), 'b': (0.0, -1.0)}
DOWN = FLOW == 'down'
FLOWDIR = (0.0, 1.0) if DOWN else (1.0, 0.0)
MAIN_IN = 'tb' if DOWN else 'lr'   # sides an arrow enters with its long, labelled tail


def P(u: float, v: float) -> Pt:
    """A point from (along the flow, across the flow)."""
    return (v, u) if DOWN else (u, v)


def sides(s: Box, t: Box) -> Tuple[str, str]:
    if DOWN:
        if t.y - s.bottom >= 60:
            return 'b', 't'
        if s.y - t.bottom >= 60:
            return 't', 'b'
        return ('r', 'l') if t.cx >= s.cx else ('l', 'r')
    if t.x - s.right >= 60:
        return 'r', 'l'
    if s.x - t.right >= 60:
        return 'l', 'r'
    return ('b', 't') if t.cy >= s.cy else ('t', 'b')


def mod_side(s: Box, a: Pt) -> str:
    if DOWN:
        if a[1] - s.bottom >= 40:
            return 'b'
        if s.y - a[1] >= 40:
            return 't'
        return 'r' if a[0] >= s.cx else 'l'
    if a[0] - s.right >= 40:
        return 'r'
    if s.x - a[0] >= 40:
        return 'l'
    return 'b' if a[1] >= s.cy else 't'


def lane_active(s: Box, t: Box, side: Tuple[str, str], lane: Optional[Tuple[float, float, float]]) -> bool:
    if lane is None:
        return False
    if DOWN:
        return side == ('b', 't') and s.bottom + 40 <= lane[0] and lane[1] + 40 <= t.y - STRIP
    return side == ('r', 'l') and s.right + 40 <= lane[0] and lane[1] + 40 <= t.x - STRIP


def s_curve(a: Pt, da: Pt, b: Pt, db: Pt) -> Tuple[Pt, Pt]:
    """Control points for a smooth curve leaving a along da and arriving at b along db."""
    dist = abs(b[0] - a[0]) if da[1] == 0 else abs(b[1] - a[1])
    k = max(24.0, 0.5 * dist)
    return (a[0] + da[0] * k, a[1] + da[1] * k), (b[0] - db[0] * k, b[1] - db[1] * k)


def fmt_path(start: Pt, segs: List[Tuple[str, List[Pt]]]) -> str:
    out = 'M%s,%s' % (f1(start[0]), f1(start[1]))
    for op, pts in segs:
        out += ' %s%s' % (op, ' '.join('%s,%s' % (f1(p[0]), f1(p[1])) for p in pts))
    return out


def route_all(boxes: Dict[str, Box], arrows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Ports, paths and label spots for every arrow.

    arrows: dicts with id, s, t (or te for a moderation), lane (u1, u2, v) or None,
    lw/lh (label size), lt (label position along a moderation curve).
    """
    by_id = {a['id']: a for a in arrows}
    plain = [a for a in arrows if 'te' not in a]
    mods = [a for a in arrows if 'te' in a]

    info: Dict[str, Dict[str, Any]] = {}
    for a in plain:
        s, t = boxes[a['s']], boxes[a['t']]
        sd = sides(s, t)
        info[a['id']] = {'sides': sd, 'lane': a['lane'] if lane_active(s, t, sd, a['lane']) else None}

    def rough_anchor(te: str) -> Pt:
        ti = info[te]
        if ti['lane'] is not None:
            return P(ti['lane'][0] + MOD_INSET, ti['lane'][2])
        tgt = by_id[te]
        s, t = boxes[tgt['s']], boxes[tgt['t']]
        return (s.cx + t.cx) / 2, (s.cy + t.cy) / 2

    for m in mods:
        info[m['id']] = {'side': mod_side(boxes[m['s']], rough_anchor(m['te']))}

    # Collect every arrow end on every side of every box, then spread them along that side
    # in the order of where each arrow comes from or goes to (so arrows don't cross at the box).
    ends: Dict[Tuple[str, str], List[Tuple[float, str, str]]] = {}
    for a in plain:
        i = info[a['id']]
        s, t = boxes[a['s']], boxes[a['t']]
        so, ti = i['sides']
        if i['lane']:
            o_out = o_in = i['lane'][2]
        elif so in 'lr':
            o_out, o_in = t.cy, s.cy
        else:
            o_out, o_in = t.cx, s.cx
        ends.setdefault((a['s'], so), []).append((o_out, a['id'], 'out'))
        ends.setdefault((a['t'], ti), []).append((o_in, a['id'], 'in'))
    for m in mods:
        side = info[m['id']]['side']
        ra = rough_anchor(m['te'])
        ends.setdefault((m['s'], side), []).append((ra[1] if side in 'lr' else ra[0], m['id'], 'out'))
    for (nid, side), lst in ends.items():
        b = boxes[nid]
        lst.sort(key=lambda t: (t[0], t[1]))
        n = len(lst)
        # Top-down, the arrows coming in from above each get a slot as wide as their badge, so
        # the badges sit side by side in one row just above the arrowheads.
        slots = [by_id[aid]['lw'] + PORT_PAD if role == 'in' else OUT_W for _, aid, role in lst]
        total = sum(slots)
        spaced = DOWN and side in 'tb' and total <= b.w
        cum = (b.w - total) / 2
        for k, (_, aid, role) in enumerate(lst):
            f = (k + 1) / (n + 1)
            if spaced:
                f = (cum + slots[k] / 2) / b.w
                cum += slots[k]
            if side == 'l':
                p = (b.x, b.y + b.h * f)
            elif side == 'r':
                p = (b.right, b.y + b.h * f)
            elif side == 't':
                p = (b.x + b.w * f, b.y)
            else:
                p = (b.x + b.w * f, b.bottom)
            info[aid][role] = p
            if role == 'in':
                info[aid]['tier'] = k % 2

    out: Dict[str, Dict[str, Any]] = {}
    for a in plain:
        i = info[a['id']]
        so, ti = i['sides']
        p0, p3 = i['out'], i['in']
        d0, d3 = DIRS[so], INTO[ti]
        tail = STRIP if ti in MAIN_IN else VTAIL
        tp = (p3[0] - d3[0] * tail, p3[1] - d3[1] * tail)
        segs: List[Tuple[str, List[Pt]]] = []
        cur, cd = p0, d0
        if i['lane']:
            u1, u2, v = i['lane']
            la, lb = P(u1, v), P(u2, v)
            c1, c2 = s_curve(cur, cd, la, FLOWDIR)
            segs.append(('C', [c1, c2, la]))
            segs.append(('L', [lb]))
            cur, cd = lb, FLOWDIR
        c1, c2 = s_curve(cur, cd, tp, d3)
        main = (cur, c1, c2, tp)
        segs.append(('C', [c1, c2, tp]))
        segs.append(('L', [p3]))
        lw, lh = a['lw'], a['lh']
        tier = i.get('tier', 0) if DOWN else 0
        if ti == 'l' and not DOWN:
            lx, ly = p3[0] - HEAD_GAP - lw, p3[1] - lh / 2
        elif ti == 'r' and not DOWN:
            lx, ly = p3[0] + HEAD_GAP, p3[1] - lh / 2
        elif ti == 't' and DOWN:   # just above the arrowhead
            lx, ly = p3[0] - lw / 2, p3[1] - HEAD_GAP - lh - tier * TIER
        elif ti == 'b' and DOWN:
            lx, ly = p3[0] - lw / 2, p3[1] + HEAD_GAP + tier * TIER
        elif DOWN:   # entering from the side: label above the short horizontal tail
            lx, ly = (p0[0] + p3[0]) / 2 - lw / 2, (p0[1] + p3[1]) / 2 - lh - 6
        else:        # entering from above or below: label beside the short vertical tail
            lx, ly = p3[0] + 8, (p0[1] + p3[1]) / 2 - lh / 2
        if i['lane']:
            # where a moderation arrow lands: the start of the lane, clear of the middle boxes
            anchor = P(i['lane'][0] + MOD_INSET, i['lane'][2])
        else:
            anchor = bezier(*main, 0.5)
        out[a['id']] = {'d': fmt_path(p0, segs), 'label': (lx, ly), 'anchor': anchor}

    perp = (1.0, 0.0) if DOWN else (0.0, 1.0)   # a moderation arrow lands across the flow
    for m in mods:
        p0 = info[m['id']]['out']
        d0 = DIRS[info[m['id']]['side']]
        ax, ay = out[m['te']]['anchor']
        k1 = max(40.0, 0.5 * (abs(ax - p0[0]) if d0[1] == 0 else abs(ay - p0[1])))
        dp = (ax - p0[0]) if DOWN else (ay - p0[1])
        k2 = max(40.0, 0.5 * abs(dp))
        sign = 1 if dp >= 0 else -1
        pts = (p0, (p0[0] + d0[0] * k1, p0[1] + d0[1] * k1),
               (ax - perp[0] * sign * k2, ay - perp[1] * sign * k2), (ax, ay))
        cx, cy = bezier(*pts, m['lt'])
        out[m['id']] = {'d': fmt_path(p0, [('C', list(pts[1:]))]), 'ring': (ax, ay), 'pts': pts,
                        'label': (cx - m['lw'] / 2, cy - m['lh'] / 2)}
    return out


def member_path(m: Box, c: Box) -> str:
    """Thin bracket line from a member box to its combination box (not an arrow)."""
    if DOWN:
        # from the member's side nearest the combination, straight down where possible
        sx = m.right - 10 if m.cx < c.cx else m.x + 10
        ex = min(max(sx, c.x + 10), c.right - 10)
        return 'M%s,%s V%s H%s V%s' % (f1(sx), f1(m.bottom), f1(c.y - 14), f1(ex), f1(c.y))
    bx = min(m.x, c.x) - 14
    return 'M%s,%s H%s V%s H%s' % (f1(m.x), f1(m.cy), f1(bx), f1(c.cy), f1(c.x))


def arrows_of(g: Graph, lanes: Dict[str, Tuple[float, float, float]]) -> List[Dict[str, Any]]:
    arrows = []
    for kind, e in links_of(g):
        lw, lh = label_size(kind, e)
        arrows.append({'id': e['id'], 's': e['source'], 't': e['target'], 'lane': lanes.get(e['id']),
                       'lw': lw, 'lh': lh})
    for m in g.edges:
        if m.get('kind') == 'moderation':
            lw, lh = label_size('m', m)
            arrows.append({'id': m['id'], 's': m['source'], 'te': m['target_edge'], 'lw': lw, 'lh': lh,
                           'lt': 0.5})
    return arrows


def place_mod_labels(boxes: Dict[str, Box], arrows: List[Dict[str, Any]],
                     routes: Dict[str, Dict[str, Any]]) -> None:
    """Slide each moderation label along its curve to the spot that overlaps boxes and labels least."""
    def rect(x: float, y: float, w: float, h: float) -> Tuple[float, float, float, float]:
        return x - 4, y - 4, w + 8, h + 8

    taken = [rect(b.x, b.y, b.w, b.h) for b in boxes.values()]
    taken += [rect(r['label'][0], r['label'][1], a['lw'], a['lh'])
              for a in arrows if 'te' not in a for r in [routes[a['id']]]]
    for a in arrows:
        if 'te' not in a:
            continue
        pts = routes[a['id']]['pts']
        best = None
        for t in [0.5] + [round(0.5 + s * k * 0.025, 3) for k in range(1, 15) for s in (-1, 1)]:
            cx, cy = bezier(*pts, t)
            x, y = cx - a['lw'] / 2, cy - a['lh'] / 2
            hit = sum(max(0.0, min(x + a['lw'], rx + rw) - max(x, rx)) *
                      max(0.0, min(y + a['lh'], ry + rh) - max(y, ry)) for rx, ry, rw, rh in taken)
            if best is None or hit < best[0]:
                best = (hit, t, x, y)
            if hit == 0:
                break
        a['lt'] = best[1]
        routes[a['id']]['label'] = (best[2], best[3])
        lx, ly = routes[a['id']]['label']
        taken.append(rect(lx, ly, a['lw'], a['lh']))


# ------------------------------------------------------------------ SVG

def build_svg(g: Graph, edge_index: Dict[str, Any], prefix: str = 'q1graph') -> str:
    lay = layout(g)
    boxes, lanes = lay['boxes'], lay['lanes']
    arrows = arrows_of(g, lanes)
    by_id = {a['id']: a for a in arrows}
    routes = route_all(boxes, arrows)
    place_mod_labels(boxes, arrows, routes)
    effects = [e for e in g.edges if e.get('kind') == 'effect']
    mods = [e for e in g.edges if e.get('kind') == 'moderation']

    bottom = max([b.bottom for b in boxes.values()] +
                 [routes[a['id']]['label'][1] + a['lh'] for a in arrows])
    height = bottom + 28

    out: List[str] = []
    n_eff, n_mod = len(effects), len(mods)
    out.append('<svg id="q1g" viewBox="0 0 %s %s" width="100%%" role="group" aria-labelledby="g-title g-desc" '
               'data-flow="%s" data-strip="%d" data-vtail="%d" data-mod-inset="%d" data-head-gap="%d" '
               'data-tier="%d" data-port-pad="%d" data-out-w="%d">'
               % (f1(lay['width']), f1(height), FLOW, STRIP, VTAIL, MOD_INSET, HEAD_GAP, TIER, PORT_PAD, OUT_W))
    out.append('<title id="g-title">Tree planting: what acts on seedling survival and growth</title>')
    where = (('at the top', 'in the middle', 'at the bottom') if DOWN else
             ('on the left', 'in the middle', 'on the right'))
    out.append('<desc id="g-desc">%d boxes and %d effect %s, %d moderation %s and %d %s marked as not '
               'studied. Planting-stock traits and site treatments are %s, the conditions they '
               'change %s, seedling survival and growth %s. Arrows that skip the conditions run down '
               'the outer edges. Each arrow links to its evidence.</desc>'
               % (len(g.nodes), n_eff, 'arrow' if n_eff == 1 else 'arrows', n_mod,
                  'arrow' if n_mod == 1 else 'arrows', len(g.gaps), 'pairing' if len(g.gaps) == 1 else 'pairings',
                  *where))
    out.append('<defs>')
    for a in ('increase', 'decrease', 'mixed', 'none'):
        out.append('<marker id="ah-%s" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="13" '
                   'markerHeight="13" markerUnits="userSpaceOnUse" orient="auto">'
                   '<path d="M0,0 L10,5 L0,10 z" class="ah-%s"/></marker>' % (a, a))
    out.append('</defs>')

    for x, y, lines in lay['heads']:
        out.append('<text class="colhead">%s</text>' % ''.join(
            '<tspan x="%s" y="%s">%s</tspan>' % (f1(x), f1(y + i * 16), esc(t)) for i, t in enumerate(lines)))

    def label_svg(key: str, parts: List[Tuple[str, bool, float]], cls: str = 'lbl') -> str:
        a = by_id[key]
        lx, ly = routes[key]['label']
        # parts: (text, aria_hidden, baseline below the label's top). A hidden line repeats
        # what the link's name already says.
        texts = ''.join('<text x="%s" y="%s" text-anchor="middle"%s>%s</text>'
                        % (f1(lx + a['lw'] / 2), f1(ly + dy),
                           ' aria-hidden="true"' if hidden else '', p) for p, hidden, dy in parts)
        return ('<g class="%s"><rect x="%s" y="%s" width="%s" height="%s" rx="4"/>%s</g>'
                % (cls, f1(lx), f1(ly), f1(a['lw']), f1(a['lh']), texts))

    def data_attrs(key: str) -> str:
        a = by_id[key]
        if 'te' in a:
            return ' data-id="%s" data-s="%s" data-te="%s" data-lt="%s"' % (
                esc(key), esc(a['s']), esc(a['te']), a['lt'])
        lane = ''
        if a['lane'] is not None:
            lane = ' data-lane="%s %s %s"' % tuple(f1(v) for v in a['lane'])
        return ' data-id="%s" data-s="%s" data-t="%s"%s' % (esc(key), esc(a['s']), esc(a['t']), lane)

    def name(nid: str) -> str:
        return g.node(nid)['label']

    # combination brackets: a thin line from each member to the combination box
    for b in boxes.values():
        for m in b.node.get('members') or []:
            mb = boxes.get(m)
            if mb is not None:
                out.append('<path class="member" data-c="%s" data-m="%s" d="%s"/>'
                           % (esc(b.id), esc(m), member_path(mb, b)))

    # gaps
    for gp in g.gaps:
        gs = slug(gp['id'])
        d = routes[gp['id']]['d']
        out.append('<a href="#e-%s" class="gap-link" id="gapedge-%s" aria-label="%s to %s: no evidence, '
                   'not studied in this body of research. Opens details."%s>'
                   % (gs, gs, esc(name(gp['source'])), esc(name(gp['target'])), data_attrs(gp['id'])))
        out.append('<path class="hit" d="%s"/><path class="vis" d="%s"/>' % (d, d))
        out.append(label_svg(gp['id'], [(GAP_TAG, False, 16)]))
        out.append('</a>')

    # effect and moderation edges
    for e in effects + mods:
        es = slug(e['id'])
        d = routes[e['id']]['d']
        n = e['studies']
        studies = '%d %s' % (n, 'study' if n == 1 else 'studies')
        if e.get('kind') == 'moderation':
            t = g.edge(e['target_edge'])
            aria = '%s changes the effect of %s on %s: %s, certainty %s, %s. Opens evidence.' % (
                name(e['source']), name(t['source']), name(t['target']), WORD[e['direction']],
                CERT[e['certainty']].lower(), studies)
            cls = 'edge mod d-%s c-%s' % (e['direction'], e['certainty'])
        else:
            split = ''
            if e['direction'] == 'mixed':
                up, down = split_counts(e)
                split = '; %d found an increase, %d a decrease' % (up, down)
            aria = '%s to %s: %s, certainty %s, %s%s. Opens evidence.' % (
                name(e['source']), name(e['target']), WORD[e['direction']], CERT[e['certainty']].lower(), studies,
                split)
            cls = 'edge d-%s c-%s' % (e['direction'], e['certainty'])
        # One meaning per channel: colour = direction, thickness = number of studies (w-1..4),
        # dash pattern = certainty (c-...). The badge shows the direction symbol and the study
        # count ("↑ 3"), or for a mixed arrow how many studies went up and down, a zero left out
        # ("⇅ ↑5 ↓1", "⇅ ↑1", "⇅"); the name says the same in words.
        cls += ' w-%d' % weight_class(n)
        split_all = ', '.join('%s %d' % (WORD.get(k, k), v)
                              for k, v in sorted((e.get('study_directions') or {}).items(), key=lambda kv: -kv[1]))
        out.append('<a href="#e-%s" class="%s" id="edge-%s" aria-label="%s"%s data-n="%d" data-split="%s">'
                   % (es, cls, es, esc(aria), data_attrs(e['id']), n, esc(split_all)))
        out.append('<path class="hit" d="%s"/>' % d)
        if e.get('kind') == 'moderation':
            out.append('<path class="vis c-%s" d="%s"/>' % (e['certainty'], d))
            rx, ry = routes[e['id']]['ring']
            out.append('<circle class="ring" cx="%s" cy="%s" r="6"/>' % (f1(rx), f1(ry)))
        else:
            out.append('<path class="vis c-%s" d="%s" marker-end="url(#ah-%s)"/>'
                       % (e['certainty'], d, ARROW[e['direction']]))
        if e['direction'] == 'mixed' and e.get('kind') != 'moderation':
            up, down = split_counts(e)
            main = '<tspan class="sym" aria-hidden="true">⇅</tspan>'
            for sym, field, v in (('↑', 'increase', up), ('↓', 'decrease', down)):
                if v:
                    main += (' <tspan class="split" aria-hidden="true">%s</tspan>'
                             '<tspan class="n" data-check="%s/%s/study_directions/%s">%d</tspan>'
                             % (sym, prefix, es, field, v))
        else:
            main = ('<tspan class="sym" aria-hidden="true">%s</tspan> '
                    '<tspan class="n" data-check="%s/%s/studies">%d</tspan>' % (SYM[e['direction']], prefix, es, n))
        out.append(label_svg(e['id'], [(main, False, 17.0)]))
        out.append('</a>')

    # boxes last, so they sit on top of any arrow a reader drags under them
    for b in boxes.values():
        if b.node.get('kind') == 'combination':   # a hexagon: two treatments applied together
            shape = ('<path class="shape" d="M0,%s L%s,0 H%s L%s,%s L%s,%s H%s Z"/>'
                     % (f1(b.h / 2), f1(COMB_TIP), f1(b.w - COMB_TIP), f1(b.w), f1(b.h / 2),
                        f1(b.w - COMB_TIP), f1(b.h), f1(COMB_TIP)))
        else:
            shape = '<rect class="shape" width="%s" height="%s" rx="6"/>' % (f1(b.w), f1(b.h))
        out.append('<g class="node k-%s" id="n-%s" data-id="%s" data-w="%s" data-h="%s" transform="translate(%s,%s)">%s'
                   % (esc(b.node.get('kind', '')), esc(slug(b.id)), esc(b.id), f1(b.w), f1(b.h), f1(b.x), f1(b.y),
                      shape))
        out.append('<text text-anchor="middle">')
        top = (b.h - LINE_H * len(b.lines)) / 2
        for i, line in enumerate(b.lines):
            out.append('<tspan x="%s" y="%s">%s</tspan>' % (f1(b.w / 2), f1(top + 13 + i * LINE_H), esc(line)))
        out.append('</text></g>')

    out.append('</svg>')
    return '\n'.join(out)


def write_graph(graph: Graph, edge_index: Dict[str, Any], out: str, qid: str = 'q1') -> None:
    name = '%s-graph.html' % qid
    path = os.path.join(out, name)
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    if '<!--GRAPH-->' not in text:
        raise RuntimeError('%s has no <!--GRAPH--> placeholder' % name)
    text = text.replace('<!--GRAPH-->', build_svg(graph, edge_index, '%sgraph' % qid), 1)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)
