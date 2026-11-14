"""Render the static pages (the Q1 SVG is added afterwards by graph_svg.py).

Every value from the pack is escaped with html.escape(quote=True). Every pack
number, direction and certainty sits in a data-check span that check.py
verifies against the answer files.
"""
from __future__ import annotations

import datetime
import html
import json
import os
import re
import shutil
import sys
from string import Template
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Tuple

from load import (CERTAINTIES, COMPARISON, EFFECT_DIRECTIONS, EFFECTS, GAPMAP, REFERENCE_DIRECTIONS,
                  Finding, Gap, Question, Quote, SiteData, slug)
from summarize import CERT_WORD, Prose
from graph_svg import FLOW as GRAPH_FLOW

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --------------------------------------------------------------- vocabulary

DIR_SYMBOL = {
    'increase': ('↑', 'Increase'), 'decrease': ('↓', 'Decrease'), 'mixed': ('⇅', 'Mixed'),
    'no_effect': ('–', 'No effect'), 'unclear': ('?', 'Unclear'),
    'below_reference': ('↓', 'Below reference'), 'comparable': ('=', 'Comparable'),
    'above_reference': ('↑', 'Above reference'),
}

PREDICATE = {
    'causes': ('causes', 'does not cause'),
    'associated_with': ('is associated with', 'is not associated with'),
    'correlated_with': ('is correlated with', 'is not correlated with'),
    'enables': ('enables', 'does not enable'),
    'prevents': ('prevents', 'does not prevent'),
    'moderates': ('changes the effect of', 'does not change the effect of'),
    'contributes_to': ('contributes to', 'does not contribute to'),
    'disrupts': ('disrupts', 'does not disrupt'),
}

COMPARATOR = {
    'untreated_control': 'an untreated control', 'alternative_treatment': 'another treatment',
    'not_reported': 'not reported', 'reference_undisturbed': 'an undisturbed reference site',
    'not_applicable': 'not applicable', 'pre_treatment_baseline': 'the site before treatment',
    'spatial_or_temporal_control': 'a control in space or time',
}

CAUSAL_LANGUAGE = {
    'direct_causal': 'states a direct cause', 'associational': 'states an association',
    'no_relationship': 'states no relationship', 'uncertain_causal': 'states a possible cause',
}

AUDIENCE = {
    'q1': 'Foresters, planting contractors and nursery managers planning reforestation.',
    'q2': 'Wetland managers and agencies that build or approve created marshes.',
    'q3': 'Grassland restoration practitioners, funders and researchers choosing what to study next.',
}
DEFAULT_AUDIENCE = 'Restoration practitioners.'

# The graph page's intro, per question; %s %s = where causes and outcomes sit (top/bottom or left/right).
GRAPH_INTRO = {
    'q1': ('Planting-stock traits and site treatments (%s) act on seedling survival and growth '
           '(%s), directly and through the conditions they change (middle). '),
}
DEFAULT_GRAPH_INTRO = ('Causes (%s) act on outcomes (%s), directly and through the conditions they change '
                       '(middle). ')


def graph_file(qid: str) -> str:
    return '%s-graph.html' % qid


def graph_prefix(qid: str) -> str:
    """data-check prefix for a question's graph values, e.g. q1graph/<edge>/certainty."""
    return '%sgraph' % qid


def qnum(data: SiteData, qid: str) -> int:
    return list(data.questions).index(qid) + 1


def esc(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def words(s: Optional[str]) -> str:
    return (s or '').replace('_', ' ')


def span(path: str, text: Any, cls: str = '') -> str:
    c = ' class="%s"' % cls if cls else ''
    return '<span data-check="%s"%s>%s</span>' % (esc(path), c, esc(text))


def plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


# --------------------------------------------------------------- building blocks

def direction_badge(d: str, path: Optional[str] = None) -> str:
    sym, word = DIR_SYMBOL[d]
    w = span(path, word) if path else esc(word)
    return ('<span class="dir dir-%s"><span aria-hidden="true">%s</span> %s</span>'
            % (esc(d.replace('_', '-')), sym, w))


def certainty_text(c: str) -> str:
    return '%s certainty' % CERT_WORD[c]


def certainty_badge(certainty: str, rationale: Optional[str], label: str, path: str) -> str:
    why = esc(rationale) if rationale else 'The pack gives no rationale for this grade.'
    return ('<details class="cert cert-%s"><summary>%s <span class="sr-only">for %s</span>'
            ' · Why?</summary><p>%s</p></details>'
            % (esc(certainty.replace('_', '-')), span(path + '/certainty', certainty_text(certainty)),
               esc(label), why))


def counts(base: str, studies: int, claims: int) -> str:
    return ('<span class="counts">%s %s · %s %s</span>'
            % (span(base + '/studies', studies), plural(studies, 'study', 'studies'),
               span(base + '/claims', claims), plural(claims, 'claim', 'claims')))


def vote_split(base: str, study_directions: Dict[str, int], reference: bool) -> str:
    if not study_directions:
        return ''
    order = list(REFERENCE_DIRECTIONS if reference else EFFECT_DIRECTIONS)
    keys = [k for k in order if k in study_directions] + \
           sorted(k for k in study_directions if k not in order)
    parts = []
    for k in keys:
        word = DIR_SYMBOL[k][1] if k in DIR_SYMBOL else words(k)
        parts.append('%s %s' % (esc(word), span('%s/study_directions/%s' % (base, k), study_directions[k])))
    return '<span class="votes">Studies by direction: %s</span>' % ' · '.join(parts)


def claim_sentence(q: Quote, prefix: str) -> str:
    pos, neg = PREDICATE.get(q.predicate, (words(q.predicate), 'not ' + words(q.predicate)))
    base = '%s/claim/%s' % (prefix, q.edge_id)
    return '%s %s %s' % (span(base + '/subject', q.subject), esc(neg if q.negated else pos),
                         span(base + '/object', q.object))


def evidence_box(q: Quote, n: int, id_prefix: str, check_prefix: str, open_: bool = False) -> str:
    base = '%s/claim/%s' % (check_prefix, q.edge_id)
    year = span(base + '/year', q.year) if q.year is not None else 'year not given'
    if q.doi:
        src = ('<a href="https://doi.org/%s" rel="noopener">%s</a>, %s. <small class="doi">DOI %s</small>'
               % (esc(q.doi), esc(q.title), year, esc(q.doi)))
    else:
        src = '%s, %s. <small class="doi">(no DOI in pack)</small>' % (esc(q.title), year)
    tested = ', '.join(words(t) for t in q.evidence_types) or 'design not given'
    comp = COMPARATOR.get(q.comparator or '', words(q.comparator))
    if comp and q.comparator not in ('not_reported', 'not_applicable'):
        tested += ', compared with ' + comp
    elif q.comparator == 'not_reported':
        tested += ' (no comparison reported)'
    found = DIR_SYMBOL.get(q.direction, ('', words(q.direction)))
    rows = [
        ('Claim', claim_sentence(q, check_prefix)),
        ('How they tested it', esc(tested[:1].upper() + tested[1:])),
        ('This study found', '<span aria-hidden="true">%s</span> %s' % (found[0], esc(found[1]))),
        ('Study quality', '%s <span class="note">(this claim\'s own grade)</span>'
         % esc(CERT_WORD.get(q.certainty_grade, words(q.certainty_grade) or 'not given'))),
        ('Ecosystem', esc(words(q.ecosystem_context) or 'not given')),
        ("Authors' wording", esc(CAUSAL_LANGUAGE.get(q.causal_language or '',
                                                     words(q.causal_language) or 'not given'))),
    ]
    dl = ''.join('<dt>%s</dt><dd>%s</dd>' % r for r in rows)
    return ('<details class="ev" data-claim="%s" id="%s-%d"%s><summary>Source %d · %s</summary>'
            '<blockquote class="quote">%s</blockquote><p class="src">%s</p>'
            '<dl class="camo">%s</dl></details>'
            % (esc(q.edge_id), esc(id_prefix), n, ' open' if open_ else '', n, year,
               esc(q.quote), src, dl))


# Source pages: the full quotes for each finding or graph arrow live on their own small page
# (sources-<slug>.html), so the answer pages stay light. Each renderer is handed a list and
# appends the source pages it links to; render_site writes them.
class SourcePage(NamedTuple):
    fname: str
    title: str
    description: str
    body: str


SOURCES_NOTE = ('<p class="note">Each source is one sentence quoted from a paper, with a link to the paper. '
                '“Authors\' wording” is how strongly the paper words its claim; it is separate from the '
                'certainty grade (<a href="method.html#certainty">how certainty is graded</a>).</p>')


# A link into something closed (paper 5 behind "Show the other papers", or a finding card
# from the glance table or gap map) opens it. Without script it is just one click away.
OPEN_TARGET_JS = ('<script>function openTarget(){var e=location.hash&&document.getElementById('
                  'decodeURIComponent(location.hash.slice(1)));if(!e)return;for(var p=e;p;p=p.parentElement)'
                  '{if(p.tagName==="DETAILS")p.open=true;}if(e.tagName!=="DETAILS"){var d=e.querySelector("details");'
                  'if(d)d.open=true;}var pp=e.closest("[popover]");if(pp&&pp.showPopover){try{pp.showPopover()}catch(x){}}'
                  'else e.scrollIntoView();}addEventListener("hashchange",openTarget);openTarget();</script>')


# "?" button (top right of the Why box and the glance table) opening one popup per page.
# Uses the browser's popover attribute: no script, keyboard and Esc work, closes on outside click.
HELP_BTN = ('<button type="button" class="help" popovertarget="how-grading" aria-label="How grading works">'
            '?</button>')
GRADING_POPOVER = (
    '<div id="how-grading" popover class="pop" role="dialog" aria-labelledby="how-grading-h">'
    '<h2 id="how-grading-h">How grading works</h2>'
    '<p>Each finding gets a certainty level from 1 to 4, shown as bars: '
    '<strong>4</strong> High · <strong>3</strong> Moderate · <strong>2</strong> Low · <strong>1</strong> Very low.</p>'
    '<ol><li><strong>Start</strong> from the best kind of study behind it: randomized experiments with an untreated '
    'control start at 4; other controlled studies at 3; observation only at 2; models or case studies at 1.</li>'
    '<li><strong>−1</strong> if there is only one study, if studies disagree, or if most claims have nothing to '
    'compare against.</li>'
    '<li><strong>+1</strong> if three or more studies agree, or if it shows how it works, not just that it works.</li>'
    '<li>The level stays between 1 and 4, and one study never goes above 3.</li></ol>'
    '<p class="ex">Example: start 4, −1 studies disagree, +1 shows how it works = <strong>4 High</strong>.</p>'
    '<p><a href="method.html#certainty">Full method →</a> '
    '<button type="button" popovertarget="how-grading" popovertargetaction="hide">Close</button></p></div>')


def paper_groups(quotes: Iterable[Quote]) -> List[List[Quote]]:
    """Quotes grouped by paper, in first-seen order (paper k is id="p-k" on the sources page)."""
    groups: Dict[str, List[Quote]] = {}
    for q in quotes:
        groups.setdefault(q.document_id or q.doi or q.title, []).append(q)
    return list(groups.values())


def source_page_link(sources: List[SourcePage], quotes: Iterable[Quote], *, fname: str, id_prefix: str,
                     check_prefix: str, label: str, back: str, back_text: str, description: str) -> str:
    """Add a page with these quotes (open, so the sentence shows at once) to sources; return a link to it.

    Quotes are grouped by paper. The first SHOW_PAPERS papers are shown; the rest sit in a
    "Show all" <details> (no script needed, and still in the page for checkers and crawlers)."""
    groups = paper_groups(quotes)
    sections, n = [], 0
    for k, qs in enumerate(groups):
        head = '%s%s' % (esc(qs[0].title), ' (%s)' % esc(qs[0].year) if qs[0].year is not None else '')
        boxes = []
        for q in qs:
            n += 1
            boxes.append(evidence_box(q, n, id_prefix, check_prefix, open_=True))
        sections.append('<section class="paper" id="p-%d"><h2>Paper %d of %d: %s</h2>%s</section>'
                        % (k + 1, k + 1, len(groups), head, ''.join(boxes)))
    shown = ''.join(sections[:SHOW_PAPERS])
    if len(sections) > SHOW_PAPERS:
        rest = len(sections) - SHOW_PAPERS
        shown += ('<details class="more"><summary>Show the other %d %s</summary>%s</details>'
                  % (rest, plural(rest, 'paper', 'papers'), ''.join(sections[SHOW_PAPERS:])))
    boxes = shown
    back_link = '<p class="back"><a href="%s">%s</a></p>' % (esc(back), esc(back_text))
    body = ('<h1>Sources: %s</h1>%s%s<div class="sources">%s</div>%s%s'
            % (esc(label), back_link, SOURCES_NOTE, boxes, back_link, OPEN_TARGET_JS))
    sources.append(SourcePage(fname, 'Sources · ' + label, description, body))
    return ('<a class="srclink" href="%s">Read all sources<span class="sr-only"> for %s</span></a>'
            % (esc(fname), esc(label)))


def finding_sources(sources: List[SourcePage], f: Finding, qid: str) -> str:
    return source_page_link(sources, f.quotes, fname='sources-%s.html' % f.slug, id_prefix='ev-' + f.slug,
                            check_prefix=qid, label=f.label, back='%s.html#f-%s' % (qid, f.slug),
                            back_text='Back to the finding',
                            description='The quoted sentences behind one finding.')


SHOW_PAPERS = 3  # papers shown at once on a sources page; the rest behind "Show all"

# --------------------------------------------------------------- finding cards (#49)
# Layer 1 is the card (direction, certainty bars, agreement bar, counts); layer 2 is
# "See why" (the certainty reason in plain English, and on Q1 the possible pathways);
# layer 3 is the sources page it links to.

CERT_BARS = {'very_low': 1, 'low': 2, 'moderate': 3, 'high': 4}
CERT_ORDER = ['high', 'moderate', 'low', 'very_low']
QUOTES_IN_CARD = 2  # papers quoted inside an open card; the rest are on its sources page (Q3: 1, page weight)

# How the study split names each direction ("5 of 7 found an increase").
FOUND = {
    'increase': 'an increase', 'decrease': 'a decrease', 'mixed': 'mixed results',
    'no_effect': 'no effect', 'unclear': 'an unclear direction',
    'below_reference': 'below the reference', 'comparable': 'comparable to the reference',
    'above_reference': 'above the reference',
}

# The pack's certainty_rationale as a short tally. What the levels mean is explained once,
# on the method page; the raw rationale is always shown too (small, grey).
# The pack's certainty_rationale as a plain checklist (README "How certainty is graded").
# ✓ / ✗ are text, so the meaning never rests on colour. The exact rationale is always shown too.
START_CHECK = {
    'high': ('✓', 'Proper experiments (treated vs. untreated plots)'),
    'moderate': ('✓', 'Controlled studies, but not fully randomized'),
    'low': ('✗', 'Observation only, no experiments'),
    'very low': ('✗', 'Based on models or single case studies'),
}
STEP_CHECK = [
    (re.compile(r'^-1 single study$'), ('✗', 'Only one study')),
    (re.compile(r'^-1 studies disagree$'), ('✗', "Studies didn't all agree")),
    (re.compile(r'^-1 most claims report no comparator$'), ('✗', 'Mostly no untreated site to compare against')),
    (re.compile(r'^\+1 (\d+) studies agree$'), ('✓', '{0} studies agree')),  # the pack's word; not "same result"
    (re.compile(r'^\+1 mechanistic and difference-making evidence$'), ('✓', 'Shows how it works, not just that it works')),
]
RATIONALE = re.compile(r'^start (high|moderate|low|very low) \([^)]*\)(.*?)\s*->\s*(high|moderate|low|very low)$')


def norm_space(s: str) -> str:
    return ' '.join(s.split())


def rationale_checks(r: Optional[str]) -> List[Tuple[str, str]]:
    """[(mark, text)] for a rationale; [] if it doesn't follow the pack's pattern."""
    m = RATIONALE.match(norm_space(r or ''))
    if not m:
        return []
    out = [START_CHECK[m.group(1)]]
    for part in (p.strip() for p in m.group(2).split(';')):
        if not part:
            continue
        for pat, (mark, text) in STEP_CHECK:
            mm = pat.match(part)
            if mm:
                out.append((mark, text.format(*mm.groups())))
                break
        else:
            out.append(('·', part))
    return out


LEVEL = {'very low': 1, 'low': 2, 'moderate': 3, 'high': 4}
LEVEL_WORD = {1: 'Very low', 2: 'Low', 3: 'Moderate', 4: 'High'}


def rationale_score(r: Optional[str]) -> Optional[Tuple[int, List[int], int, str]]:
    """(start level, step changes, final level, cap note) using the 1-4 scale the bars show.
    The pack's final grade is what is shown; the note says why a sum went past a limit."""
    m = RATIONALE.match(norm_space(r or ''))
    if not m:
        return None
    steps = [p.strip() for p in m.group(2).split(';') if p.strip()]
    deltas = []
    for p in steps:
        mm = re.match(r'^([+-]\d+)\b', p)
        deltas.append(int(mm.group(1)) if mm else 0)
    start, final = LEVEL[m.group(1)], LEVEL[m.group(3)]
    total = start + sum(deltas)
    note = ''
    if total != final:
        if total > 4 and final == 4:
            note = 'adds up to %d, capped at 4: High is the top level' % total
        elif total < 1 and final == 1:
            note = 'adds up to %d, kept at 1: Very low is the lowest level' % total
        elif final == 3 and any('single study' in p for p in steps):
            note = 'adds up to %d, capped at 3: one study never goes above Moderate' % total
        else:
            note = 'adds up to %d; the pack grades it %d' % (total, final)
    return start, deltas, final, note


def _checks_js() -> str:
    """Builds the Why checklist in the browser from a card's exact rule text (used on Q3, where
    the card repeats 123 times). The lookup tables come from START_CHECK / STEP_CHECK above."""
    start = json.dumps({k: list(v) for k, v in START_CHECK.items()}, ensure_ascii=False)
    steps = json.dumps([[pat.pattern, mk, t] for pat, (mk, t) in STEP_CHECK], ensure_ascii=False)
    return ('<script>(function(){var ST=%s,SP=%s,LV={"very low":1,low:2,moderate:3,high:4},'
            'LW={1:"Very low",2:"Low",3:"Moderate",4:"High"},'
            'RX=/^start (high|moderate|low|very low) \\([^)]*\\)(.*?)\\s*->\\s*(high|moderate|low|very low)$/;'
            'function e(t){var d=document.createElement("span");d.textContent=t;return d.innerHTML}'
            'function li(mk,t,p){return \'<li><span class="mk" aria-hidden="true">\'+mk+\'</span><span class="sr-only">\''
            '+({"✓":"For","✗":"Against"}[mk]||"Note")+\': </span><span class="t">\'+e(t)+\'</span><span class="pts">\'+p+\'</span></li>\'}'
            'document.querySelectorAll("ul.checks[data-rule]").forEach(function(ul){'
            'var r=ul.parentNode.querySelector("p.rule").textContent.replace(/\\s+/g," ").trim(),m=r.match(RX);'
            'if(!m){ul.remove();return}var s=ST[m[1]],o=li(s[0],s[1],"start "+LV[m[1]]),tot=LV[m[1]],one=false;'
            'm[2].split(";").forEach(function(p){p=p.trim();if(!p)return;var d=+((p.match(/^([+-]\\d+)/)||[0,0])[1]);'
            'tot+=d;if(/single study/.test(p))one=true;for(var i=0;i<SP.length;i++){var x=p.match(new RegExp(SP[i][0]));'
            'if(x){o+=li(SP[i][1],SP[i][2].replace("{0}",x[1]||""),d?(d>0?"+":"\u2212")+Math.abs(d):"");return}}'
            'o+=li("·",p,"")});var f=LV[m[3]],n="";if(tot!==f){n="adds up to "+tot+(tot>4&&f==4?", capped at 4: High is '
            'the top level":tot<1&&f==1?", kept at 1: Very low is the lowest level":f==3&&one?", capped at 3: one study '
            'never goes above Moderate":"; the pack grades it "+f)}'
            'o+=\'<li class="total"><span class="mk" aria-hidden="true">=</span><span class="t">\'+LW[f]+'
            '(n?\' <span class="cap">(\'+e(n)+\')</span>\':"")+\'</span><span class="pts">\'+f+\'</span></li>\';'
            'ul.innerHTML=o})})();</script>' % (start, steps))


CHECKS_JS = _checks_js()


START_WHY = {
    'high': 'the best studies are proper experiments (treated vs. untreated plots)',
    'moderate': 'the best studies are controlled, but not fully randomized',
    'low': 'the best studies only observe, with no experiment',
    'very low': 'the evidence is models or single case studies',
}
LEVELS_BTN = ('<button type="button" class="help" popovertarget="how-levels" aria-label="How certainty levels are set">'
              '<span aria-hidden="true">?</span></button>')
LEVELS_POPOVER = (
    '<div id="how-levels" popover class="pop" role="dialog" aria-labelledby="how-levels-h">'
    '<h2 id="how-levels-h">How certainty levels are set</h2>'
    '<p>Certainty is how much you can trust a result, not how big the effect is. There are four levels: '
    '<strong>Very low · Low · Moderate · High</strong>. The same recipe is applied to every finding.</p>'
    '<table class="levels"><tbody>'
    '<tr><th scope="row">1. Start</th><td>at the level of the best kind of study behind the result: '
    'experiments with untreated plots → High · other controlled studies → Moderate · observation only → Low · '
    'models or case studies → Very low</td></tr>'
    '<tr><th scope="row">2. Down one level</th><td>for each of: only one study · the studies disagree · most '
    'claims have no untreated site to compare against</td></tr>'
    '<tr><th scope="row">3. Up one level</th><td>for each of: three or more studies agree · the studies show '
    '<em>how</em> it works, not only <em>that</em> it works</td></tr>'
    '<tr><th scope="row">4. Limits</th><td>High is the top and Very low the bottom · one study never goes above '
    'Moderate</td></tr></tbody></table>'
    '<p class="ex">Example: starts at High (experiments) · down one, the studies disagree (Moderate) · up one, '
    'they show how it works · ends at <strong>High</strong>.</p>'
    '<p><a href="method.html#certainty">Full method →</a> '
    '<button type="button" popovertarget="how-levels" popovertargetaction="hide">Close</button></p></div>')


def level_track(r: Optional[str]) -> str:
    """The pack's certainty_rationale as steps on the four levels: a dot shows the level after each
    step. The last row is always the pack's own grade. '' if the rationale doesn't follow the pattern."""
    m = RATIONALE.match(norm_space(r or ''))
    if not m:
        return ''
    cells = lambda lv: ''.join('<i%s></i>' % (' class="on"' if i == lv else '') for i in range(1, 5))
    def row(cls: str, mk: str, text: str, lv: int, note: str = '') -> str:
        return ('<li class="%s"><span class="t"><span class="mk" aria-hidden="true">%s</span> %s%s'
                '<span class="sr-only">: now %s</span></span><span class="lv" aria-hidden="true">%s</span></li>'
                % (cls, mk, text, (' <span class="cap">(%s)</span>' % esc(note)) if note else '',
                   LEVEL_WORD[lv], cells(lv)))
    lv = LEVEL[m.group(1)]
    out = [row('start', '●', 'Starts at <strong>%s</strong>: %s' % (LEVEL_WORD[lv], esc(START_WHY[m.group(1)])), lv)]
    for part in (p.strip() for p in m.group(2).split(';') if p.strip()):
        text = part
        for pat, (_, t) in STEP_CHECK:
            mm = pat.match(part)
            if mm:
                text = t.format(*mm.groups())
                break
        d = re.match(r'^([+-]\d+)\b', part)
        d = int(d.group(1)) if d else 0
        new = min(4, max(1, lv + d))
        note = ''
        if d > 0 and new == lv:
            note = 'already at the top, so no change'
        elif d < 0 and new == lv:
            note = 'already at the bottom, so no change'
        out.append(row('step', '↑' if d > 0 else ('↓' if d < 0 else '·'),
                       '%s %s' % ({1: 'Up one:', -1: 'Down one:'}.get(d, ''), esc(text)), new, note))
        lv = new
    final = LEVEL[m.group(3)]
    note = ''
    if final != lv:
        note = ('one study never goes above Moderate' if final == 3 and 'single study' in m.group(2)
                else 'the final grade from the data')
    out.append(row('total', '=', 'Ends at <strong>%s</strong>' % LEVEL_WORD[final], final, note))
    head = ('<li class="hd" aria-hidden="true"><span class="t"></span><span class="lv">'
            '<b>Very low</b><b>Low</b><b>Moderate</b><b>High</b></span></li>')
    return '<ol class="track">%s%s</ol>' % (head, ''.join(out))


def headline_reason(checks: List[Tuple[str, str]]) -> Optional[Tuple[str, str]]:
    """For the closed card: the first ✗, or if none the strongest ✓ (agreement, then mechanism, then design)."""
    for c in checks:
        if c[0] == '✗':
            return c
    ok = [c for c in checks if c[0] == '✓']
    for key in ('studies agree', 'how it works'):
        for c in ok:
            if key in c[1]:
                return c
    return ok[0] if ok else None


CHIP = {'increase': ('▲', 'Increase', 's'), 'decrease': ('▼', 'Decrease', 's'), 'mixed': ('⇅', 'Mixed', ''),
        'no_effect': ('–', 'No effect', ''), 'unclear': ('?', 'Unclear', ''),
        'below_reference': ('◀', 'Behind', ''), 'comparable': ('=', 'Matches', ''),
        'above_reference': ('▶', 'Ahead', '')}  # plain words, the same as the Q2 chart


def chip(d: str, path: str) -> str:
    """Direction chip. The checked word stays exactly the pack's word ("Increase"); the plain
    "s" sits outside the data-check span so the chip reads "▲ Increases"."""
    sym, word, tail = CHIP.get(d, ('', words(d), ''))
    return ('<span class="dir chip dir-%s"><span aria-hidden="true">%s</span> %s%s</span>'
            % (esc(d.replace('_', '-')), sym, span(path, word), tail))


def _dot(k: str) -> str:
    return '<i class="dot s-%s" aria-hidden="true"></i>' % esc(k.replace('_', '-'))


def _keys(f_reference: bool, sd: Dict[str, int]) -> List[str]:
    order = list(REFERENCE_DIRECTIONS if f_reference else EFFECT_DIRECTIONS)
    return [k for k in order if k in sd] + sorted(k for k in sd if k not in order)


def split_bar(f: Finding) -> str:
    sd = f.study_directions
    if not sd:
        return ''
    segs = ''.join('<i class="s-%s" style="flex-grow:%d"></i>' % (esc(k.replace('_', '-')), sd[k])
                   for k in _keys(f.reference, sd))
    return '<span class="agree" aria-hidden="true">%s</span>' % segs


SHORT = {'increase': 'up', 'decrease': 'down', 'mixed': 'mixed', 'no_effect': 'no effect', 'unclear': 'unclear',
         'below_reference': 'behind', 'comparable': 'matches', 'above_reference': 'ahead'}


def split_short(f: Finding, base: str) -> str:
    """"7 studies: 5 up · 1 mixed · 1 none" with a dot per direction; every number checked."""
    sd = f.study_directions
    head = '%s %s' % (span(base + '/studies', f.studies), plural(f.studies, 'study', 'studies'))
    if not sd:
        return head
    keys = _keys(f.reference, sd)
    if f.direction in keys:
        keys.remove(f.direction)
        keys.insert(0, f.direction)
    return head + ': ' + ' · '.join('<span class="sp">%s%s %s</span>' % (_dot(k), span('%s/study_directions/%s' % (base, k), sd[k]),
                                                                         esc(SHORT.get(k, words(k)))) for k in keys)


def tested_how(q: Quote) -> str:
    t = ', '.join(words(x) for x in q.evidence_types) or 'study type not given'
    return t[:1].upper() + t[1:]


def card_quote(q: Quote) -> str:
    """One quote, word for word, then where it is from."""
    title = esc(q.title)
    if q.doi:
        title = '<a href="https://doi.org/%s">%s</a>' % (esc(q.doi), title)
    year = ', %s' % esc(q.year) if q.year is not None else ''
    return ('<figure class="cq"><blockquote class="quote">%s</blockquote><figcaption>%s%s · %s</figcaption></figure>'
            % (esc(q.quote), title, year, esc(tested_how(q))))


def pathways(data: SiteData, f: Finding) -> str:
    """Q1 only: subject -> condition -> outcome routes in the graph, drawn as a vertical chain.
    Each step is its own body of evidence with its own certainty; never combined (README)."""
    g = data.graphs.get(f.question)
    if g is None:
        return ''
    gfile = graph_file(f.question)
    effects = [e for e in g.edges if e.get('kind') == 'effect']
    first = {e['target']: e for e in effects if e['source'] == f.subject_id}
    chains = []
    for e2 in effects:
        e1 = first.get(e2['source'])
        if e1 is None or e2['target'] != f.outcome_id or g.node(e2['source']).get('kind') != 'condition':
            continue
        parts = ['<li class="node">%s</li>' % esc(g.node(e1['source'])['label'])]
        for e in (e1, e2):
            s = slug(e['id'])
            base = '%s/%s' % (graph_prefix(f.question), s)
            parts.append('<li class="step"><span class="down" aria-hidden="true">↓</span> %s · %s · %s %s</li>'
                         % (chip(e['direction'], base + '/direction'),
                            span(base + '/certainty', certainty_text(e['certainty'])),
                            span(base + '/studies', e['studies']), plural(e['studies'], 'study', 'studies')))
            parts.append('<li class="node">%s</li>' % esc(g.node(e['target'])['label']))
        chains.append('<ol class="chain">%s</ol>' % ''.join(parts))
    graph = ''
    if f.slug in data.graph_join:
        graph = ('<p class="go"><a href="%s#e-%s">See on the graph →<span class="sr-only"> %s</span></a></p>'
                 % (gfile, esc(slug(data.graph_join[f.slug])), esc(f.label)))
    if not chains:
        # a gap, shown as a gap: no study here links this factor to a condition on the way
        conds = [n['label'] for n in g.nodes if n.get('kind') == 'condition']
        names = ', '.join(c[:1].lower() + c[1:] for c in conds[:-1]) + ' or ' + conds[-1][:1].lower() + conds[-1][1:] \
            if len(conds) > 1 else ''.join(conds)
        return ('<section class="panel"><h5>Possible pathways</h5><p class="none-pw"><span class="gq" aria-hidden="true">'
                '?</span> None in this research. No study here linked %s to %s.</p>%s</section>'
                % (esc(_lower_first(f.subject_label)), esc(names), graph))
    return ('<section class="panel"><h5>Possible pathways</h5><p class="warn">Each step is separate evidence, '
            'mostly from different papers. Not one tested chain.</p>%s%s</section>' % (''.join(chains), graph))


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s[1:2].islower() else s


def card_name(f: Finding, subject: bool) -> str:
    """"Fertilization at planting → seedling growth & size"; the direction chip says which way."""
    if f.reference or not subject:
        return esc(f.outcome_label)
    return ('%s <span class="arrow" aria-hidden="true">→</span><span class="sr-only">, effect on</span> %s'
            % (esc(f.subject_label), esc(_lower_first(f.outcome_label))))


def finding_card(data: SiteData, f: Finding, sources: List[SourcePage], *, subject: bool = True,
                 tag: str = '', level: int = 3, extra: str = '', links: str = '',
                 quotes_shown: int = QUOTES_IN_CARD, compact: bool = False, open_: bool = False,
                 track: bool = False) -> str:
    """One finding. Closed it is one line: direction, name, certainty, study split, Details.
    Open it shows panels: why that certainty, sources (quotes first), Q1 pathways."""
    base = '%s/%s' % (f.question, f.slug)
    cw = CERT_WORD[f.certainty]
    checks = rationale_checks(f.certainty_rationale)
    reason = headline_reason(checks)
    reason_html = (' · <span class="reason"><span class="mk">%s</span> %s</span>' % (esc(reason[0]), esc(reason[1]))
                   if reason else '')
    summary = ('<span class="fchip">%s</span><h%d class="fhead">%s%s</h%d>'
               '<span class="fmore" aria-hidden="true">Details</span><span class="fmeta">'
               '<span class="fcert"><span class="bars b%d" aria-hidden="true"></span> %s%s</span>'
               '<span class="fsplit">%s %s</span></span>'
               % (chip(f.direction, base + '/direction'), level, card_name(f, subject), tag, level,
                  0 if track else CERT_BARS.get(f.certainty, 0), span(base + '/certainty', certainty_text(f.certainty)), reason_html,
                  split_bar(f), split_short(f, base)))
    if track:
        summary = summary.replace('<span class="bars b0" aria-hidden="true"></span> ', '')
    # panel 1: why that certainty, as a checklist; the exact rule text one click further
    raw = esc(f.certainty_rationale) if f.certainty_rationale else 'The pack gives no rationale for this grade.'
    score = rationale_score(f.certainty_rationale)
    pts = []
    if score and len(checks) == 1 + len(score[1]):
        pts = ['start %d' % score[0]] + ['%+d' % d if d else '' for d in score[1]]
        pts = [p.replace('-', '−') for p in pts]
    items = ''.join('<li><span class="mk" aria-hidden="true">%s</span><span class="sr-only">%s: </span>'
                    '<span class="t">%s</span><span class="pts">%s</span></li>'
                    % (esc(mk), {'✓': 'For', '✗': 'Against'}.get(mk, 'Note'), esc(t), esc(pts[i] if pts else ''))
                    for i, (mk, t) in enumerate(checks))
    if pts:
        items += ('<li class="total"><span class="mk" aria-hidden="true">=</span><span class="t">%s%s</span>'
                  '<span class="pts">%d</span></li>'
                  % (esc(LEVEL_WORD[score[2]]), (' <span class="cap">(%s)</span>' % esc(score[3])) if score[3] else '',
                     score[2]))
    if compact:
        # Q3 repeats this 123 times: the checklist is built in the browser from the rule text
        # below (CHECKS_JS); without script the exact rule text is still there.
        items = ''
    why = ('<section class="panel"><h5>Why “%s”?%s</h5>%s'
           # the pack's exact rationale must be on the page (README; both checkers): kept, but quiet
           '<details class="raw"><summary>exact rule text</summary><p class="rule">%s</p></details></section>'
           % (esc(cw), '' if compact else HELP_BTN,
              '<ul class="checks" data-rule></ul>' if compact else (('<ul class="checks">%s</ul>' % items) if items else ''),
              raw))
    lt = level_track(f.certainty_rationale) if track else ''
    if lt:
        # Q1: a one-line explanation, then the steps on the four levels (a dot per step)
        why = ('<section class="panel why-track"><h5>Why “%s”?%s</h5><p class="why-intro">Certainty is how much '
               'you can trust this result. It starts at the level of the best kind of study, then moves up or down '
               'one level for each check below.</p>%s'
               '<details class="raw"><summary>exact rule text</summary><p class="rule">%s</p></details></section>'
               % (esc(cw), LEVELS_BTN, lt, raw))
    # panel 2: sources, quotes first
    finding_sources(sources, f, f.question)  # writes sources-<slug>.html
    groups = paper_groups(f.quotes)
    quotes = ''.join(card_quote(qs[0]) for qs in groups[:quotes_shown])
    all_link = ('<a class="srclink" href="sources-%s.html">All %d %s, %s %s →</a>'
                % (esc(f.slug), len(groups), plural(len(groups), 'paper', 'papers'),
                   span(base + '/claims', f.claims), plural(f.claims, 'quote', 'quotes')))
    src = '<section class="panel"><h5>Sources</h5>%s<p class="go">%s</p></section>' % (quotes, all_link)
    pw = pathways(data, f) if f.question in data.graphs else ''
    more = extra + (('<p class="flinks">%s</p>' % links) if links and not pw else '')
    return ('<article class="fcard%s fdir-%s" id="f-%s"><details class="fd"%s><summary>%s</summary>'
            '<div class="panels">%s%s%s</div>%s</details></article>'
            % ((' fref' if f.reference else '') + (' track' if lt else ''), esc(f.direction.replace('_', '-')), esc(f.slug), ' open' if open_ else '', summary, why, src, pw, more))


CHART_KEY = [('increase', 'Increases'), ('decrease', 'Decreases'), ('mixed', 'Mixed: the studies disagree'),
             ('no_effect', 'No effect'), ('unclear', 'Unclear')]


# Highlight bars by outcome and factor: the others fade (they stay in place, so nothing seems to vanish).
CHART_FILTER_JS = ('<script>(function(){var f=document.querySelector(".cc-filter");if(!f)return;f.hidden=false;'
                   'var o="",bs=f.querySelectorAll("[data-o]"),sel=document.getElementById("cc-factor"),'
                   'n=f.querySelector(".cc-count");function go(){var fa=sel.value,t=0,k=0;'
                   'document.querySelectorAll(".cc-grp").forEach(function(g){var any=false;'
                   'g.querySelectorAll("li[data-outcome]").forEach(function(r){t++;var m=(!o||r.dataset.outcome===o)'
                   '&&(!fa||g.dataset.factor===fa);r.classList.toggle("cc-dim",!m);if(m){k++;any=true}});'
                   'g.classList.toggle("cc-dim-g",!any)});n.textContent=(o||fa)?"Highlighting "+k+" of "+t+" bars":""}'
                   'bs.forEach(function(b){b.addEventListener("click",function(){o=b.dataset.o;bs.forEach(function(x)'
                   '{x.setAttribute("aria-pressed",x===b?"true":"false")});go()})});sel.addEventListener("change",go)'
                   '})();</script>')


# chart title per question (our wording); other EFFECTS questions get the general one
CHART_TITLE = {'q1': 'Effect of each factor on seedling survival and growth, by certainty of evidence'}


def certainty_chart(q: Question, popups: Dict[str, str]) -> str:
    """Q1 main view: one bar per finding (factor x outcome). Bar length = the pack's certainty
    grade (Very low..High), colour + symbol + word = direction, the number = studies. A gap is an
    empty dashed box, never a bar. Each row is a button that opens its finding's full card in a
    popup (why that grade, the quoted sources), the same popup as the Q2 timeline."""
    subjects, outcomes, cells = [], [], {}
    for f in q.findings:
        if f.subject_id not in [x[0] for x in subjects]:
            subjects.append((f.subject_id, f.subject_label))
        if f.outcome_id not in [x[0] for x in outcomes]:
            outcomes.append((f.outcome_id, f.outcome_label))
        cells[(f.subject_id, f.outcome_id)] = f
    for g in q.gaps:
        if g.subject_id not in [x[0] for x in subjects]:
            subjects.append((g.subject_id, g.subject_label))
        if g.outcome_id not in [x[0] for x in outcomes]:
            outcomes.append((g.outcome_id, g.outcome_label))
        cells[(g.subject_id, g.outcome_id)] = g

    def strength(sid: str) -> Tuple[int, int]:
        fs = [c for (s_, _), c in cells.items() if s_ == sid and isinstance(c, Finding)]
        return (min((CERT_ORDER.index(f.certainty) for f in fs), default=9), -sum(f.studies for f in fs))
    subjects.sort(key=lambda x: strength(x[0]))

    groups = []
    for sid, slbl in subjects:
        rows = []
        for oid, olbl in outcomes:
            c = cells.get((sid, oid))
            if c is None:
                continue
            li = '<li data-outcome="%s">' % esc(slug(oid))
            if isinstance(c, Gap):
                rows.append(li + '<a class="cc-row cc-gap" href="#gap-%s"><span class="sr-only">%s, </span><span class="cc-out">%s</span>'
                            '<span class="cc-dir"><span class="chip gapchip"><span aria-hidden="true">?</span> '
                            'Not studied</span></span><span class="cc-track"><span class="cc-none">No study tested '
                            'this: a gap, not a result</span></span><span class="cc-q" aria-hidden="true">?</span></a></li>'
                            % (esc(c.slug), esc(slbl), esc(olbl)))
                continue
            b = '%s/%s' % (c.question, c.slug)
            rows.append(li + '<button type="button" class="cc-row" popovertarget="pop-%s">'
                        '<span class="sr-only">Details: %s, </span><span class="cc-out">%s</span><span class="cc-dir">%s</span>'
                        '<span class="cc-track"><span class="cc-bar cb%d bar-%s"><span class="cc-lab">%s'
                        '<span class="sr-only"> certainty</span> · %s %s</span></span></span>'
                        '<span class="cc-q" aria-hidden="true">?</span></button></li>'
                        % (esc(c.slug), esc(slbl), esc(olbl), chip(c.direction, b + '/direction'),
                           CERT_BARS.get(c.certainty, 0), esc(c.direction.replace('_', '-')),
                           span(b + '/certainty', CERT_WORD[c.certainty]),
                           span(b + '/studies', c.studies), plural(c.studies, 'study', 'studies')))
        groups.append('<li class="cc-grp" data-factor="%s"><h3>%s</h3><ul>%s</ul></li>'
                      % (esc(slug(sid)), esc(slbl), ''.join(rows)))

    present = {f.direction for f in q.findings}
    key = ''.join('<li><span class="sw bar-%s" aria-hidden="true"></span><span aria-hidden="true">%s</span> %s</li>'
                  % (esc(d.replace('_', '-')), CHIP[d][0], esc(w)) for d, w in CHART_KEY if d in present)
    if q.gaps:
        key += ('<li><span class="sw sw-gap" aria-hidden="true"></span>Not studied: no study tested it '
                '(not a negative result)</li>')
    levels = ['very_low', 'low', 'moderate', 'high']
    unused = [CERT_WORD[c] for c in levels if c not in {f.certainty for f in q.findings}]
    unused_note = (' No finding here is graded %s.' % ' or '.join(unused)) if unused else ''
    ticks = ''.join('<span>%s</span>' % esc(CERT_WORD[c]) for c in levels)
    outs = '<p class="cc-outs"><strong>Outcomes:</strong> %s</p>' % ' · '.join(esc(o) for _, o in outcomes)
    # highlight controls: hidden until the script runs, so without script nothing is broken
    obtn = ''.join('<button type="button" data-o="%s" aria-pressed="%s">%s</button>'
                   % (v, 'true' if v == '' else 'false', esc(lbl))
                   for v, lbl in [('', 'Both')] + [(slug(oid), olbl) for oid, olbl in outcomes])
    fopt = ''.join('<option value="%s">%s</option>' % (esc(slug(sid)), esc(slbl)) for sid, slbl in subjects)
    filt = ('<div class="cc-filter" hidden><div class="cc-f-o" role="group" aria-label="Highlight an outcome">'
            '<span class="cc-f-l" aria-hidden="true">Outcome:</span>%s</div><div class="cc-f-f"><label for="cc-factor">'
            'Factor:</label> <select id="cc-factor"><option value="">All factors</option>%s</select></div>'
            '<p class="cc-count" role="status"></p></div>' % (obtn, fopt))
    title = CHART_TITLE.get(q.qid, 'Effect of each factor on each outcome, by certainty of evidence')
    return ('<section class="cchart-sec" aria-labelledby="glance"><h2 id="glance">%s %s</h2>%s'
            '<p class="cc-read"><strong>How to read:</strong> each bar is one finding, a factor\'s effect on one '
            'outcome. Bar length is the certainty of the evidence (Very low, Low, Moderate, High), not the size of '
            'the effect. Colour, symbol and word give the direction; the number is how many studies.%s '
            'Select a bar for the certainty rationale and the quoted sources.</p>'
            '<ul class="cc-key" aria-label="Legend">%s</ul>%s'
            '<div class="cchart"><div class="cc-axis" aria-hidden="true"><span class="cc-out"></span>'
            '<span class="cc-dir">Direction</span><span class="cc-ticks">%s</span><span class="cc-q"></span></div>'
            '<ul class="cc-grps">%s</ul><p class="cc-xlab" aria-hidden="true">Certainty of evidence →</p></div>'
            '</section>%s%s'
            % (esc(title), LEVELS_BTN, outs, unused_note, key, filt, ticks, ''.join(groups), CHART_FILTER_JS, ''.join(popups.values())))


def limits_box(prefix: str, limitations: Iterable[str], rule: Optional[str],
               how_built: Optional[str], heading: str = 'Read this first') -> str:
    """The pack's limitations, word for word. A closed one-liner, so the page stays clean,
    but always on the question page itself (README; both checkers)."""
    lims = list(limitations)
    items = ''.join('<li>%s</li>' % span('%s/limitations/%d' % (prefix, i), t) for i, t in enumerate(lims))
    # how_built (the data team's selection rules) is on the Method page, under "Where the data comes from"
    return ('<details class="limits" id="limits-%s"><summary><strong>%d %s this answer can\'t tell you</strong>'
            '<span class="cnt">read before acting on it</span></summary><p class="intro">In the data team\'s own '
            'words: how the studies were matched and grouped, and what that means for the answer above. '
            '<a href="method.html#data">How each answer was built →</a></p><ul>%s</ul></details>'
            % (esc(prefix), len(lims), plural(len(lims), 'thing', 'things'), items))


def finding_cells(f: Finding) -> Tuple[str, str, str]:
    base = '%s/%s' % (f.question, f.slug)
    return (direction_badge(f.direction, base + '/direction'),
            certainty_badge(f.certainty, f.certainty_rationale, f.label, base),
            counts(base, f.studies, f.claims))


def table(caption: str, headers: List[str], body: str, cls: str = 'findings') -> str:
    th = ''.join('<th scope="col">%s</th>' % esc(h) for h in headers)
    return ('<div class="table-wrap"><table class="%s"><caption>%s</caption><thead><tr>%s</tr></thead>'
            '<tbody>%s</tbody></table></div>' % (cls, esc(caption), th, body))


# --------------------------------------------------------------- page shell

SHELL = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<meta name="description" content="$description">
<link rel="stylesheet" href="static/style.css">
<link rel="icon" href="static/favicon.svg" type="image/svg+xml">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
$layout
<footer class="site"><p>Data: Evidence Jam 2026 Lane 3 answer pack (rule <code>$rule</code>), built from the
Lane 2 CAMO causal graph. Every direction, certainty and count on this site is read from the pack's
answer files. Site code: MIT licence. Built $date.</p></footer>
$script</body>
</html>
""")


def question_name(q: Question) -> str:
    stem = q.file[:-5].split('_', 1)
    rest = stem[1].replace('_', ' ') if len(stem) > 1 else ''
    return rest[:1].upper() + rest[1:]


def nav_items(data: SiteData) -> List[Tuple[str, str]]:
    """Top nav (home page): Home, each question numbered, the graph, Method."""
    items = [('index.html', 'Home')]
    for n, (qid, q) in enumerate(data.questions.items(), 1):
        items.append(('%s.html' % qid, '%02d %s' % (n, question_name(q))))
        if qid in data.graphs:
            items.append((graph_file(qid), 'Graph'))
    items.append(('method.html', 'Method'))
    return items


def side_nav(data: SiteData, filename: str, jumps: Optional[List[Tuple[str, str]]]) -> str:
    """Left sidebar: 01 / 02 / 03 (with Graph under 01), then Method and Home. The open page
    lists its sections as jump links underneath it."""
    def item(href: str, num: str, label: str, cls: str = '') -> str:
        cur = href == filename
        sub = ''
        if cur and jumps:
            sub = '<ul class="jumps">%s</ul>' % ''.join(
                '<li><a href="%s">%s</a></li>' % (esc(h), esc(t)) for h, t in jumps)
        return ('<li class="%s"><a href="%s"%s><span class="n" aria-hidden="true">%s</span> %s</a>%s</li>'
                % (cls, esc(href), ' aria-current="page"' if cur else '', esc(num), esc(label), sub))
    qs = []
    for n, (qid, q) in enumerate(data.questions.items(), 1):
        qs.append(item('%s.html' % qid, '%02d' % n, question_name(q)))
        if qid in data.graphs:
            qs.append(item(graph_file(qid), '↳', '%s graph' % question_name(q), 'sub'))
    more = item('method.html', '?', 'How it works') + item('index.html', '⌂', 'Home')
    return ('<aside class="side"><a class="brand" href="index.html">whimsy<span class="sr-only">: home</span></a>'
            '<nav aria-label="Questions"><ol class="qnav">%s</ol><ul class="qnav more">%s</ul></nav></aside>'
            % (''.join(qs), more))


def build_date() -> str:
    sde = os.environ.get('SOURCE_DATE_EPOCH')
    if sde and sde.isdigit():
        return datetime.datetime.fromtimestamp(int(sde), datetime.timezone.utc).strftime('%Y-%m-%d')
    return datetime.date.today().isoformat()


def page(data: SiteData, filename: str, title: str, description: str, body: str, *,
         side: bool = True, jumps: Optional[List[Tuple[str, str]]] = None,
         script: Optional[str] = None) -> str:
    """Home has a top nav and the big headline; every other page has the left sidebar."""
    main = '<main id="main" tabindex="-1">\n%s\n</main>' % body
    if side:
        layout = '<div class="layout">%s%s</div>' % (side_nav(data, filename, jumps), main)
    else:
        nav = ''.join('<li><a href="%s"%s>%s</a></li>' % (href, ' aria-current="page"' if href == filename else '',
                                                           esc(label)) for href, label in nav_items(data))
        layout = ('<header class="site"><nav aria-label="Main"><ul>%s</ul></nav></header>%s' % (nav, main))
    rule = next((q.rule for q in data.questions.values() if q.rule), 'unknown')
    tag = '<script src="%s" defer></script>\n' % esc(script) if script else ''
    return SHELL.substitute(title=esc(title), description=esc(description), layout=layout,
                            body=body, rule=esc(rule), date=build_date(), script=tag)


# --------------------------------------------------------------- pages

def render_index(data: SiteData, prose: Prose) -> str:
    """Home: big headline, one sentence, the questions as 01 / 02 / 03 rows with their real short
    answers, and a small key for reading the site."""
    rows = []
    for n, (qid, q) in enumerate(data.questions.items(), 1):
        graph = ''
        if qid in data.graphs:
            graph = (' · <a href="%s">See it as a graph<span class="sr-only">: %s</span></a>'
                     % (graph_file(qid), esc(question_name(q))))
        rows.append(
            '<li class="qrow"><span class="n" aria-hidden="true">%02d</span><div>'
            '<h2 id="card-%s"><a href="%s.html">%s</a></h2><p class="q">%s</p>%s'
            '<p class="go"><a href="%s.html">Read the answer →<span class="sr-only"> %s</span></a>%s</p></div></li>'
            % (n, esc(qid), esc(qid), esc(question_name(q)), esc(q.text), short_box(prose.short_answer[qid].html),
               esc(qid), esc(question_name(q)), graph))
    m = data.manifest.get('graph') or {}
    papers = (' from %s papers' % span('manifest/graph/source_documents', m['source_documents'])
              if m.get('source_documents') else '')
    key = ('<section class="key-strip" aria-labelledby="key-h"><h2 id="key-h">How to read this site</h2><ul>'
           '<li><span class="chip dir-increase"><span aria-hidden="true">▲</span> Increases</span> '
           '<span class="chip dir-decrease"><span aria-hidden="true">▼</span> Decreases</span> '
           '<span class="chip dir-mixed"><span aria-hidden="true">⇅</span> Mixed</span> what studies found</li>'
           '<li><span class="bars b3" aria-hidden="true"></span> how sure we can be, 1 to 4</li>'
           '<li><span class="chip gapchip"><span aria-hidden="true">?</span> Not studied</span> nobody here tested it '
           '(not “doesn’t work”)</li>'
           '<li><span class="qmark" aria-hidden="true">“ ”</span> sentences quoted word for word from the papers</li>'
           '</ul><p class="go"><a href="method.html">How it works →</a></p></section>')
    guide = ('<section class="guide" aria-labelledby="guide-h"><h2 id="guide-h">How to use this site</h2><ol>'
             '<li><strong>Pick a question</strong> below or in the sidebar.</li>'
             '<li><strong>Read the short answer.</strong> The best-supported findings in a line or two, and how '
             'sure we can be of them.</li>'
             '<li><strong>Scan “At a glance”.</strong> Every factor, which way it pushes the outcome, how sure '
             'we can be (<span class="bars b3" aria-hidden="true"></span> 1 to 4) and how many studies.</li>'
             '<li><strong>Open a finding</strong> to see why it got that certainty and the sentences quoted '
             'from the papers, with links to each paper.</li>'
             '<li><strong>Read “things this answer can’t tell you”</strong> before acting on it. It says how '
             'the studies were picked and grouped, in the data team’s own words.</li></ol></section>')
    body = ('<h1 class="mega">restoration evidence</h1>'
            '<p class="lead">Plain answers to %s restoration questions%s: what works, how sure we can be, '
            'and where nothing has been studied. Works offline.</p>%s'
            '<h2 class="rows-h">The questions</h2><ol class="qrows">%s</ol>%s'
            % (number_word(len(data.questions)), papers, guide, ''.join(rows), key))
    return page(data, 'index.html', 'Restoration evidence', 'Plain answers to restoration questions, '
                'with certainty, gaps and sources.', body)


def number_word(n: int) -> str:
    return {1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six'}.get(n, str(n))


def short_box(inner: str, sid: str = '') -> str:
    """The short answer, in the cream box. A bullet list stays a list; a sentence gets a <p>."""
    body = inner if inner.lstrip().startswith('<ul') else '<p>%s</p>' % inner
    return ('<div class="short"%s><p class="sa-h"><strong>Short answer</strong></p>%s</div>'
            % (' id="%s"' % sid if sid else '', body))


def fold(sid: str, heading: str, level: int, count: str, inner: str, open_: bool = False) -> str:
    """A section that opens like a dropdown, so a page shows its outline first."""
    return ('<details class="sec" id="%s"%s><summary><h%d>%s</h%d><span class="cnt">%s</span></summary>'
            '<div class="sec-body">%s</div></details>'
            % (esc(sid), ' open' if open_ else '', level, heading, level, esc(count), inner))


def search_template(gaps: List[Gap]) -> Optional[str]:
    """The pack's "searched for" sentence shared by a group of gaps, with the outcome replaced by
    {outcome}, when they all use the same sentence apart from their outcome; else None. Read from
    the pack's own text, so it is said once per group instead of once per gap."""
    if len(gaps) < 2:
        return None
    templates = set()
    for g in gaps:
        templates.add(g.searched_for.replace(g.outcome_label, OUTCOME_SLOT)
                      if g.searched_for.count(g.outcome_label) == 1 else None)
    if len(templates) == 1 and None not in templates:
        return templates.pop()
    return None


OUTCOME_SLOT = '{outcome}'


def not_studied(q: Question) -> str:
    """Gaps, the same compact way on every page: grouped by what was tested, each one
    "? Not studied: <outcome>". Never worded as a negative result."""
    if not q.gaps:
        return ''
    groups: Dict[str, List[Gap]] = {}
    for g in q.gaps:
        groups.setdefault(g.subject_label, []).append(g)
    parts = []
    for subj, gs in groups.items():
        template = search_template(gs)
        note = ''
        if template is not None:
            note = ('<p class="searched" data-template="%s">Searched for and not found: %s.</p>'
                    % (esc(template), esc(template.replace(OUTCOME_SLOT, 'that outcome'))))
        items = ''.join(
            '<li class="gap" id="gap-%s"><strong>Not studied:</strong> %s%s</li>'  # the "?" is drawn by CSS (261 on Q3)
            % (esc(g.slug), esc(g.outcome_label),
               '' if template is not None else ' <span class="searched">Searched for: %s</span>' % esc(g.searched_for))
            for g in gs)
        parts.append('<section class="gapgrp" aria-label="%s"><h3>%s</h3>%s<ul class="gaps">%s</ul></section>'
                     % (esc(subj), esc(subj), note, items))
    return fold('gaps-h', 'Not studied', 2, '%d %s' % (len(q.gaps), plural(len(q.gaps), 'pairing', 'pairings')),
                '<p>Looked for in this body of research and not found. That is not evidence that something '
                'fails: nobody here tested it.</p>%s' % ''.join(parts))


def question_page(data: SiteData, prose: Prose, q: Question, main: str, *,
                  jumps: List[Tuple[str, str]], short: Optional[str] = None, scripts: str = '') -> str:
    """The one template every question page uses, in this order: kicker + h1, short answer,
    limitations, MAIN VIEW, not studied, link to How it works."""
    n = list(data.questions).index(q.qid) + 1
    name = question_name(q)
    body = '<p class="kicker">Question %02d · %s</p><h1>%s</h1>' % (n, esc(name), esc(q.text))
    body += short if short is not None else short_box(prose.short_answer[q.qid].html, 'short')
    body += limits_box(q.qid, q.limitations, q.rule, q.how_built)
    body += main
    body += not_studied(q)
    body += ('<p class="to-method"><a href="method.html">How it works: how certainty is graded, where the data '
             'comes from, and the limits →</a></p>')
    jumps = [('#short', 'Short answer')] + jumps + ([('#gaps-h', 'Not studied')] if q.gaps else [])
    return page(data, '%s.html' % q.qid, 'Q%d · %s' % (n, name), q.text,
                body + GRADING_POPOVER + OPEN_TARGET_JS + scripts, jumps=jumps)


def by_strength(fs: Iterable[Finding]) -> List[Finding]:
    return sorted(fs, key=lambda f: (CERT_ORDER.index(f.certainty), -f.studies))


def render_effects(data: SiteData, prose: Prose, q: Question, sources: List[SourcePage]) -> str:
    """EFFECTS layout (Q1 today). Main view: the certainty chart (each row opens its finding's card
    in a popup), combined treatments, graph link."""
    def popup(f: Finding) -> str:
        graph = ''
        if f.slug in data.graph_join:
            graph = ('<a href="%s#e-%s">On the graph<span class="sr-only">: %s</span></a>'
                     % (graph_file(q.qid), esc(slug(data.graph_join[f.slug])), esc(f.label)))
        return ('<div popover id="pop-%s" class="pop fpop" role="dialog" aria-label="%s">'
                '<button type="button" class="pop-x" popovertarget="pop-%s" popovertargetaction="hide">'
                '<span aria-hidden="true">×</span><span class="sr-only">Close</span></button>%s</div>'
                % (esc(f.slug), esc(f.label), esc(f.slug),
                   finding_card(data, f, sources, level=3, links=graph, open_=True, track=True)))

    main = certainty_chart(q, {f.slug: popup(f) for f in by_strength(q.findings)}) + LEVELS_POPOVER
    main += interactions_section(data, q)
    if q.qid in data.graphs:
        main += '<p class="graph-link"><a href="%s">See this answer as a graph →</a></p>' % graph_file(q.qid)
    jumps = [('#glance', 'Certainty chart')]
    if q.extra.get('interactions'):
        jumps.append(('#ix-h', 'Combined treatments'))
    return question_page(data, prose, q, main, jumps=jumps)


def interactions_section(data: SiteData, q: Question) -> str:
    inter = q.extra.get('interactions') or []
    if not inter:
        return ''
    g = data.graphs.get(q.qid)
    rows = []
    for i, it in enumerate(inter):
        eid = it['edge_id']
        quote = q.evidence[eid]
        shown = 'Not drawn on the graph.'
        if g is not None:
            aside = [s for s in g.set_aside if s.get('edge_id') == eid]
            if aside:
                shown = 'Set aside, not drawn: %s.' % esc(aside[0].get('why', ''))
            else:
                for e in g.edges:
                    if eid in (e.get('edge_ids') or ()):
                        src = g.node(e['source'])
                        if e.get('kind') == 'moderation':
                            kind = 'a moderation edge (an arrow pointing at another arrow)'
                        elif src.get('kind') == 'combination':
                            kind = 'a combination node (two treatments applied together)'
                        else:
                            kind = 'an edge'
                        shown = 'Shown as %s: <a href="%s#e-%s">%s</a>.' % (
                            kind, graph_file(q.qid), esc(slug(e['id'])), esc(edge_title(g, e)))
                        break
        rows.append('<tr id="ix-%d"><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            i + 1, evidence_box(quote, 1, 'ev-ix-%d' % (i + 1), q.qid, open_=True),
            direction_badge(it['direction'], '%s/interactions/%d/direction' % (q.qid, i)), shown))
    return fold('ix-h', 'Combined treatments', 2, '%d %s' % (len(rows), plural(len(rows), 'claim', 'claims')),
                '<p>These claims are about two treatments together, or one treatment changing another\'s '
                'effect. They are listed one by one, not pooled into the findings above.</p>%s'
                % table('Claims about combined treatments', ['Claim', 'Direction', 'Shown on the graph as'],
                        ''.join(rows), 'interactions'))


# --------------------------------------------------------------- Q2 timeline
# "When were these marshes measured?": one row per comparison finding, a bar for each marsh age
# in its time_points. It is NOT a recovery curve: no study reports a time to reach the
# reference (time_to_reference is null), and the bar colour is the overall result.

TL_WORD = {'below_reference': ('◀', 'Behind'), 'above_reference': ('▶', 'Ahead'),
           'comparable': ('=', 'Matches'), 'mixed': ('⇅', 'Mixed'), 'unclear': ('?', 'Unclear'),
           'increase': ('▲', 'Increase'), 'decrease': ('▼', 'Decrease'), 'no_effect': ('–', 'No effect')}
TL_MAX, TL_STEP = 30, 5                      # axis: 0 to 30, a tick every 5
TL_X0, TL_PX = 400, 16                       # where the axis starts, px per year (fits the page column)
TL_ROW, TL_TOP, TL_GROUP = 76, 60, 44        # row height, space for the axis, a group heading
TL_BTN = 44                                  # the "?" column on the right
AGE_RANGE = re.compile(r'^\s*(\d+)\s*[-–]\s*(\d+)\s*years?\s*$')
AGE_ONE = re.compile(r'^\s*(\d+)\s*years?\s*$')


def f1(v: float) -> str:
    s_ = '%.1f' % v
    return s_[:-2] if s_.endswith('.0') else s_


def parse_age(t: str) -> Optional[Tuple[int, int]]:
    """'6-10 years' -> (6, 10); '9 years' -> (9, 9); anything else -> None."""
    m = AGE_RANGE.match(t)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = AGE_ONE.match(t)
    if m:
        return int(m.group(1)), int(m.group(1))
    return None


def timeline_chart(q: Question, popups: Dict[str, str]) -> str:
    """The Q2 main view: one row per finding (compared with natural marshes, then change with age).
    A row is short; its "?" (or a click anywhere on it) opens a popup with the finding's full card.
    Static SVG, values in data-check spans; the same data follows as a table."""
    rank = {c: i for i, c in enumerate(CERT_ORDER)}
    groups = [('', sorted(q.findings, key=lambda f: (not f.raw.get('lags'), rank.get(f.certainty, 9))))]
    if q.trends:
        groups.append(('As marshes age', list(q.trends)))
    allf = [f for _, fs in groups for f in fs]
    if not allf or not any(f.raw.get('time_points') for f in allf):
        return ''
    qid = q.qid
    x = lambda yr: TL_X0 + min(yr, TL_MAX) * TL_PX
    width = x(TL_MAX) + 24 + TL_BTN
    parts, buttons, y = [], [], TL_TOP
    parts.append('<defs><pattern id="tl-hatch" width="8" height="8" patternUnits="userSpaceOnUse" '
                 'patternTransform="rotate(45)"><rect width="8" height="8" class="tl-hatch-bg"/>'
                 '<line x1="0" y1="0" x2="0" y2="8" class="tl-hatch-line"/></pattern></defs>')
    # axis title first (so no tick number runs into it), then tick numbers
    parts.append('<text class="tl-axis-title" x="%d" y="18">Marsh age when measured (years)</text>' % TL_X0)
    for yr in range(0, TL_MAX + 1, TL_STEP):
        parts.append('<text class="tl-tick" x="%d" y="%d" text-anchor="middle">%d</text>' % (x(yr), TL_TOP - 18, yr))
    rows_svg = []
    for title, fs in groups:
        if title:
            rows_svg.append('<text class="tl-group" x="0" y="%d">%s</text>' % (y + 30, esc(title)))
            y += TL_GROUP
        for f in fs:
            base = '%s/%s' % (qid, f.slug)
            sym, word = TL_WORD.get(f.direction, ('', words(f.direction)))
            lag = ' <tspan class="tl-lag">· lags</tspan>' if f.raw.get('lags') else ''
            row = ['<g class="tl-row tl-%s"><line class="tl-sep" x1="0" y1="%d" x2="%d" y2="%d"/>'
                   '<text class="tl-name" x="0" y="%d">%s%s</text>'
                   '<text class="tl-meta" x="0" y="%d"><tspan class="tl-sym" aria-hidden="true">%s</tspan> '
                   '<tspan data-check="%s/direction">%s</tspan> · <tspan data-check="%s/certainty">%s</tspan> · '
                   '<tspan data-check="%s/studies">%d</tspan> %s</text>'
                   % (esc(f.direction.replace('_', '-')), y + TL_ROW, width, y + TL_ROW, y + 30,
                      esc(f.outcome_label), lag, y + 54, sym, esc(base), esc(word), esc(base),
                      esc(certainty_text(f.certainty)), esc(base), f.studies, plural(f.studies, 'study', 'studies'))]
            ages = [a for a in (parse_age(t) for t in f.raw.get('time_points') or []) if a is not None]
            if ages:
                for a, b in ages:
                    x1, x2 = x(a), x(b)
                    if x2 - x1 < 8:
                        x1, x2 = (x1 + x2) / 2 - 4, (x1 + x2) / 2 + 4
                    row.append('<rect class="tl-bar" x="%s" y="%d" width="%s" height="28" rx="4"/>'
                               % (f1(x1), y + 24, f1(x2 - x1)))
            else:
                row.append('<rect class="tl-none" x="%d" y="%d" width="%d" height="28" fill="url(#tl-hatch)"/>'
                           '<text class="tl-none-t" x="%d" y="%d" text-anchor="middle">age not reported</text>'
                           % (x(0), y + 24, x(TL_MAX) - x(0), (x(0) + x(TL_MAX)) // 2, y + 43))
            row.append('</g>')
            rows_svg.append(''.join(row))
            # the whole row is a button (over the drawing); its "?" sits at the right
            buttons.append('<button type="button" class="tl-open" popovertarget="pop-%s" '
                           'style="top:%dpx;height:%dpx;width:%dpx">'
                           '<span class="sr-only">Details: %s</span><span class="tl-q" aria-hidden="true">?</span></button>'
                           % (esc(f.slug), y, TL_ROW, width, esc(f.label)))
            y += TL_ROW
    height = y + 8
    grid = ''.join('<line class="tl-grid" x1="%d" y1="%d" x2="%d" y2="%d"/>' % (x(yr), TL_TOP - 10, x(yr), height - 8)
                   for yr in range(0, TL_MAX + 1, TL_STEP))
    n_aged = sum(1 for f in allf if f.raw.get('time_points'))
    summary = ('Ages of the marshes studied for %d findings; %d of them report marsh ages. Each row shows the '
               'overall result. Select a row for its details. The table below has the same data.' % (len(allf), n_aged))
    svg = ('<svg class="tl" width="%d" height="%d" viewBox="0 0 %d %d" role="group" aria-label="%s">%s%s%s</svg>'
           % (width, height, width, height, esc(summary), ''.join(parts), grid, ''.join(rows_svg)))
    rows = []
    for f in allf:
        base = '%s/%s' % (qid, f.slug)
        sym, word = TL_WORD.get(f.direction, ('', words(f.direction)))
        tps = f.raw.get('time_points') or []
        ages = (', '.join(span('%s/time_points/%d' % (base, i), t) for i, t in enumerate(tps))
                if tps else '<span class="muted">not reported</span>')
        rows.append('<tr><th scope="row">%s%s</th><td><span aria-hidden="true">%s</span> %s</td>'
                    '<td>%s</td><td>%s</td><td>%s</td></tr>'
                    % (esc(f.outcome_label), ' (lags)' if f.raw.get('lags') else
                       (' (as marshes age)' if f.kind == 'trend' else ''), sym,
                       span(base + '/direction', word), span(base + '/certainty', CERT_WORD[f.certainty]),
                       span(base + '/studies', f.studies), ages))
    tbl = table('The chart as a table: each finding, its overall result and the marsh ages studied',
                ['Outcome', 'Result', 'Certainty', 'Studies', 'Ages measured'], ''.join(rows), 'tl-table')
    pops = ''.join(popups[f.slug] for f in allf)
    return ('<h2 id="timeline">When were these marshes measured?</h2>'
            '<p class="note">Select a row (or its <span class="tl-q-inline" aria-hidden="true">?</span>) for why it has '
            'that certainty and the quoted sources.</p>'
            '<div class="tl-wrap" role="region" aria-label="Marsh ages chart" tabindex="0">%s%s</div>'
            '<p class="tl-cap">Bars show the marsh ages studies looked at. The result (Behind / Ahead) is overall, '
            'not at each age. No study followed a marsh until it matched a natural one.</p>'
            '<details class="tl-tbl"><summary>The same data as a table</summary>%s</details>%s'
            % (svg, ''.join(buttons), tbl, pops))


def render_comparison(data: SiteData, prose: Prose, q: Question, sources: List[SourcePage]) -> str:
    """COMPARISON layout (Q2 today). Main view: what lags behind, compared with natural marshes, change as marshes age.
    The "how long?" answer is the short answer itself, so it comes first and is said once."""
    sa = q.extra.get('short_answer') or {}
    note = sa.get('time_to_reference_note') or ''
    ttr = sa.get('time_to_reference')
    if ttr is not None:
        lead = ('<p><strong>Time to reach the reference:</strong> %s</p><p>%s</p>'
                % (span('%s/short_answer/time_to_reference' % q.qid, ttr), span('%s/short_answer/time_to_reference_note' % q.qid, note)))
    else:
        lead = ('<p><strong>How long? This body of research cannot say.</strong></p><p>%s</p>'
                % span('%s/short_answer/time_to_reference_note' % q.qid, note))
    if prose.short_answer[q.qid].text != note:
        lead += '<p>%s</p>' % prose.short_answer[q.qid].html
    short = ('<div class="short callout" role="note" aria-label="How long" id="short"><p class="sa-h">'
             '<strong>Short answer</strong></p>%s</div>' % lead)

    def when(f: Finding) -> str:
        tps = f.raw.get('time_points') or []
        if not tps:
            return '<span class="muted">No marsh age given</span>'
        return '<ul class="when">%s</ul>' % ''.join(
            '<li>%s</li>' % span('%s/%s/time_points/%d' % (q.qid, f.slug, i), t) for i, t in enumerate(tps))

    def cards(fs: Iterable[Finding]) -> str:
        out = []
        for f in fs:
            tag = ' <span class="lags">Lags</span>' if f.raw.get('lags') else ''
            extra = '<div class="when-wrap"><span class="mlabel">When measured</span> %s</div>' % when(f)
            out.append(finding_card(data, f, sources, tag=tag, extra=extra))
        return '<div class="cards">%s</div>' % ''.join(out)

    def popup(f: Finding) -> str:
        tag = ' <span class="lags">Lags</span>' if f.raw.get('lags') else ''
        extra = '<div class="when-wrap"><span class="mlabel">When measured</span> %s</div>' % when(f)
        return ('<div popover id="pop-%s" class="pop fpop" role="dialog" aria-label="%s">'
                '<button type="button" class="pop-x" popovertarget="pop-%s" popovertargetaction="hide">'
                '<span aria-hidden="true">×</span><span class="sr-only">Close</span></button>%s</div>'
                % (esc(f.slug), esc(f.label), esc(f.slug),
                   finding_card(data, f, sources, tag=tag, extra=extra, open_=True)))

    popups = {f.slug: popup(f) for f in q.all_findings()}
    chart = timeline_chart(q, popups)
    if chart:
        main, jumps = chart, [('#timeline', 'When measured')]
    else:  # no ages in the data: cards as on any other page
        main = '<h2 id="compare">Findings</h2>' + cards(q.findings) + (cards(q.trends) if q.trends else '')
        jumps = [('#compare', 'Findings')]
    return question_page(data, prose, q, main, jumps=jumps, short=short)


def q3_cell_id(subject_id: str, outcome_id: str) -> str:
    return 'c-%s--%s-detail' % (slug(subject_id), slug(outcome_id))


OUTCOME_SLOT = '{outcome}'


def render_gapmap(data: SiteData, prose: Prose, q: Question, sources: List[SourcePage]) -> str:
    """GAPMAP layout (Q3 today). Main view: the gap map (sticky names), the ten most studied, then every studied combination
    grouped by intervention, closed; a map cell opens its card. Gaps are in the shared Not studied."""
    grid = data.grids[q.qid]
    qid = q.qid
    s = q.extra['summary']
    short = short_box('%s of %s combinations have been studied; %s of those by a single study. %s'
                      % (span('%s/summary/filled' % qid, s['filled']), span('%s/summary/cells' % qid, s['cells']),
                         span('%s/summary/thin' % qid, s['thin']), prose.short_answer[qid].html), 'short')
    main = ('<h2 id="map">Gap map %s</h2><dl class="key"><div><dt><span class="swatch empty" aria-hidden="true">–</span>'
            ' Not studied</dt><dd>No study in this body of research tested the pairing. Not a negative '
            'result.</dd></div><div><dt><span class="swatch d-thin" aria-hidden="true"></span> thin</dt>'
            '<dd>1 study</dd></div><div><dt><span class="swatch d-some" aria-hidden="true"></span> some</dt>'
            '<dd>2–3 studies</dd></div><div><dt><span class="swatch d-dense" aria-hidden="true"></span> '
            'dense</dt><dd>4 or more studies</dd></div></dl>'
            '<p class="note">Each filled cell shows its number of studies and density word. Study counts '
            'measure research effort, not effect size. Select a cell to open its finding. Scroll the map '
            'sideways for more outcomes →</p>' % HELP_BTN)
    head = ''.join('<th scope="col"><span>%s</span></th>' % esc(lbl) for _, lbl in grid['cols'])
    trs = []
    for rid, rlbl in grid['rows']:
        tds = []
        for cid, clbl in grid['cols']:
            item = grid['cells'][(rid, cid)]
            if isinstance(item, Gap):
                tds.append('<td class="empty" aria-label="Not studied" title="Not studied: %s">–</td>' % esc(item.label))
            else:
                dens = item.raw.get('density', '')
                tds.append('<td class="d-%s"><a href="#%s">%s <span class="sr-only">%s, </span>%s</a></td>'
                           % (esc(dens), q3_cell_id(rid, cid), span('%s/%s/studies' % (qid, item.slug), item.studies),
                              esc(plural(item.studies, 'study', 'studies')), esc(dens)))
        trs.append('<tr><th scope="row">%s</th>%s</tr>' % (esc(rlbl), ''.join(tds)))
    main += ('<div class="grid-wrap" role="region" aria-label="Gap map" tabindex="0"><table class="gapmap">'
             '<caption>Interventions (rows) by outcomes (columns): number of studies in each '
             'combination</caption><thead><tr><td></td>%s</tr></thead><tbody>%s</tbody></table></div>'
             % (head, ''.join(trs)))
    by_id = {f.id: f for f in q.findings}
    dense = []
    for fid in s.get('densest') or []:
        f = by_id[fid]
        d, c, n = finding_cells(f)
        dense.append('<li><a href="#%s">%s</a>: %s · %s · %s</li>' % (
            q3_cell_id(f.subject_id, f.outcome_id), esc(f.subject_label + ' × ' + f.outcome_label), d,
            span('%s/%s/certainty' % (qid, f.slug), certainty_text(f.certainty)), n))
    main += ('<h2 id="densest">Where the evidence is densest</h2><p>The pack\'s ten most-studied combinations, in its '
             'order.</p><ol class="densest">%s</ol>' % ''.join(dense))
    main += '<h2 id="every">Every studied combination</h2>'
    for rid, rlbl in grid['rows']:
        items = []
        for cid, clbl in grid['cols']:
            item = grid['cells'][(rid, cid)]
            if isinstance(item, Gap):
                continue
            dens = '<p class="density">Evidence: <strong>%s</strong></p>' % esc(item.raw.get('density', ''))
            items.append('<li id="%s">%s</li>' % (q3_cell_id(rid, cid), finding_card(
                data, item, sources, subject=False, level=4, extra=dens, quotes_shown=0, compact=True)))
        if items:
            main += fold('r-%s' % slug(rid), esc(rlbl), 3, '%d studied' % len(items),
                         '<ul class="cells">%s</ul>' % ''.join(items))
    jumps = [('#map', 'Gap map'), ('#densest', 'Most studied'), ('#every', 'Every studied combination')]
    return question_page(data, prose, q, main, jumps=jumps, short=short, scripts=CHECKS_JS)


def render_generic(data: SiteData, prose: Prose, q: Question, sources: List[SourcePage]) -> str:
    """Any future qN file gets the same page with no code change: its findings, then its trends."""
    main = '<h2 id="findings">Findings</h2><div class="cards">%s</div>' % ''.join(
        finding_card(data, f, sources) for f in by_strength(q.findings))
    jumps = [('#findings', 'Findings')]
    if q.trends:
        main += '<h2 id="trends">Trends</h2><div class="cards">%s</div>' % ''.join(
            finding_card(data, f, sources) for f in q.trends)
        jumps.append(('#trends', 'Trends'))
    return question_page(data, prose, q, main, jumps=jumps)


# --------------------------------------------------------------- graph page

def edge_title(g: Any, e: Dict[str, Any]) -> str:
    src = g.node(e['source'])['label']
    if e.get('kind') == 'moderation':
        t = g.edge(e['target_edge'])
        return '%s changes the effect of %s → %s' % (src, g.node(t['source'])['label'],
                                                    g.node(t['target'])['label'])
    return '%s → %s' % (src, g.node(e['target'])['label'])


def _swatch(cls: str, word: str) -> str:
    return ('<span><svg width="30" height="12" aria-hidden="true"><line x1="0" y1="6" x2="30" y2="6" '
            'class="lg sw %s"/></svg> %s</span>' % (cls, word))


COLOUR_KEY = ''.join(_swatch(c, w) for c, w in (('up', 'Green: increase ↑'), ('down', 'Red: decrease ↓'),
                                                ('mixed', 'Blue: mixed ⇅'),
                                                ('none', 'Grey: no effect – or unclear ?')))


def _box_row(cls: str, dashed_word: str, meaning: str) -> str:
    return ('<div><dt><svg width="34" height="20" aria-hidden="true"><rect x="1" y="2" width="32" height="16" '
            'rx="3" class="lg-box %s"/></svg> %s</dt><dd>%s</dd></div>' % (cls, dashed_word, meaning))


BOX_KEY = (_box_row('', 'White box', 'Something you do: a planting-stock choice or a site treatment')
           + _box_row('condition', 'Beige box', 'A site or seedling condition the treatments change')
           + _box_row('outcome', 'Pale green box, thick border', 'An outcome: seedling survival or growth')
           + _box_row('combination', 'Dashed box with “+”', 'Two treatments applied together; thin lines '
                      'join it to each treatment'))


def render_graph_page(data: SiteData, qid: str, sources: List[SourcePage]) -> str:
    """The graph page for any question that has a *_graph.json."""
    g = data.graphs[qid]
    q = data.questions.get(qid)
    n = qnum(data, qid)
    gp_ = graph_prefix(qid)
    gfile = graph_file(qid)
    name = question_name(q) if q is not None else qid.upper()
    ends = ('top', 'bottom') if GRAPH_FLOW == 'down' else ('left', 'right')
    body = ('<h1>%s as a causal graph</h1>'
            '<p class="lead">Each arrow is a body of evidence. Select one to read its sources.</p>'
            '<p>%sA table of every arrow follows the graph.</p>'
            % (esc(name), esc(GRAPH_INTRO.get(qid, DEFAULT_GRAPH_INTRO) % ends)))
    body += ('<h2 id="read">How to read the graph</h2><dl class="legend">'
             '<div><dt><span class="lg-sym">↑ ↓ ⇅ – ?</span></dt><dd>Direction, the large symbol on each '
             'label: what happens to the target (increase, decrease, mixed, no effect, unclear). The symbol '
             'carries the meaning; colour repeats it.</dd></div>'
             '<div><dt>Colour of an arrow</dt><dd class="key-list">%s</dd></div>'
             '<div><dt><span class="lg-sym">⇅ ↑5 ↓1</span> On a mixed arrow</dt><dd>How many studies found an '
             'increase (↑) and a decrease (↓), so you can see which way it leans. The other studies found '
             'mixed results or no effect; select the arrow for the full split. “↑0 ↓0” means no study '
             'went clearly either way.</dd></div>'
             '<div><dt><span class="lg-sym">7</span> Number on a label</dt><dd>How many studies the arrow '
             'rests on</dd></div>'
             '<div><dt><svg width="48" height="12" aria-hidden="true"><line x1="0" y1="6" x2="48" y2="6" '
             'class="lg high"/></svg> thick, solid</dt><dd>High certainty</dd></div>'
             '<div><dt><svg width="48" height="12" aria-hidden="true"><line x1="0" y1="6" x2="48" y2="6" '
             'class="lg moderate"/></svg> medium, long dashes</dt><dd>Moderate certainty</dd></div>'
             '<div><dt><svg width="48" height="12" aria-hidden="true"><line x1="0" y1="6" x2="48" y2="6" '
             'class="lg low"/></svg> thin, short dashes</dt><dd>Low certainty</dd></div>'
             '<div><dt><svg width="48" height="12" aria-hidden="true"><line x1="0" y1="6" x2="48" y2="6" '
             'class="lg very_low"/></svg> thinnest, dots</dt><dd>Very low certainty</dd></div>'
             '<div><dt><svg width="48" height="12" aria-hidden="true"><line x1="0" y1="6" x2="48" y2="6" '
             'class="lg gapline"/></svg> faint grey, “no evidence”</dt><dd>A pairing looked for and not '
             'found. Not a negative result.</dd></div>'
             '<div><dt><svg width="48" height="14" aria-hidden="true"><line x1="0" y1="7" x2="38" y2="7" '
             'class="lg very_low"/><circle cx="41" cy="7" r="5" class="lg-ring"/></svg> ends in a circle on an '
             'arrow</dt><dd>Moderation: the source changes how strong the arrow it points at is</dd></div>'
             '%s</dl>' % (COLOUR_KEY, BOX_KEY))
    body += ('<figure class="graph"><!--GRAPH--><figcaption>%s boxes linked by %s arrows, each a body of '
             'evidence, and %s %s looked for and not found. Select an arrow to read its evidence '
             'and sources.</figcaption></figure>'
             % (span(gp_ + '/count/nodes', len(g.nodes)), span(gp_ + '/count/edges', len(g.edges)),
                span(gp_ + '/count/gaps', len(g.gaps)), plural(len(g.gaps), 'pairing', 'pairings')))
    body += ('<p class="callout paths" role="note">A route through a middle box joins separate bodies of '
             'evidence. It is not one tested effect.</p>')
    body += limits_box(gp_, g.limitations, g.raw.get('rule'), g.raw.get('how_built'),
                       heading='Before you trace a path')
    if g.set_aside:
        items = []
        for s in g.set_aside:
            where = ''
            if q is not None:
                for i, it in enumerate(q.extra.get('interactions') or []):
                    if it.get('edge_id') == s.get('edge_id'):
                        where = ' <a href="%s.html#ix-%d">Read the claim</a>.' % (qid, i + 1)
            items.append('<li>%s: %s.%s</li>' % (esc(s.get('edge_id')), esc(s.get('why')), where))
        body += ('<h2>Claim set aside</h2><p>Not drawn on the graph:</p><ul>%s</ul>' % ''.join(items))

    body += '<h2 id="arrows">Evidence behind each arrow</h2>'
    for e in g.edges:
        es = slug(e['id'])
        base = '%s/%s' % (gp_, es)
        title = edge_title(g, e)
        quotes = data.edge_index.get(qid, {}).get(e['id'], ())
        boxes = source_page_link(sources, quotes, fname='sources-e-%s.html' % es, id_prefix='ev-e-' + es,
                                 check_prefix=gp_, label=title, back=gfile + '#e-' + es,
                                 back_text='Back to the graph',
                                 description='The quoted sentences behind one arrow on the Q%d graph.' % n)
        finding = ''
        for fs, eid in data.graph_join.items():
            if eid == e['id']:
                finding = ('<p>This arrow is the finding <a href="%s.html#f-%s">on the Q%d answer page</a>.</p>'
                           % (qid, esc(fs), n))
        meaning = esc(e.get('direction_meaning') or '')
        # .back-graph is left out when graph.js shows this section in its side panel
        body += ('<section class="edge-panel" id="e-%s" aria-labelledby="h-%s"><h3 id="h-%s">%s</h3>'
                 '<div class="badges">%s %s %s</div><p>%s</p>%s%s'
                 '<p class="back-graph"><a href="#edge-%s">Back to the graph</a></p>%s</section>'
                 % (es, es, es, esc(title), direction_badge(e['direction'], base + '/direction'),
                    certainty_badge(e['certainty'], e.get('certainty_rationale'), title, base),
                    counts(base, e['studies'], e['claims']),
                    vote_split(base, e.get('study_directions') or {}, False),
                    '<p>%s</p>' % meaning if meaning else '', finding, es, boxes))
    for gp in g.gaps:
        gs = slug(gp['id'])
        lbl = '%s → %s' % (g.node(gp['source'])['label'], g.node(gp['target'])['label'])
        body += ('<section class="edge-panel gap-panel" id="e-%s" aria-labelledby="h-%s"><h3 id="h-%s">%s</h3>'
                 '<div class="gap" role="note"><strong>Not studied:</strong> no claim in this body of research '
                 'tested this pairing. That is not evidence of no effect. <span class="searched">Searched for: '
                 '%s</span></div><p class="back-graph"><a href="#gapedge-%s">Back to the graph</a></p></section>'
                 % (gs, gs, gs, esc(lbl), esc(gp.get('searched_for', '')), gs))

    rows = []
    for e in g.edges:
        es = slug(e['id'])
        base = '%s/%s' % (gp_, es)
        rows.append('<tr><th scope="row"><a href="#e-%s">%s</a></th><td>%s</td><td>%s</td><td>%s</td></tr>'
                    % (es, esc(edge_title(g, e)), direction_badge(e['direction'], base + '/direction'),
                       span(base + '/certainty', certainty_text(e['certainty'])),
                       counts(base, e['studies'], e['claims'])))
    body += '<h2 id="table">All arrows as a table</h2>' + table(
        'Every arrow on the graph, with the same data as text',
        ['Arrow', 'Direction', 'Certainty', 'Studies'], ''.join(rows), 'all-edges')
    jumps = [('#read', 'How to read it'), ('#arrows', 'Evidence behind each arrow'), ('#table', 'All arrows as a table'),
             ('%s.html' % qid, 'Back to the answer')]
    return page(data, gfile, 'Q%d graph · %s' % (n, name), 'The %s answer drawn as a causal graph, with the '
                'sources behind every arrow.' % name.lower().replace(' ', '-'), body, jumps=jumps,
                script='static/graph.js')


# --------------------------------------------------------------- method

def render_method(data: SiteData) -> str:
    m = data.manifest.get('graph') or {}
    if m:
        src = ('The answers come from the Lane 2 causal graph: %s claims from %s papers, each recorded '
               'in the CAMO schema (cause, effect, direction, the study design, the comparator and the '
               'sentence in the paper).'
               % (span('manifest/graph/claims', '{:,}'.format(m.get('claims'))),
                  span('manifest/graph/source_documents', m.get('source_documents'))))
    else:
        src = ('The answers come from the Lane 2 causal graph, recorded in the CAMO schema (cause, effect, '
               'direction, the study design, the comparator and the sentence in the paper).')
    rule = next((q.rule for q in data.questions.values() if q.rule), 'unknown')
    body = (
        '<h1>How it works</h1>'
        '<nav class="tabs" aria-label="On this page"><ul><li><a href="#certainty">Certainty</a></li>'
        '<li><a href="#data">Where the data comes from</a></li><li><a href="#limits">Limits</a></li>'
        '<li><a href="#about">About us</a></li></ul></nav>'
        '%%CERTAINTY%%'
        '<section class="tab" aria-labelledby="data"><h2 id="data">Where the data comes from</h2>'
        '<p>%s The answer pack pools those claims into findings with simple, visible rules: no '
        'language model and no statistical modelling.</p>'
        '<p>Every direction, certainty grade and study count on this site is read from the pack\'s answer '
        'files when the site is built, and a check compares each one on every page with the pack before '
        'the site is published. Nothing is typed in by hand.</p>%%BUILT%%</section>'
        '%%LIMITS%%%%ABOUT%%'
        '<section class="tab" aria-labelledby="certainty"><h2 id="certainty">Certainty: how sure we can be</h2>'
        '<p class="lead">First we look at the best kind of study behind a finding. Experiments start at High, '
        'observation-only studies start at Low. It moves down a level if there\'s only one study or studies '
        'disagree, and up a level if several studies agree or they show how it works.</p>'
        '<p>On this site the four levels are numbered and drawn as bars: <strong>4</strong> High, '
        '<strong>3</strong> Moderate, <strong>2</strong> Low, <strong>1</strong> Very low. Each step moves exactly '
        'one level, and the level stays between 1 and 4. For example: start 4 (proper experiments), −1 (studies '
        'disagree), +1 (shows how it works) = 4, High.</p>'
        '<p>The pack uses rule <code>%s</code>. In full:</p>'
        '<ol><li>Start from the best study design in the body of evidence. A randomized experiment '
        'against an untreated control starts high. Other randomized, quasi-experimental and controlled '
        'long-term designs start moderate. Observational studies start low. Modelling and case studies '
        'start very low.</li>'
        '<li>Go down one step for a single study, one if studies disagree, and one if most claims '
        'report no comparison.</li>'
        '<li>Go up one step if three or more studies agree, and one if there is both evidence of '
        'mechanism and evidence that the treatment made a difference.</li>'
        '<li>A single study never rises above moderate.</li></ol>'
        '<p>Every grade comes with its reasoning: open a finding and read its “Why …?” checklist. The '
        'pack\'s exact rule text is under “exact rule text”.</p>'
        '<p>How strongly a paper words its claim (“causes” versus “is associated with”) is shown with each '
        'source as “Authors\' wording”. It is not used in the grade: how loudly a paper claims something '
        'and how strong its evidence is are separate questions.</p>'
        '<h2>Direction words</h2><dl class="defs">'
        '<dt>%s</dt><dd>Most studies (at least two thirds) found the outcome went up.</dd>'
        '<dt>%s</dt><dd>Most studies found it went down.</dd>'
        '<dt>%s</dt><dd>Studies disagree. This is a finding: the effect may depend on species, site or '
        'timing. Open the sources.</dd>'
        '<dt>%s</dt><dd>Studies tested it and found no clear change. A tested null is a finding, and it '
        'is different from a gap.</dd>'
        '<dt>%s</dt><dd>The claims do not say which way.</dd>'
        '<dt>%s, %s, %s</dt><dd>For created marshes: how they compare with a natural reference '
        'wetland.</dd></dl>'
        '<h2>Not studied is not “no effect”</h2>'
        '<p>A “Not studied” marker means nobody in this body of research tested that pairing. It does not '
        'mean the treatment fails. Gaps are shown in grey with a dashed border and the words “Not '
        'studied”, never as a weak or negative result.</p>'
        '<h2>Paths on the graph</h2>'
        '<p>On the tree-planting graph, a route through a middle condition (for example site '
        'preparation → competing vegetation → growth) joins two separate bodies of evidence, mostly from '
        'different papers. It is not one tested effect, and the site never multiplies arrows into a '
        'pathway strength.</p></section>'
        % (src, esc(rule),
           direction_badge('increase'), direction_badge('decrease'), direction_badge('mixed'),
           direction_badge('no_effect'), direction_badge('unclear'), direction_badge('below_reference'),
           direction_badge('comparable'), direction_badge('above_reference')))
    # Certainty first (the "?" popups link here), then data, limits, about
    cert_start = body.index('<section class="tab" aria-labelledby="certainty">')
    cert = body[cert_start:]
    body = body[:cert_start].replace('%CERTAINTY%', cert)
    lim = []
    for n, (qid, q) in enumerate(data.questions.items(), 1):
        lim.append('<h3>%02d %s</h3><ul>%s</ul>' % (n, esc(question_name(q)), ''.join(
            '<li>%s</li>' % esc(t) for t in q.limitations)))
    for gq in data.graph_qids():
        if data.graphs[gq].limitations:
            lim.append('<h3>%s graph</h3><ul>%s</ul>' % (esc(question_name(data.questions[gq])), ''.join(
                '<li>%s</li>' % esc(t) for t in data.graphs[gq].limitations)))
    built = ''.join('<h3>%02d %s</h3><p>%s</p>' % (n, esc(question_name(q)), esc(q.how_built))
                    for n, (qid, q) in enumerate(data.questions.items(), 1) if q.how_built)
    body = body.replace('%BUILT%', ('<h3 class="sub-h">How each answer was built</h3>%s' % built) if built else '')
    body = body.replace('%LIMITS%', '<section class="tab" aria-labelledby="limits"><h2 id="limits">Limits</h2>'
                        '<p>What each answer cannot tell you, as the answer pack states it. Each question page '
                        'shows its own list too.</p>%s</section>' % ''.join(lim))
    body = body.replace('%ABOUT%', '<section class="tab" aria-labelledby="about"><h2 id="about">About us</h2>'
                        '<p>Built by team Whimsy for Evidence Jam 2026, Lane 3 (decision support). The site '
                        'is static and works offline. It uses no language model: every sentence that states a '
                        'finding is built from the answer pack with fixed rules, and a check compares every '
                        'number on every page with the pack before the site is published.</p>'
                        '<p>Site code: MIT licence. Data: the Evidence Jam 2026 Lane 3 answer pack, built from '
                        'the Lane 2 CAMO causal graph.</p></section>')
    return page(data, 'method.html', 'Method · How it works', 'How certainty is graded, what the direction '
                'words mean and where every number comes from.', body)


# --------------------------------------------------------------- entry

def render_site(data: SiteData, prose: Prose, out: str) -> List[str]:
    os.makedirs(os.path.join(out, 'static'), exist_ok=True)
    for f in ('style.css', 'favicon.svg', 'graph.js'):
        shutil.copyfile(os.path.join(ROOT, 'static', f), os.path.join(out, 'static', f))
    # bundled fonts (no font is loaded from the internet), sorted so builds are repeatable
    fonts = os.path.join(ROOT, 'static', 'fonts')
    if os.path.isdir(fonts):
        os.makedirs(os.path.join(out, 'static', 'fonts'), exist_ok=True)
        for f in sorted(os.listdir(fonts)):
            if f.endswith(('.woff2', '.txt')):
                shutil.copyfile(os.path.join(fonts, f), os.path.join(out, 'static', 'fonts', f))
    sources: List[SourcePage] = []
    pages: Dict[str, str] = {'index.html': render_index(data, prose)}
    for qid, q in data.questions.items():
        fn = {EFFECTS: render_effects, COMPARISON: render_comparison, GAPMAP: render_gapmap}.get(
            data.kinds[qid], render_generic)
        pages['%s.html' % qid] = fn(data, prose, q, sources)
    for gq in data.graph_qids():
        pages[graph_file(gq)] = render_graph_page(data, gq, sources)
    pages['method.html'] = render_method(data)
    for sp in sources:
        if sp.fname in pages:
            raise RuntimeError('two pages named %s' % sp.fname)
        pages[sp.fname] = page(data, sp.fname, sp.title, sp.description, sp.body)
    for name, text in pages.items():
        with open(os.path.join(out, name), 'w', encoding='utf-8') as fh:
            fh.write(text)
    return list(pages)
