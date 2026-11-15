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
from graph_svg import FLOW as GRAPH_FLOW, SYM as GRAPH_SYM, order_rows

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
                  'only(pp,e);e.scrollIntoView({block:"nearest"});}addEventListener("hashchange",openTarget);openTarget();'
                  # in a row popup, show just one card (class "only"); "Show all" lifts it
                  'function only(pp,t){if(!pp||!pp.classList.contains("rowpop"))return;var li=t.closest("li");if(!li)return;'
                  'pp.querySelectorAll("ul.cells>li").forEach(function(x){x.classList.toggle("on",x===li)});'
                  'pp.classList.add("only");}'
                  # a button with data-open="<id>" opens its popup (popovertarget) and then that card in it
                  'document.addEventListener("click",function(ev){var a=ev.target.closest(".show-all");'
                  'if(a){a.closest("[popover]").classList.remove("only");return;}'
                  'var b=ev.target.closest("[data-open]");if(!b)return;'
                  'setTimeout(function(){var t=document.getElementById(b.getAttribute("data-open"));if(!t)return;'
                  'var d=t.querySelector("details");if(d)d.open=true;only(t.closest("[popover]"),t);'
                  't.scrollIntoView({block:"nearest"});},0);});</script>')


# "?" button (top right of the Why box and the glance table) opening one popup per page.
# Uses the browser's popover attribute: no script, keyboard and Esc work, closes on outside click.
HELP_BTN = ('<button type="button" class="help" popovertarget="how-grading" aria-label="How grading works">'
            '?</button>')
GRADING_POPOVER = (
    '<div id="how-grading" popover class="pop hgpop" role="dialog" aria-labelledby="how-grading-h">'
    '<div class="hg-head"><p class="hg-kick">Certainty</p><h2 id="how-grading-h">How grading works</h2>'
    '<button type="button" class="hg-x" popovertarget="how-grading" popovertargetaction="hide">'
    '<span aria-hidden="true">×</span><span class="sr-only">Close</span></button></div>'
    '<div class="hg-body">'
    '<p>Each finding gets a certainty level from 1 to 4, shown as bars:</p>'
    '<ul class="hg-levels">'
    '<li><span class="bars b4" aria-hidden="true"></span><strong>4</strong> High</li>'
    '<li><span class="bars b3" aria-hidden="true"></span><strong>3</strong> Moderate</li>'
    '<li><span class="bars b2" aria-hidden="true"></span><strong>2</strong> Low</li>'
    '<li><span class="bars b1" aria-hidden="true"></span><strong>1</strong> Very low</li></ul>'
    '<ol class="hg-steps"><li><strong>Start</strong> from the best kind of study behind it: randomized experiments '
    'with an untreated control start at 4; other controlled studies at 3; observation only at 2; models or case '
    'studies at 1.</li>'
    '<li><strong>−1</strong> if there is only one study, if studies disagree, or if most claims have nothing to '
    'compare against.</li>'
    '<li><strong>+1</strong> if three or more studies agree, or if it shows how it works, not just that it works.</li>'
    '<li><strong>Limits:</strong> the level stays between 1 and 4, and one study never goes above 3.</li></ol>'
    '<p class="ex">Example: start 4, −1 studies disagree, +1 shows how it works = <strong>4 High</strong>.</p>'
    '<p class="hg-foot"><a href="method.html#certainty">Full method →</a> '
    '<button type="button" class="hg-close" popovertarget="how-grading" popovertargetaction="hide">Close</button></p>'
    '</div></div>')


# "Full screen" for a wide map: shows the button only where the browser can do it; Esc exits.
FULLSCREEN_JS = ('<script>document.querySelectorAll("[data-fs]").forEach(function(b){var el=document.getElementById('
                 'b.getAttribute("data-fs"));if(!el||!el.requestFullscreen)return;b.hidden=false;'
                 'b.addEventListener("click",function(){el.requestFullscreen().catch(function(){})});});</script>')


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


# The study split in words, for the one-finding popup ("the numbers count studies: of these 3,
# 2 found it behind natural marshes and 1 found it ahead of natural marshes").
NOTE_FOUND = {'below_reference': 'it behind natural marshes', 'above_reference': 'it ahead of natural marshes',
              'comparable': 'it about the same as natural marshes', 'mixed': 'mixed results',
              'unclear': 'an unclear result', 'no_effect': 'no change', 'increase': 'an increase',
              'decrease': 'a decrease'}


def split_note(f: Finding, base: str) -> str:
    sd = f.study_directions
    if not sd:
        return ''
    keys = _keys(f.reference, sd)
    if f.direction in keys:
        keys.remove(f.direction)
        keys.insert(0, f.direction)
    found = lambda k: 'found %s' % NOTE_FOUND.get(k, words(k))
    n = span(base + '/studies', f.studies)
    if len(keys) == 1:
        k = keys[0]
        if f.studies == 1:
            return 'The number counts studies: the %s study %s.' % (n, found(k))
        return 'The number counts studies: all %s %s.' % (n, found(k))
    parts = ['%s %s' % (span('%s/study_directions/%s' % (base, k), sd[k]), found(k)) for k in keys]
    return ('The numbers count studies: of these %s, %s and %s.'
            % (n, ', '.join(parts[:-1]), parts[-1]))


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
                 labels: bool = False) -> str:
    """One finding. Closed it is one line: direction, name, certainty, study split, Details.
    Open it shows panels: why that certainty, sources (quotes first), Q1 pathways.
    labels: the box labels and the study split in words, for the one-finding popup (Q2) only;
    left out elsewhere because they are only shown there and the cards repeat (page weight)."""
    base = '%s/%s' % (f.question, f.slug)
    lab = (lambda t: '<span class="flab">%s</span>' % t) if labels else (lambda t: '')
    cw = CERT_WORD[f.certainty]
    checks = rationale_checks(f.certainty_rationale)
    reason = headline_reason(checks)
    reason_html = (' · <span class="reason"><span class="mk">%s</span> %s</span>' % (esc(reason[0]), esc(reason[1]))
                   if reason else '')
    summary = ('<span class="fchip">%s</span><h%d class="fhead">%s%s</h%d>'
               '<span class="fmore" aria-hidden="true">Details</span><span class="fmeta">'
               # flab / fnote: labels for the one-finding popup (.cardpop), where the card is read
               # on its own
               '<span class="fcert">%s<span class="bars b%d" aria-hidden="true"></span> %s%s</span>'
               '<span class="fsplit">%s%s %s%s</span></span>'
               % (chip(f.direction, base + '/direction'), level, card_name(f, subject), tag, level,
                  lab('Certainty: how sure are we?'), CERT_BARS.get(f.certainty, 0),
                  span(base + '/certainty', certainty_text(f.certainty)), reason_html,
                  lab('What the studies found'), split_bar(f), split_short(f, base),
                  '<span class="fnote">%s</span>' % split_note(f, base) if labels else ''))
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
    # the line under the heading is left out of compact cards (Q3 repeats them; page weight)
    sub = ('' if compact else '<p class="why-sub">Why “%s”: start from the best kind of study behind it, then one '
           'level up or down for each check.</p>' % esc(cw))
    why = ('<section class="panel pwhy"><h5>How the certainty is worked out%s</h5>%s%s'
           # the pack's exact rationale must be on the page (README; both checkers): kept, but quiet
           '<details class="raw"><summary>exact rule text</summary><p class="rule">%s</p></details></section>'
           % ('' if compact else HELP_BTN, sub,
              '<ul class="checks" data-rule></ul>' if compact else (('<ul class="checks">%s</ul>' % items) if items else ''),
              raw))
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
            % (' fref' if f.reference else '', esc(f.direction.replace('_', '-')), esc(f.slug), ' open' if open_ else '', summary, why, src, pw, more))


def at_a_glance(q: Question, short_html: str = '') -> str:
    """Q1: factors as rows, outcomes as columns; each cell links to its card."""
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
        cells[(g.subject_id, g.outcome_id)] = g
    def strength(sid: str) -> Tuple[int, int]:
        fs = [c for (s_, _), c in cells.items() if s_ == sid and isinstance(c, Finding)]
        return (min((CERT_ORDER.index(f.certainty) for f in fs), default=9), -sum(f.studies for f in fs))
    subjects.sort(key=lambda x: strength(x[0]))
    head = ''.join('<th scope="col">%s</th>' % esc(lbl) for _, lbl in outcomes)
    rows = []
    for sid, slbl in subjects:
        tds = []
        for oid, _ in outcomes:
            c = cells.get((sid, oid))
            if c is None:
                tds.append('<td class="none">–</td>')
            elif isinstance(c, Gap):
                tds.append('<td class="gapcell"><a href="#gap-%s"><span class="chip gapchip">'
                           '<span aria-hidden="true">?</span> Not studied</span></a></td>' % esc(c.slug))
            else:
                b = '%s/%s' % (c.question, c.slug)
                tds.append('<td><a href="#f-%s">%s <span class="bars b%d" aria-hidden="true"></span> %s · %s %s</a></td>'
                           % (esc(c.slug), chip(c.direction, b + '/direction'), CERT_BARS.get(c.certainty, 0),
                              span(b + '/certainty', CERT_WORD[c.certainty]), span(b + '/studies', c.studies),
                              plural(c.studies, 'study', 'studies')))
        rows.append('<tr><th scope="row">%s</th>%s</tr>' % (esc(slbl), ''.join(tds)))
    return ('<section class="glance-sec" aria-labelledby="glance"><h2 id="glance">At a glance %s</h2>%s'
            '<div class="table-wrap"><table class="glance"><caption>Every factor: which way it pushes each outcome, '
            'how sure we can be, and how many studies. Select a cell for the details.</caption><thead><tr>'
            '<th scope="col">Factor</th>%s</tr></thead><tbody>%s</tbody></table></div></section>'
            % (HELP_BTN, short_box(short_html, 'short') if short_html else '', head, ''.join(rows)))


# Our own short label for each limitation (Figma Q1 "Constraints"), in the pack's order. Shown in
# front of the pack's sentence, which stays word for word. Used only when the count matches.
LIMIT_TAGS = {'q1': ['Keyword matching', 'Fertilization', 'Vegetation', 'Growth'],
              'q2': ['', 'Created vs. restored', 'One snapshot', 'Keyword sorting'],   # 0 already starts "Thin evidence:"
              'q3': ['Grassland tagging', 'Unmapped claims', 'Empty isn\u2019t negative', 'Effort, not effect']}


def limits_box(prefix: str, limitations: Iterable[str], rule: Optional[str],
               how_built: Optional[str], heading: str = 'Read this first', open_: bool = False) -> str:
    """The pack's limitations, word for word. A closed one-liner, so the page stays clean,
    but always on the question page itself (README; both checkers)."""
    lims = list(limitations)
    tags = LIMIT_TAGS.get(prefix, [])
    tags = tags if len(tags) == len(lims) else [''] * len(lims)
    items = ''.join('<li>%s%s</li>' % ('<strong class="lim-tag">%s:</strong> ' % esc(tg) if tg else '',
                                       span('%s/limitations/%d' % (prefix, i), t))
                    for i, (tg, t) in enumerate(zip(tags, lims)))
    # how_built (the data team's selection rules) is on the Method page, under "Where the data comes from"
    return ('<details class="limits" id="limits-%s"' % esc(prefix) + (' open' if open_ else '') + '><summary><strong>%d %s this answer can\'t tell you</strong>'
            '<span class="cnt">read before acting on it</span></summary><p class="intro">In the data team\'s own '
            'words: how the studies were matched and grouped, and what that means for the answer above. '
            '<a href="method.html#data">How each answer was built →</a></p><ul>%s</ul></details>'
            % (len(lims), plural(len(lims), 'thing', 'things'), items))


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
<footer class="site"><p>Data: Evidence Jam 2026 Lane 3 answer pack, rule <code>$rule</code> · MIT licence ·
built $date</p></footer>
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
    items.append(('method.html', 'Guide'))
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
    more = item('method.html', '?', 'Guide') + item('index.html', '⌂', 'Home')
    return ('<aside class="side">'
            '<nav aria-label="Questions"><ol class="qnav">%s</ol><ul class="qnav more">%s</ul></nav></aside>'
            % (''.join(qs), more))


def build_date() -> str:
    sde = os.environ.get('SOURCE_DATE_EPOCH')
    if sde and sde.isdigit():
        return datetime.datetime.fromtimestamp(int(sde), datetime.timezone.utc).strftime('%Y-%m-%d')
    return datetime.date.today().isoformat()


# Home page tree (static/tree.svg) that turns as you scroll; static/tree.js splits it into layers.
# Kept in an inert <template> so it costs nothing until the script uses it; decorative only.
with open(os.path.join(ROOT, 'static', 'tree.svg'), encoding='utf-8') as _f:
    TREE_HTML = ('<div class="home-tree" id="treeStage" aria-hidden="true"><div class="tree-scene"></div></div>'
                 '<template id="treeSvg">%s</template>' % _f.read().strip())


def page(data: SiteData, filename: str, title: str, description: str, body: str, *,
         side: bool = True, jumps: Optional[List[Tuple[str, str]]] = None,
         script: Optional[str] = None, home_menu: Optional[str] = None, wide: bool = False,
         hero: str = '') -> str:
    """Every page has the same top bar (Figma "home page" frame): a thin line across the top of
    the screen, the boxed menu hanging from it (the line is the boxes' top edge) and the WHIMSY
    logo, which always links home. The bar stays at the top while scrolling.
    Home (home_menu given) then has the tree and a numbered menu of its own sections on the left;
    every other page has the left sidebar, styled the same way."""
    main = '<main id="main" tabindex="-1">\n%s\n</main>' % body
    # HOME | Q1 | Q2 | Q3 (Figma). Graph and Guide stay in the left menu. Each Qn also carries the
    # question's name for screen readers. The open page and its graph mark their own box.
    top = [('index.html', 'Home', '', ())] + [
        ('%s.html' % qid, 'Q%d' % n, question_name(q), (graph_file(qid),) if qid in data.graphs else ())
        for n, (qid, q) in enumerate(data.questions.items(), 1)] + [('method.html', 'Guide', '', ())]
    boxed = ''.join('<li><a href="%s"%s>%s%s</a></li>'
                    % (esc(h), ' aria-current="page"' if h == filename else (' class="here"' if filename in also else ''),
                       esc(t), '<span class="sr-only">: %s</span>' % esc(name) if name else '')
                    for h, t, name, also in top)
    over = 'hero-full' in hero or 'hero-sky' in hero   # header see-through over the hero's sky
    header = ('<header class="site-top%s"><div class="site-top-in"><a class="logo" href="index.html">'
              '<img src="static/logo.svg" alt="Whimsy: home" width="293" height="51"></a><nav aria-label="Main"><ul class="boxnav">%s</ul></nav>'
              '</div></header>' % ((' over light' if 'hero-full' in hero else ' over') if over else '', boxed))
    if over:   # on a full-photo hero the header is see-through until the photo scrolls past
        header += ('<script>addEventListener("DOMContentLoaded",function(){var h=document.querySelector(".site-top"),'
                   'b=document.querySelector(".hero");if(!h||!b)return;'
                   'function f(){h.classList.toggle("over",b.getBoundingClientRect().bottom>h.offsetHeight);}'
                   'addEventListener("scroll",f,{passive:true});addEventListener("resize",f);f();});</script>')
    if home_menu is not None:
        layout = ('%s<div class="home-grid"><div class="home-side">%s'
                  '<nav class="home-menu" aria-label="On this page">%s</nav></div>%s</div>'
                  % (header, TREE_HTML, home_menu, main))
    elif side and hero:
        # question pages: the full-width hero, then the content; no left menu (the top menu has
        # Home and Q1-Q3, the page links to its graph and to the Guide)
        layout = ('%s<main id="main" tabindex="-1" class="has-hero">%s<div class="content solo">\n%s\n</div></main>'
                  % (header, hero, body))
    elif side:
        # wide (the graph page): the menu runs across the top so the content gets the full width
        layout = '%s<div class="layout%s">%s%s</div>' % (header, ' wide' if wide else '',
                                                       side_nav(data, filename, jumps), main)
    else:
        layout = header + main
    rule = next((q.rule for q in data.questions.values() if q.rule), 'unknown')
    tag = '<script src="%s" defer></script>\n' % esc(script) if script else ''
    return SHELL.substitute(title=esc(title), description=esc(description), layout=layout,
                            body=body, rule=esc(rule), date=build_date(), script=tag)


# --------------------------------------------------------------- pages

# "How to read this site": the symbols used on every page (shown on the Guide page)
READ_KEY = ('<ul class="key-list">'
            '<li><span class="chip dir-increase"><span aria-hidden="true">▲</span> Increases</span> '
            '<span class="chip dir-decrease"><span aria-hidden="true">▼</span> Decreases</span> '
            '<span class="chip dir-mixed"><span aria-hidden="true">⇅</span> Mixed</span> what studies found</li>'
            '<li><span class="bars b3" aria-hidden="true"></span> how sure we can be, 1 to 4</li>'
            '<li><span class="chip gapchip"><span aria-hidden="true">?</span> Not studied</span> nobody here tested it '
            '(not “doesn’t work”)</li>'
            '<li><span class="qmark" aria-hidden="true">“ ”</span> sentences quoted word for word from the papers</li>'
            '</ul>')


# Home "Problem" opening (Figma home page frame). Each flower in static/home-flowers.webp as
# [centre x, centre y, radius] in percent, so the page can show them one at a time with clip-path.
HOME_FLOWERS = [[9.1, 7.7, 5.2], [29.2, 7.6, 6], [26.1, 14.5, 3.7], [38.9, 16.6, 5.2], [40.7, 30.2, 4.1], [74.4, 32.7, 4.4], [33.3, 36, 4.4], [77.9, 40, 5.7], [52.7, 46.3, 4.9], [45.2, 53.5, 6], [88.3, 63.6, 5.2], [73.3, 66.9, 4.3], [56.3, 81.6, 4.4], [45.5, 92.4, 5.2]]
HOME_PAPER_STRIPS = 24   # the paper band is shown in this many slices, one after another


def problem_section() -> str:
    """The opening of the home page: the problem in one sentence, then flowers, then "hundreds of
    papers" over a band of paper stacks. static/problem.js reveals them as you scroll; without
    script (or with reduced motion) everything shows at once. Pictures are decorative."""
    flowers = ''.join('<img src="static/home-flowers.webp" alt="" decoding="async" '
                      'style="clip-path:circle({}% at {}% {}%)">'.format(r, x, y) for x, y, r in HOME_FLOWERS)
    n = HOME_PAPER_STRIPS
    strips = ''.join('<img src="static/home-papers.webp" alt="" decoding="async" loading="lazy" '
                     'style="clip-path:inset(0 {:.3f}% 0 {:.3f}%)">'.format(100 - (i + 1) * 100 / n, i * 100 / n)
                     for i in range(n))
    # hide the parts before the first paint (no flash), unless the reader asks for reduced motion
    early = ('<script>(function(s){if(!matchMedia("(prefers-reduced-motion: reduce)").matches){s.classList.add("anim");'
             '}})(document.currentScript.parentNode);</script>')
    return ('<section class="problem" id="problem" aria-labelledby="problem-h">' + early + '<div class="pb-pin">'
            '<p class="pb-kicker">Problem</p>'
            '<h1 id="problem-h">Restoration practitioners make decisions <span class="hl">every day</span> '
            'about where to plant, what to treat and what to try next.</h1>'
            '<div class="pb-flowers" aria-hidden="true">' + flowers + '</div>'
            '<p class="pb-spread">The research that could guide those choices is spread across:</p>'
            '<p class="pb-many">hundreds of papers</p>'
            '<div class="pb-papers" aria-hidden="true">' + strips + '</div>'
            '</div></section>')


def render_index(data: SiteData, prose: Prose) -> str:
    """Home, laid out as the Figma "home page" frame: each section has a big blue heading over a
    thin rule, with its text indented below; a numbered menu on the left (pinned bottom-left)
    leads to the sections and the questions. Content: the headline, one sentence, how to use the
    site, and the questions (each answer is one click away)."""
    def section(sid: str, heading: str, inner: str, level: int = 2, cls: str = '') -> str:
        return ('<section class="hsec%s" id="%s" aria-labelledby="%s-h"><h%d id="%s-h">%s</h%d>'
                '<div class="hsec-body">%s</div></section>'
                % (' ' + cls if cls else '', sid, sid, level, sid, heading, level, inner))

    menu = []      # (link, mark, label) for the left menu
    sections = [problem_section()]
    m = data.manifest.get('graph') or {}
    papers = (' from %s papers' % span('manifest/graph/source_documents', m['source_documents'])
              if m.get('source_documents') else '')
    sections.append(section(
        'top', 'our mission',
        '<p class="lead">Plain answers to %s restoration questions%s: what works, how sure we can be, '
        'and where nothing has been studied. Works offline.</p>' % (number_word(len(data.questions)), papers),
        level=2, cls='mission'))
    menu.append(('#guide', '?', 'How to use this site'))
    sections.append(section(
        'guide', 'How to use this site',
        '<p>Pick one of the questions below. Each answer starts with a short answer, then a chart or table '
        'you can take in at a glance: what each treatment does, how sure we can be, and how many studies '
        'looked at it.</p>'
        '<p>Select any row or box to see why the evidence got its certainty grade and to read the exact '
        'sentences from the papers, with a link to each one. Before acting on an answer, open “things this '
        'answer can’t tell you”: it says how the studies were picked and grouped.</p>'
        '<p class="go"><a href="method.html">The Guide: symbols, grading and where the data comes from →</a>'
        '</p>', cls='guide'))
    for n, (qid, q) in enumerate(data.questions.items(), 1):
        graph = ''
        if qid in data.graphs:
            graph = (' · <a href="%s">See it as a graph<span class="sr-only">: %s</span></a>'
                     % (graph_file(qid), esc(question_name(q))))
        menu.append(('%s.html' % qid, '%02d' % n, question_name(q)))   # the question's own page
        sections.append(section(
            'card-%s' % qid,
            '<span class="qn">Q%d.</span> <a href="%s.html">%s</a>' % (n, esc(qid), esc(question_name(q))),
            '<p class="q">%s</p>%s<p class="go"><a href="%s.html">Go to question →<span class="sr-only"> %s'
            '</span></a>%s</p>' % (esc(q.text), home_summary(prose, qid), esc(qid), esc(question_name(q)), graph), cls='qsec'))
    # data-sec: the home section each item stands for, so static/tree.js can mark the one being read
    menu_html = '<ol class="qnav">%s</ol>' % ''.join(
        '<li data-sec="%s"><a href="%s"><span class="n" aria-hidden="true">%s</span> %s</a></li>'
        % (esc(h[1:] if h.startswith('#') else 'card-' + h[:-len('.html')]), esc(h), esc(mk), esc(t))
        for h, mk, t in menu)
    return page(data, 'index.html', 'Whimsy · Restoration evidence', 'Plain answers to restoration questions, '
                'with certainty, gaps and sources.', ''.join(sections) + '<script src="static/problem.js" defer></script>',
                home_menu=menu_html, script='static/tree.js')


def home_summary(prose: Prose, qid: str) -> str:
    """The question's summary on the home page; says so when a language model wrote it."""
    p = prose.home_summary.get(qid)
    if not p:
        return ''
    note = (' <small class="llm-note">Summary written at build time by a language model from this answer\'s '
            'findings; the question page has the exact values.</small>' if p.source == 'llm' else '')
    return '<p class="qsum" data-source="%s">%s%s</p>' % (esc(p.source), p.html, note)


def number_word(n: int) -> str:
    return {1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six', 7: 'seven', 8: 'eight',
            9: 'nine', 10: 'ten'}.get(n, str(n))


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
        lbl = g.outcome_label
        if g.searched_for.count(lbl) != 1 and g.searched_for.count(lbl.lower()) == 1:
            lbl = lbl.lower()  # the pack writes the outcome in lower case mid-sentence
        templates.add(g.searched_for.replace(lbl, OUTCOME_SLOT)
                      if g.searched_for.count(lbl) == 1 else None)
    if len(templates) == 1 and None not in templates:
        return templates.pop()
    return None


OUTCOME_SLOT = '{outcome}'

# One line on what each outcome group covers, in our words, summarised from the keywords that
# define the group in groups/lane3_groups.yaml. Shown under a not-studied outcome when a list
# has only one topic (Q2), so the reader knows what "not studied" spans.
OUTCOME_INFO = {
    'invasive_abundance': 'Cover, density or spread of invasive and non-native plants, e.g. buckthorn, '
                          'Phragmites, reed canary grass, smooth brome.',
    'contaminants': 'Metals, salts, hydrocarbons, PCBs and other contaminants, and their toxicity.',
    'ecosystem_function': 'Carbon and gas fluxes, decomposition, productivity, nutrient cycling and '
                          'methane release.',
    'richness_diversity': 'How many species or taxa there are, and how evenly they are spread.',
    'community_composition': 'Which species make up the community, and how similar it is to another site.',
    'survival_mortality': 'Whether plants or animals live or die, including dieback and persistence.',
    'establishment_regeneration': 'Germination, seedling emergence, recruitment, colonisation and the seed bank.',
    'reproduction': 'Flowering, seed set, nesting, hatching and other breeding success.',
    'plant_cover': 'Percent cover of plants and vegetation, and canopy closure.',
    'animal_abundance': 'Numbers or presence of birds, fish, insects, amphibians, mammals and other animals.',
    'soil_water_chemistry': 'Nutrients, carbon, pH and other chemistry of soil, water or plant tissue.',
    'soil_physical': 'Soil moisture, temperature, compaction, bulk density, light and microclimate.',
    'hydrology_geomorphology': 'Water levels, flooding, flow, erosion, sediment and landform change.',
    'growth_size': 'Growth, height, biomass and other measures of size.',
    'abundance_density': 'How many plants or other organisms there are, and how dense or frequent.',
    'behaviour_habitat_use': 'Movement, foraging, habitat use, predation, herbivory and pollinator visits.',
}


NS_SHOWN = 12  # not-studied pairings listed before "+ N more"
NS_OPEN = 3    # a list this short starts open: no click needed to see it

# Topic / outcome pickers and "+ N more" for the Not studied dropdown live in static/ns.js
# (shared and cached across pages). Without script every pairing is listed and the pickers stay hidden.


def not_studied(q: Question) -> str:
    """Gaps, the same way on every page: a "See not-studied pairings" dropdown listing each
    pairing as "<topic> → <outcome>", with topic and outcome filters. Never worded as a negative
    result: each item says "Not studied" (to screen readers; the dashed "?" ring shows it)."""
    if not q.gaps:
        return ''
    subjects: Dict[str, str] = {}
    outcomes: Dict[str, str] = {}
    groups: Dict[str, List[Gap]] = {}
    for g in q.gaps:
        subjects.setdefault(g.subject_id, g.subject_label)
        outcomes.setdefault(g.outcome_id, g.outcome_label)
        groups.setdefault(g.subject_id, []).append(g)
    s_ix = {k: str(i) for i, k in enumerate(subjects)}
    o_ix = {k: str(i) for i, k in enumerate(outcomes)}
    n = len(q.gaps)
    word = plural(n, 'pairing', 'pairings')
    # One topic for every gap (Q2): name the topic once and list just the outcomes, each with a
    # line on what it covers, and say what was searched for once at the bottom.
    one = len(subjects) == 1 and n > 1 and search_template(q.gaps) is not None
    # What was searched for: said once per topic when the pack uses one sentence for all its
    # outcomes (shown when that topic is picked), else on each pairing.
    notes, own, foot_note = [], set(), ''
    for sid, gs in groups.items():
        template = search_template(gs)
        if template is None:
            own.update(g.slug for g in gs)
            continue
        if one:
            foot_note = ('<p class="searched" data-template="%s">Searched for and not found: %s.</p>'
                         % (esc(template), esc(template.replace(OUTCOME_SLOT, 'that outcome'))))
            continue
        notes.append('<p class="searched" data-s="%s" data-template="%s">Searched for and not found: %s.</p>'
                     % (s_ix[sid], esc(template), esc(template.replace(OUTCOME_SLOT, 'that outcome'))))
    if one:
        items = ''.join(
            '<li class="gap" id="gap-%s" data-s="%s" data-o="%s"><strong class="sr-only">Not studied:</strong> '
            '<span class="on">%s</span>%s</li>'
            % (esc(g.slug), s_ix[g.subject_id], o_ix[g.outcome_id], esc(g.outcome_label),
               ' <span class="info">%s</span>' % esc(OUTCOME_INFO[g.outcome_id])
               if g.outcome_id in OUTCOME_INFO else '')
            for g in q.gaps)
    else:
        items = ''.join(
            '<li class="gap" id="gap-%s" data-s="%s" data-o="%s"><strong class="sr-only">Not studied:</strong> '
            '%s <span class="o">%s</span>%s</li>'
            % (esc(g.slug), s_ix[g.subject_id], o_ix[g.outcome_id], esc(g.subject_label), esc(g.outcome_label),
               ' <span class="searched">Searched for: %s</span>' % esc(g.searched_for) if g.slug in own else '')
            for g in q.gaps)

    def picker(key: str, label: str, name: str, empty: str, opts: Dict[str, str], ix: Dict[str, str]):
        """A box of removable chips plus a "Choose a ..." button that opens a grid of toggle
        buttons, one per value: several values can be chosen. A chosen value leaves the grid and
        shows as a chip (Figma frames 7-9)."""
        if len(opts) < 2:
            return '', ''
        box = ('<div class="ns-pick" data-k="%s" data-name="%s" data-panel="ns-%s-p">'
               '<span class="ns-lab" id="ns-%s-l">%s</span><div class="ns-box"><span class="ns-chips"></span>'
               '<button type="button" class="ns-open" id="ns-%s-b" aria-labelledby="ns-%s-l ns-%s-b" '
               'aria-expanded="false" aria-controls="ns-%s-p">%s</button></div></div>'
               % (key, esc(name), key, key, esc(label), key, key, key, key, esc(empty)))
        panel = ('<div class="ns-panel" id="ns-%s-p" role="group" aria-labelledby="ns-%s-l" hidden>%s</div>'
                 % (key, key, ''.join('<button type="button" data-v="%s">%s</button>'
                                      % (ix[k], esc(v)) for k, v in opts.items())))
        return box, panel
    sb, sp = picker('s', 'Topic (intervention)', 'Topic', 'Choose a topic', subjects, s_ix)
    ob, op = picker('o', 'Outcome', 'Outcome', 'Choose an outcome', outcomes, o_ix)
    filters = sb + ob + sp + op
    ns_t, no_t = len(subjects), len(outcomes)
    scope = 'Across %d %s and %d %s.' % (ns_t, plural(ns_t, 'topic', 'topics'), no_t, plural(no_t, 'outcome', 'outcomes'))
    if one:
        scope = ('Outcomes nobody here measured for <strong>%s</strong>.'
                 % esc(next(iter(subjects.values()))))
    if filters:
        scope += ' Choose %s to narrow the list.' % ('outcomes' if one else 'topics or outcomes')
    scope = '<p class="ns-sub">%s</p>' % scope if n > 1 else ''
    intro = ('<h2 class="ns-h" id="not-studied">Not studied</h2>'
             '<p class="ns-intro">These are combinations <em>nobody</em> in this body of research has '
             '<em>tested</em>. We searched for studies and found none. <em>“Not studied”</em> means '
             '<em>we simply don’t know</em>: it might help, harm, or do nothing.</p>')
    return (
        '<section class="ns-sec" aria-labelledby="not-studied">' + intro +
        '<details class="ns" id="gaps-h" data-shown="%d"%s><summary><span class="ns-q" aria-hidden="true">?</span>'
        '<h3><span class="v-see">See</span><span class="v-hide">Hide</span> not-studied pairings</h3>'
        '<span class="ns-c">%d</span></summary>'
        '%s<div class="ns-p"><p class="ns-t" role="status"><strong><span class="ns-n">%d</span> not-studied '
        '<span class="ns-w">%s</span></strong></p>%s'
        '<p class="ns-key"><span class="ns-dot" aria-hidden="true"></span> Not studied: no paper here tested the pairing.</p>%s'
        '<ul class="gaps%s">%s</ul><p class="ns-none" hidden>None of the chosen pairings is in the not-studied list. '
        'Remove a topic or an outcome to see more.</p><button type="button" class="ns-more" hidden></button>'
        '<p class="ns-foot">No paper in this body of research tested %s. Not studied is not a '
        'negative result: nobody here tested it.</p>%s</div></details></section><script src="static/ns.js" defer></script>'
        % (NS_SHOWN, ' open' if n <= NS_OPEN else '', n, '<div class="ns-f" hidden>%s</div>' % filters if filters else '', n, word, scope,
           ''.join(notes), ' one' if one else '', items, 'this pairing' if n == 1 else 'these pairings', foot_note))


# The phrase picked out in each question's hero (Figma). Only used if the question contains it.
HERO_MARK = {
    'q1': 'planting-stock traits',
    'q2': 'biodiversity and function',
    'q3': 'intervention-outcome combinations',
}
HERO_EXT = ('webp', 'avif', 'jpg', 'png')
# 'full': the photo fills the whole hero, sky included, with the header over it (Q3 in Figma).
# 'sky': a white-to-pale-blue sky gradient with the photo along the bottom (Q2 in Figma).
# Default: Q1-style picture beside the text ('effects' questions), else a landscape band.
HERO_STYLE = {'q2': 'sky', 'q3': 'full'}


def hero_image(qid: str) -> Optional[str]:
    """static/hero-<qid>.<ext> if the team added a picture for this question."""
    for ext in HERO_EXT:
        if os.path.exists(os.path.join(ROOT, 'static', 'hero-%s.%s' % (qid, ext))):
            return 'static/hero-%s.%s' % (qid, ext)
    return None


def hero_stats(data: SiteData, q: Question) -> List[Tuple[str, str]]:
    """The blue bar under the hero: the same four labels on every question (Figma), each count
    taken straight from that question's data (0 where it has none)."""
    papers = len({(e.doi or e.title) for e in q.evidence.values()})
    return [('Findings', esc(len(q.all_findings()))), ('Not studied', esc(len(q.gaps))),
            ('Papers', esc(papers)), ('Combined-treatment claims', esc(len(q.extra.get('interactions') or [])))]


def hero(data: SiteData, q: Question, n: int, name: str, lead: str = '') -> str:
    """Top of a question page (Figma): kicker, the question with one phrase picked out, dotted
    shapes, a picture, and a blue bar of counts. Q1 has the picture beside the text, the others
    a landscape band under it. Shapes and picture are decorative."""
    text = esc(q.text)
    mark = HERO_MARK.get(q.qid)
    if mark and esc(mark) in text:
        text = text.replace(esc(mark), '<span class="hl">%s</span>' % esc(mark), 1)
    img = hero_image(q.qid)
    side = data.kinds.get(q.qid) == 'effects'
    style = HERO_STYLE.get(q.qid) if img is not None else None
    full = style in ('full', 'sky')
    pic = '<div class="hero-pic"><img src="%s" alt="" decoding="async"></div>' % esc(img) if img else ''
    clouds = os.path.join(ROOT, 'static', 'hero-%s-clouds.svg' % q.qid)
    if full and os.path.exists(clouds):   # the Figma frame's own dotted clouds
        blobs = '<img class="hero-clouds" src="static/hero-%s-clouds.svg" alt="">' % esc(q.qid)
    else:
        blobs = ''.join('<span class="blob b%d" aria-hidden="true"></span>' % i for i in (1, 2, 3))
    if full:   # the photo goes behind everything, not in the text's grid
        blobs, pic = pic.replace('hero-pic', 'hero-bg') + blobs, ''
    stats = ''.join('<div><dt>%s</dt><dd>%s</dd></div>' % (esc(k), v) for k, v in hero_stats(data, q))
    return ('<div class="hero hero-%s %s%s">%s<div class="hero-in"><div class="hero-txt">'
            '<p class="kicker">Q%d · %s</p><h1>%s</h1>%s</div>%s</div></div>'
            '<dl class="hero-stats" aria-label="This question in numbers">%s</dl>'
            % (esc(q.qid), 'hero-full' if style == 'full' else 'hero-sky' if style == 'sky' else 'hero-side' if side else 'hero-band', '' if img else ' no-pic', blobs, n, esc(name), text,
               '<p class="hero-lead">%s</p>' % lead if lead else '', pic, stats))


# Q1 "Overview & Constraints" (Figma frame "Q1 - tree planting", under the blue bar): a dotted
# wave (Vector 35) with a pin at its low point and one at its peak; the short answer on the left,
# the limitations inside the crest. static/ov.js draws the wave left to right as you scroll and
# shows each part as the wave reaches it. Wave and pins are decorative.
OVERVIEW_STYLE = {'q1', 'q2', 'q3'}   # Figma frames "Q1 - tree planting", "Desktop - 4", "Desktop - 5"
CERT_RANK = {'high': 0, 'moderate': 1, 'low': 2, 'very_low': 3}
OV_WAVE = '<div class="ov-wave-box" aria-hidden="true"><div class="ov-wave"></div></div>'   # shape: static/ov-wave.svg


def _outcome(f: Finding) -> str:
    """The outcome half of a finding label ("Created ... vs natural reference: Growth, size & biomass")."""
    o = f.label.split(': ', 1)[-1]
    return o[:1].lower() + o[1:]


def _cert(f: Finding) -> str:
    return f.certainty.replace('_', ' ')


def overview_short(data: SiteData, q: Question, short: str) -> str:
    """The short answer, as headed parts for the Overview (Figma). Q1's is already headed. Q2 and
    Q3 get their Figma headings; every sentence is built from the pack's own values."""
    kind = data.kinds.get(q.qid)
    if kind == 'comparison':
        sa = q.extra.get('short_answer') or {}
        note = span('%s/short_answer/time_to_reference_note' % q.qid, sa.get('time_to_reference_note') or '')
        ttr = sa.get('time_to_reference')
        how = (span('%s/short_answer/time_to_reference' % q.qid, ttr) + '. ' + note if ttr is not None
               else '<strong class="sa-lead">This body of research cannot say.</strong> ' + note)
        word = {'below_reference': 'behind natural marshes on', 'above_reference': 'ahead of natural marshes on',
                'comparable': 'level with natural marshes on', 'mixed': 'mixed against natural marshes on',
                'unclear': 'unclear against natural marshes on'}
        firm = sorted([f for f in q.findings if f.certainty in ('high', 'moderate')], key=lambda f: CERT_RANK[f.certainty])
        short_word = {k: v.replace(' natural marshes', '').replace(' of', '') for k, v in word.items()}
        parts = ['with %s certainty, %s %s' % (_cert(f), ('created marshes are ' + word.get(f.direction, f.direction)) if i == 0
                                                else short_word.get(f.direction, f.direction), esc(_outcome(f)))
                 for i, f in enumerate(firm)]
        rest = len(q.findings) - len(firm)
        compare = ('; '.join(parts) + '.' if parts else '')
        compare = compare[:1].upper() + compare[1:]
        if rest:
            compare += ' The other %d %s low or very low certainty.' % (rest, plural(rest, 'comparison has', 'comparisons have'))
        tword = {'no_effect': 'shows no clear change', 'increase': 'goes up', 'decrease': 'goes down',
                 'mixed': 'shows mixed results', 'unclear': 'is unclear'}
        tfirm = sorted([f for f in q.trends if f.certainty in ('high', 'moderate')], key=lambda f: CERT_RANK[f.certainty])
        age = ' '.join('With %s certainty, %s %s as marshes get older.' % (_cert(f), esc(_outcome(f)), tword.get(f.direction, f.direction))
                       for f in tfirm)
        trest = len(q.trends) - len(tfirm)
        if trest:
            age += ' %d more %s low or very low certainty.' % (trest, plural(trest, 'trend has', 'trends have'))
        items = [('How long to catch up', how), ('Compared with natural marshes', compare)]
        if q.trends:
            items.append(('As marshes age', age.strip()))
        return ('<div class="short callout" role="note" aria-label="How long" id="short"><p class="sa-h"><strong>'
                'Short answer</strong></p><ul class="sa">%s</ul></div>'
                % ''.join('<li><strong>%s:</strong> %s</li>' % (h, t) for h, t in items))
    if kind == 'gapmap' and 'summary' in q.extra:
        m = re.search(r'<p class="sa-h">.*?</p><p>(.*)</p></div>$', short, re.S)
        if not m:
            return short
        s = q.extra['summary']
        n = len(q.gaps)
        hasnt = ('%d of %s combinations have no study in this body of research. An empty cell is not a negative '
                 'result: nobody here tested it.' % (n, span('%s/summary/cells' % q.qid, s['cells'])))
        return ('<div class="short" id="short"><p class="sa-h"><strong>Short answer</strong></p><ul class="sa">'
                '<li><strong>What has been studied:</strong> %s</li><li><strong>What hasn\u2019t:</strong> %s</li></ul></div>'
                % (m.group(1), hasnt))
    return short


def overview_section(short_html: str, limits_html: str, qid: str = '') -> str:
    """The short answer and the limitations, laid out over the wave (see OV_WAVE). ov-<qid> lets a
    question move its text where its wording is longer (CSS)."""
    early = ('<script>(function(s){if(!matchMedia("(prefers-reduced-motion: reduce)").matches&&'
             'matchMedia("(min-width: 900px)").matches)s.classList.add("anim");})(document.currentScript.parentNode);</script>')
    return ('<div class="ov-track"><section class="ov%s" id="overview" aria-label="Overview and constraints">' % (' ov-' + esc(qid) if qid else '') + early + OV_WAVE +
            '<img class="ov-pin pin-top" src="static/pin.webp" alt="" width="84" height="126">'
            '<img class="ov-pin pin-bottom" src="static/pin.webp" alt="" width="84" height="126">'
            '<div class="ov-left"><h2 class="ov-label">Overview</h2>' + short_html + '</div>'
            '<div class="ov-right"><h2 class="ov-label">Constraints</h2>' + limits_html + '</div>'
            '</section></div><script src="static/ov.js" defer></script>')


def question_page(data: SiteData, prose: Prose, q: Question, main: str, *,
                  jumps: List[Tuple[str, str]], short: Optional[str] = None, scripts: str = '') -> str:
    """The one template every question page uses, in this order: kicker + h1, short answer,
    limitations, MAIN VIEW, not studied, link to the Guide."""
    n = list(data.questions).index(q.qid) + 1
    name = question_name(q)
    lead = ''
    if data.kinds.get(q.qid) == 'effects':
        lead = '<span class="hl">Each finding</span> below shows its direction, certainty and number of studies; open one to read the studies behind it.'
    top = hero(data, q, n, name, lead)
    body = short if short is not None else short_box(prose.short_answer[q.qid].html, 'short')
    if q.qid in OVERVIEW_STYLE:
        body = overview_section(overview_short(data, q, body), limits_box(q.qid, q.limitations, q.rule, q.how_built, open_=True),
                                q.qid)
    else:
        body += limits_box(q.qid, q.limitations, q.rule, q.how_built)
    body += main
    body += not_studied(q)
    body += ('<p class="to-method"><a href="method.html">Guide: how to read this site, how certainty is graded, where the data '
             'comes from, and the limits →</a></p>')
    jumps = [('#short', 'Short answer')] + jumps + ([('#not-studied', 'Not studied')] if q.gaps else [])
    return page(data, '%s.html' % q.qid, 'Q%d · %s' % (n, name), q.text,
                body + GRADING_POPOVER + OPEN_TARGET_JS + scripts, jumps=jumps, hero=top)


def by_strength(fs: Iterable[Finding]) -> List[Finding]:
    return sorted(fs, key=lambda f: (CERT_ORDER.index(f.certainty), -f.studies))


def render_effects(data: SiteData, prose: Prose, q: Question, sources: List[SourcePage]) -> str:
    """EFFECTS layout (Q1 today). Main view: at a glance, findings by outcome (strongest first),
    combined treatments, graph link."""
    def card(f: Finding) -> str:
        graph = ''
        if f.slug in data.graph_join:
            graph = ('<a href="%s#e-%s">On the graph<span class="sr-only">: %s</span></a>'
                     % (graph_file(q.qid), esc(slug(data.graph_join[f.slug])), esc(f.label)))
        return finding_card(data, f, sources, level=4, links=graph)

    groups: Dict[str, List[Finding]] = {}
    for f in q.findings:
        groups.setdefault(f.outcome_label, []).append(f)
    main = at_a_glance(q)
    main += ('<h2 id="findings">Findings</h2><p class="note">Open a group, then a finding, for why it has that '
             'certainty, the quoted sources and, where the graph has them, possible pathways.</p>')
    for outcome, fs in groups.items():
        main += fold('o-%s' % slug(fs[0].outcome_id), esc(outcome), 3, '%d findings, strongest first' % len(fs),
                     '<div class="cards">%s</div>' % ''.join(card(f) for f in by_strength(fs)))
    main += interactions_section(data, q)
    if q.qid in data.graphs:
        main += '<p class="graph-link"><a href="%s">See this answer as a graph →</a></p>' % graph_file(q.qid)
    jumps = [('#glance', 'At a glance')]
    jumps += [('#o-%s' % slug(fs[0].outcome_id), fs[0].outcome_label) for fs in groups.values()]
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


# --------------------------------------------------------------- Q2 chart
# "Outcome by outcome" (Figma frame "current graph"): one row per finding with its result, a
# 4-block certainty meter, the marsh ages studied on a 0-30 year track, and (compared with
# natural marshes) "Matched natural marshes yet?". It is NOT a recovery curve: no study reports
# a time to reach the reference (time_to_reference is null), and the bar colour is the overall
# result, pooled across ages. HTML (not SVG) so it reflows into stacked rows on a phone.

TL_WORD = {'below_reference': ('◀', 'Behind'), 'above_reference': ('▶', 'Ahead'),
           'comparable': ('=', 'Matches'), 'mixed': ('⇅', 'Mixed'), 'unclear': ('?', 'Unclear'),
           'increase': ('▲', 'Increase'), 'decrease': ('▼', 'Decrease'), 'no_effect': ('–', 'No change')}
# colour key per direction (the CSS class mc-<key>), and the legend word
MC_KEY = {'below_reference': 'behind', 'decrease': 'behind', 'above_reference': 'ahead', 'increase': 'ahead',
          'comparable': 'ahead', 'mixed': 'mixed', 'unclear': 'unclear', 'no_effect': 'nochg'}
MC_LEGEND = [('behind', 'Behind'), ('ahead', 'Ahead'), ('mixed', 'Mixed'), ('unclear', 'Unclear'),
             ('nochg', 'No change')]
# "Matched natural marshes yet?": the answer word, and the result word for the line under it
MC_MATCHED = {'below_reference': ('No', 'behind'), 'above_reference': ('Yes (ahead)', 'ahead'),
              'comparable': ('Yes', 'matches'), 'mixed': ('Mixed', ''), 'unclear': ('Unclear', '')}
MC_CLAIM_WORD = {'above_reference': 'higher', 'comparable': 'same', 'below_reference': 'lower', 'unclear': 'unclear'}
MC_SPLIT_WORD = {'below_reference': 'behind', 'above_reference': 'ahead'}
# the chart's heading per question (falls back to "Outcome by outcome"); the line under it is
# shown only while the pack has no time to reach the reference
MC_TITLE = {'q2': ('How long until created marshes match natural ones?',
                   'No study followed a created marsh until it fully matched a natural one, '
                   'so we don’t know how long it takes.')}
MC_ORDER = {'below_reference': 0, 'above_reference': 1, 'comparable': 2, 'mixed': 3, 'unclear': 4}
# "How to read this": what each result word means, for each group of the chart
MC_HOW_REF = {'below_reference': 'Created marsh scored lower than natural',
              'above_reference': 'Created marsh scored higher than natural',
              'comparable': 'Created marsh scored about the same as natural',
              'mixed': 'Some measures higher, some the same',
              'unclear': 'Different from natural, but not better or worse'}
MC_HOW_AGE = {'no_effect': 'Older created marshes were no different from newer ones',
              'increase': 'Older created marshes scored higher than newer ones',
              'decrease': 'Older created marshes scored lower than newer ones',
              'mixed': 'Some measures changed with age, some did not',
              'unclear': 'The studies do not say which way it changed'}
CERT_BLOCKS = {'very_low': 1, 'low': 2, 'moderate': 3, 'high': 4}
TL_MAX, TL_STEP = 30, 5                      # age axis: 0 to 30 years, a grid line every 5
AGE_RANGE = re.compile(r'^\s*(\d+)\s*[-–]\s*(\d+)\s*years?\s*$')
AGE_ONE = re.compile(r'^\s*(\d+)\s*years?\s*$')


def f1(v: float) -> str:
    s_ = '%.2f' % v
    return s_.rstrip('0').rstrip('.')


def parse_age(t: str) -> Optional[Tuple[int, int]]:
    """'6-10 years' -> (6, 10); '9 years' -> (9, 9); anything else -> None."""
    m = AGE_RANGE.match(t)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = AGE_ONE.match(t)
    if m:
        return int(m.group(1)), int(m.group(1))
    return None


def meter(certainty: str, cls: str = 'mc-meter') -> str:
    """Four blocks, the first N filled (N = 1 for very low ... 4 for high). The word is said next to it."""
    n = CERT_BLOCKS.get(certainty, 0)
    return '<span class="%s m%d" aria-hidden="true">%s</span>' % (cls, n, '<i></i>' * 4)


# Hover help rows (static/mc.js) for certainty and for the marks on the age track, in the same
# format as the "How to read this" rows (which list the result words only).
MC_HOW_CERT = [('high', 'Several good studies agree; new research is unlikely to change this'),
               ('moderate', 'Fairly sure; new research could change it'),
               ('low', 'Limited evidence; new research could well change it'),
               ('very_low', 'Very unsure; treat it as a lead, not an answer')]
MC_HOW_MARK = [('bar', 'Bar', 'A range of marsh ages that studies looked at, coloured by the overall result '
                '(not the result at that age)'),
               ('pt', 'Short mark', 'A single marsh age that a study looked at'),
               ('tick', 'Dark line', 'A single marsh age, inside a range that was also studied'),
               ('none', 'Dashed box', 'The studies did not say how old their marshes were')]


def def_row(cls: str, term: str, meaning: str, tip: bool = False) -> str:
    """One "How to read this" row: a sample (drawn by CSS from cls) and the word, then what it means.
    In the card it is a <dt>/<dd> pair; in a hover tip, spans."""
    if tip:
        return ('<span class="mc-def %s"><span class="mc-dt">%s</span><span class="mc-dd">%s</span></span>'
                % (cls, term, meaning))
    return '<div class="mc-def %s"><dt>%s</dt><dd>%s</dd></div>' % (cls, term, meaning)


def result_term(f_direction: str) -> str:
    return '<i aria-hidden="true"></i>%s' % TL_WORD.get(f_direction, ('', words(f_direction)))[1]


def cert_term(c: str) -> str:
    return '%s%s' % (meter(c, 'mc-meter mc-smeter'), CERT_WORD[c])


def mark_term(kind: str, word: str) -> str:
    return '<i class="mc-samp mc-samp-%s" aria-hidden="true"></i>%s' % (kind, word)


def tip(inner: str) -> str:
    """Hover help: hidden in the page, shown next to its parent by static/mc.js."""
    return '<span class="mc-tt" hidden>%s</span>' % inner


def age_track(f: Finding, base: str) -> str:
    """The marsh ages a finding's studies looked at, on the 0-30 track: a bar per age range, a
    short bar for a single age, a tick for a single age that falls inside a range. A dashed box
    when no age is reported. Ages are also said as text (pack values, data-checked)."""
    tps = f.raw.get('time_points') or []
    ages = [(i, parse_age(t)) for i, t in enumerate(tps)]
    ranges = [a for _, a in ages if a and a[0] != a[1]]
    pct = lambda yr: min(yr, TL_MAX) * 100.0 / TL_MAX
    marks = []
    mark_def = {k: (w, m) for k, w, m in MC_HOW_MARK}

    def mark_tip(kind: str, i: int) -> str:
        w, m = mark_def[kind]
        return tip(def_row('mc-plain', mark_term(kind, w), m, tip=True) +
                   '<span class="mc-tnote">This one: %s</span>' % span('%s/time_points/%d' % (base, i), tps[i]))
    for i, a in sorted(((i, a) for i, a in ages if a), key=lambda x: x[1]):
        lo, hi = a
        if lo != hi:
            marks.append('<span class="mc-bar mc-tip" style="left:%s%%;width:%s%%">%s</span>'
                         % (f1(pct(lo)), f1(pct(hi) - pct(lo)), mark_tip('bar', i)))
        elif any(r[0] <= lo <= r[1] for r in ranges):
            marks.append('<span class="mc-tick mc-tip" style="left:%s%%">%s</span>' % (f1(pct(lo)), mark_tip('tick', i)))
        else:
            marks.append('<span class="mc-pt mc-tip" style="left:%s%%">%s</span>' % (f1(pct(lo)), mark_tip('pt', i)))
    said = ', '.join(span('%s/time_points/%d' % (base, i), t) for i, t in enumerate(tps))
    axis = ('<span class="mc-ax" aria-hidden="true">%s</span>'
            % ''.join('<span style="left:%s%%">%d</span>' % (f1(pct(y)), y) for y in range(0, TL_MAX + 1, 10)))
    if not marks:
        unparsed = (' <span class="sr-only">Marsh ages: %s</span>' % said) if tps else ''
        w, m = mark_def['none']
        return ('<div class="mc-ages"><span class="mc-none mc-tip">marsh age not reported%s%s</span></div>'
                % (unparsed, tip(def_row('mc-plain', mark_term('none', w), m, tip=True))))
    return ('<div class="mc-ages"><span class="mc-track">%s</span>%s<span class="sr-only">Marsh ages studied: %s'
            '</span></div>' % (''.join(marks), axis, said))


def split_text(f: Finding, base: str) -> str:
    """'2 of 3 studies behind' when the studies disagree, else '5 of 6 claims behind' when the
    claims do; nothing when all agree. Numbers are the pack's (data-checked)."""
    word = MC_SPLIT_WORD.get(f.direction)
    if not word:
        return ''
    sd, cd = f.raw.get('study_directions') or {}, f.raw.get('claim_directions') or {}
    if len(sd) > 1 and f.direction in sd:
        return ' · %s of %s studies %s' % (span(base + '/study_directions/' + f.direction, sd[f.direction]),
                                           span(base + '/studies', f.studies), word)
    if len(cd) > 1 and f.direction in cd and f.raw.get('claims'):
        return ' · %s of %s claims %s' % (span(base + '/claim_directions/' + f.direction, cd[f.direction]),
                                          span(base + '/claims', f.raw['claims']), word)
    return ''


def matched_cell(f: Finding, base: str) -> str:
    ans, word = MC_MATCHED.get(f.direction, (words(f.direction), ''))
    tps = f.raw.get('time_points') or []
    if f.direction == 'mixed':
        cd = f.raw.get('claim_directions') or {}
        bits = ['%s %s' % (span(base + '/claim_directions/' + d, n), MC_CLAIM_WORD.get(d, words(d)))
                for d, n in sorted(cd.items(), key=lambda x: -x[1])]
        if bits:
            bits[0] = bits[0].replace('</span> ', '</span> claims ', 1)
        sub = ', '.join(bits)
    else:
        sub = word
    # The marsh ages the studies looked at, youngest first, as the pack writes them (data-checked).
    # One result covers all of them: the pack does not give a result per age.
    order = sorted(range(len(tps)), key=lambda i: parse_age(tps[i]) or (999, 999))
    tail = ('at %s' % ', '.join(span('%s/time_points/%d' % (base, i), tps[i]) for i in order)
            if tps else 'age unknown')
    sub = '%s · %s' % (sub, tail) if sub else tail
    return ('<div class="mc-match"><span class="mc-mlab">Matched natural marshes yet? </span>'
            '<strong>%s</strong><span class="mc-msub">%s</span></div>' % (esc(ans), sub))


def timeline_chart(q: Question, popups: Dict[str, str], gaps_anchor: str = 'gaps-h') -> str:
    """The Q2 main view (Figma "current graph"): a key, "How to read this", one row per finding
    (compared with natural marshes, then older vs newer created marshes) and the takeaway. A
    row's outcome name opens a popup with the finding's full card (why that certainty, quotes).
    The same data follows as a table."""
    rank = {c: i for i, c in enumerate(CERT_ORDER)}
    groups = [('Compared with natural marshes', sorted(q.findings, key=lambda f: (
        not f.raw.get('lags'), rank.get(f.certainty, 9), MC_ORDER.get(f.direction, 9))), True)]
    if q.trends:
        groups.append(('Comparing older created marshes to newer ones', list(q.trends), False))
    allf = [f for _, fs, _ in groups for f in fs]
    if not allf or not any(f.raw.get('time_points') for f in allf):
        return ''
    qid = q.qid
    # "How to read this" (Figma frame "How to read this (dropdown)"): per chart group, each result
    # word that group uses, with its colour and what it means. Each row is also the hover help of
    # that result word; certainty and the age-track marks have hover help only (MC_HOW_CERT/MARK).
    how_groups = []
    for title, fs, matched in groups:
        defs = MC_HOW_REF if matched else MC_HOW_AGE
        seen, items = set(), []
        for f in fs:
            k = MC_KEY.get(f.direction, 'unclear')
            if f.direction in seen or f.direction not in defs:
                continue
            seen.add(f.direction)
            cls = 'mc-' + k
            items.append((MC_ORDER.get(f.direction, 9), def_row(cls, result_term(f.direction), defs[f.direction])))
        if items:
            how_groups.append('<div class="mc-hg"><p class="mc-hgt">%s</p><dl>%s</dl></div>'
                              % (esc(title), ''.join(h for _, h in sorted(items))))
    how = ('<details class="mc-how"><summary>How to read this</summary>%s</details>' % ''.join(how_groups)
           if how_groups else '')
    cert_tip = {c: def_row('mc-plain', cert_term(c), m, tip=True) for c, m in MC_HOW_CERT}

    keys = {MC_KEY.get(f.direction, 'unclear') for f in allf}
    legend = ''.join('<span class="mc-sw mc-%s"><i aria-hidden="true"></i>%s</span>' % (k, w)
                     for k, w in MC_LEGEND if k in keys)
    key = ('<div class="mc-key"><p><span class="mc-kh">Result:</span> %s</p>'
           '<p><span class="mc-kh">Certainty:</span> <span class="mc-meter mc-kmeter m4" aria-hidden="true">'
           '<i></i><i></i><i></i><i></i></span> More filled blocks = more certain (very low, low, moderate, high)</p></div>'
           % legend)
    ticks = ''.join('<span style="left:%s%%">%d</span>' % (f1(yr * 100.0 / TL_MAX), yr)
                    for yr in range(0, TL_MAX + 1, TL_STEP))
    head = ('<div class="mc-row mc-head" aria-hidden="true"><div class="mc-out">Outcome</div>'
            '<div class="mc-cert"><span class="mc-ch">Certainty (how sure are we?)</span>'
            '<span class="mc-clabs"><span>Very low</span><span>Low</span><span>Moderate</span><span>High</span></span></div>'
            '<div class="mc-ages"><span class="mc-ch">Marsh ages studied (years)</span><span class="mc-ticks">%s</span></div>'
            '<div class="mc-match">Matched natural marshes yet?</div></div>' % ticks)
    rows = [head]
    for title, fs, matched in groups:
        rows.append('<div class="mc-row mc-group%s"><div class="mc-out"><h3>%s</h3></div><div class="mc-cert"></div>'
                    '<div class="mc-ages"></div><div class="mc-match"></div></div>'
                    % ('' if matched else ' mc-nom', esc(title)))
        for i, f in enumerate(fs):
            base = '%s/%s' % (qid, f.slug)
            sym, word = TL_WORD.get(f.direction, ('', words(f.direction)))
            k = MC_KEY.get(f.direction, 'unclear')
            last = ' mc-last' if i == len(fs) - 1 else ''
            rows.append(
                '<div class="mc-row mc-%s%s%s">'
                '<div class="mc-out"><button type="button" class="mc-name" popovertarget="pop-%s">%s'
                '<span class="sr-only">: details and sources</span></button>'
                '<span class="mc-dir mc-tip"><span aria-hidden="true">%s</span> %s%s</span></div>'
                '<div class="mc-cert"><span class="mc-tip mc-cbox">%s<span class="mc-meta">%s · %s %s%s</span>%s</span></div>'
                '%s%s</div>'
                % (k, last, '' if matched else ' mc-nom', esc(f.slug), esc(f.outcome_label), sym,
                   span(base + '/direction', word),
                   tip(def_row('mc-' + k, result_term(f.direction),
                               (MC_HOW_REF if matched else MC_HOW_AGE).get(f.direction, ''), tip=True)),
                   meter(f.certainty),
                   span(base + '/certainty', CERT_WORD[f.certainty]), span(base + '/studies', f.studies),
                   plural(f.studies, 'study', 'studies'), split_text(f, base),
                   tip(cert_tip[f.certainty] + ('<span class="mc-tnote">Why this grade: %s</span>'
                                                % esc(f.certainty_rationale) if f.certainty_rationale else '')),
                   age_track(f, base), matched_cell(f, base) if matched else '<div class="mc-match"></div>'))
    chart = '<div class="mc-wrap"><div class="mc">%s</div></div>' % ''.join(rows)

    # takeaway: what the chart cannot say, from the pack
    sa = q.extra.get('short_answer') or {}
    take = []
    if sa.get('time_to_reference') is None:
        take.append('<p class="mc-take-h">Takeaway: how long full recovery takes is unknown.</p>')
    take.append('<p>Bars show the marsh ages that were studied, coloured by the overall result for that outcome. '
                'Results are pooled across studies, not reported age by age.</p>')
    if q.limitations:
        take.append('<p>%s A result measured at one age doesn’t show the trajectory.</p>'
                    % span('%s/limitations/0' % qid, q.limitations[0]))
    if q.gaps:
        labels = [g.outcome_label for g in q.gaps]
        some = ', '.join(esc(lbl[0].lower() + lbl[1:]) for lbl in labels[:3])
        take.append('<p>No evidence for %s %s, including %s. <a href="#%s">See Not studied</a>.</p>'
                    % (number_word(len(q.gaps)), plural(len(q.gaps), 'outcome', 'outcomes'), some, gaps_anchor))
    takeaway = '<div class="mc-take">%s</div>' % ''.join(take)

    # the table view: the same findings in the same two groups. A row opens the same popup as
    # the chart row; ages are listed youngest first, each as a pill (pack text, data-checked).
    tbodies = []
    for title, fs, matched in groups:
        trs = []
        for f in fs:
            base = '%s/%s' % (qid, f.slug)
            sym, word = TL_WORD.get(f.direction, ('', words(f.direction)))
            k = MC_KEY.get(f.direction, 'unclear')
            tps = f.raw.get('time_points') or []
            order = sorted(range(len(tps)), key=lambda i: (parse_age(tps[i]) or (999, 999), i))
            ages = (''.join('<span class="mc-age">%s</span>' % span('%s/time_points/%d' % (base, i), tps[i]) for i in order)
                    if tps else '<span class="mc-nr">not reported</span>')
            trs.append('<tr class="mc-trow mc-%s"><th scope="row"><button type="button" class="mc-name" '
                       'popovertarget="pop-%s">%s<span class="sr-only">: details and sources</span></button></th>'
                       '<td><span class="mc-tres"><i aria-hidden="true"></i><span aria-hidden="true">%s</span> %s</span></td>'
                       '<td><span class="mc-tcert">%s%s</span></td><td class="mc-tnum">%s</td><td>%s</td></tr>'
                       % (k, esc(f.slug), esc(f.outcome_label), sym, span(base + '/direction', word),
                          meter(f.certainty, 'mc-meter mc-smeter'), span(base + '/certainty', CERT_WORD[f.certainty]),
                          span(base + '/studies', f.studies), ages))
        tbodies.append('<tbody><tr class="mc-tgroup"><th scope="rowgroup" colspan="5">%s</th></tr>%s</tbody>'
                       % (esc(title), ''.join(trs)))
    tbl = ('<div class="mc-tview" role="region" aria-label="The chart as a table" tabindex="0">'
           '<table class="tl-table mc-table"><caption class="sr-only">The chart as a table: each finding, its overall '
           'result, certainty, number of studies and the marsh ages studied</caption><thead><tr>'
           '<th scope="col">Outcome</th><th scope="col">Result</th><th scope="col">Certainty</th>'
           '<th scope="col">Studies</th><th scope="col">Marsh ages studied</th></tr></thead>%s</table></div>'
           % ''.join(tbodies))
    # Chart | Table switch (static/mc.js shows it and hides the other view). Without script it
    # stays hidden and both views show, one under the other.
    switch = ('<div class="mc-switch" role="group" aria-label="View" hidden>'
              '<button type="button" data-view="mc-view-chart" aria-pressed="true">Chart</button>'
              '<button type="button" data-view="mc-view-table" aria-pressed="false">Table</button></div>')
    views = ('<div id="mc-view-chart" class="mc-view">%s</div><div id="mc-view-table" class="mc-view">%s</div>'
             % (chart, tbl))
    pops = ''.join(popups[f.slug] for f in allf)
    # heading (Figma "current graph"): a small label, the question in plain words, and the
    # answer to "how long?" when the pack has none
    title, sub = MC_TITLE.get(qid, ('Outcome by outcome', ''))
    if sa.get('time_to_reference') is not None:
        sub = ''
    head_html = ('<div class="mc-top"><p class="mc-eyebrow">Restoration evidence · %s</p><h2 id="timeline">%s</h2>%s</div>'
                 % (esc(qid.upper()), esc(title), '<p class="mc-sub">%s</p>' % esc(sub) if sub else ''))
    # .mc-section: on wide screens the chart runs almost the full page width, as in the Figma frame
    return ('<div class="mc-section">%s%s<div class="mc-tools">%s%s</div>%s%s</div>%s'
            % (head_html, key, how, switch, views, takeaway, pops))


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
        # "Lags" says the same as the "Behind" chip (the pack's lagging attributes are exactly the
        # findings below the reference), so the popup shows it only if the two ever disagree
        # (screen readers still hear "lags": the pack marks it and both say it in words)
        tag = ('' if not f.raw.get('lags') else
               '<span class="sr-only"> (lags behind natural marshes)</span>' if f.direction == 'below_reference' else
               ' <span class="lags">Lags</span>')
        extra = '<div class="when-wrap"><span class="mlabel">When measured</span> %s</div>' % when(f)
        return ('<div popover id="pop-%s" class="pop fpop cardpop" role="dialog" aria-label="%s">'
                '<button type="button" class="pop-x" popovertarget="pop-%s" popovertargetaction="hide">'
                '<span aria-hidden="true">×</span><span class="sr-only">Close</span></button>%s</div>'
                % (esc(f.slug), esc(f.label), esc(f.slug),
                   finding_card(data, f, sources, tag=tag, extra=extra, open_=True, labels=True)))

    popups = {f.slug: popup(f) for f in q.all_findings()}
    chart = timeline_chart(q, popups)
    if chart:
        main, jumps = chart + '<script src="static/mc.js" defer></script>', [('#timeline', 'Outcomes')]
    else:  # no ages in the data: cards as on any other page
        main = '<h2 id="compare">Findings</h2>' + cards(q.findings) + (cards(q.trends) if q.trends else '')
        jumps = [('#compare', 'Findings')]
    return question_page(data, prose, q, main, jumps=jumps, short=short)


def q3_cell_id(subject_id: str, outcome_id: str) -> str:
    return 'c-%s--%s-detail' % (slug(subject_id), slug(outcome_id))


OUTCOME_SLOT = '{outcome}'


def render_gapmap(data: SiteData, prose: Prose, q: Question, sources: List[SourcePage]) -> str:
    """GAPMAP layout (Q3 today). Main view: the gap map (sticky names) and the ten most studied. A filled
    cell, or a row's "?", opens a popup with that intervention's findings (one popup per row, to keep the
    page light); a cell opens straight onto its own card. Gaps are in the shared Not studied."""
    grid = data.grids[q.qid]
    qid = q.qid
    s = q.extra['summary']
    short = short_box('%s of %s combinations have been studied; %s of those by a single study. %s'
                      % (span('%s/summary/filled' % qid, s['filled']), span('%s/summary/cells' % qid, s['cells']),
                         span('%s/summary/thin' % qid, s['thin']), prose.short_answer[qid].html), 'short')
    # Figma "Q3 gap map" page, frame "C · Q2 layout, site colours": a titled grid of rounded boxes,
    # outcome names turned upright, an "Outcomes studied" column, then the key and the takeaway.
    ncols = len(grid['cols'])
    row_n = {rid: sum(1 for cid, _ in grid['cols'] if not isinstance(grid['cells'][(rid, cid)], Gap))
             for rid, _ in grid['rows']}
    none = sum(1 for n in row_n.values() if n == 0)
    counts = ('%s of %s treatment × outcome pairings have been studied; %s of those by a single study.'
              % (span('%s/summary/filled' % qid, s['filled']), span('%s/summary/cells' % qid, s['cells']),
                 span('%s/summary/thin' % qid, s['thin'])))
    none_txt = (' %s %s no studies at all.' % (number_word(none).capitalize(), plural(none, 'treatment has', 'treatments have'))
                if none else '')
    main = ('<section class="gm" aria-labelledby="map"><p class="gm-kicker">Gap map %s</p>'
            '<h2 id="map">Which grassland treatments have been studied, and for what?</h2>'
            '<p class="gm-sub">%s%s</p>' % (HELP_BTN, counts, none_txt))
    head = ''.join('<th scope="col"><span>%s</span></th>' % esc(lbl) for _, lbl in grid['cols'])
    trs, pops = [], []
    for rid, rlbl in grid['rows']:
        rpop = 'r-%s' % slug(rid)
        tds, items = [], []
        for cid, clbl in grid['cols']:
            item = grid['cells'][(rid, cid)]
            if isinstance(item, Gap):
                tds.append('<td class="empty" aria-label="Not studied">–</td>')  # 261 of these: kept minimal
                continue
            dens = item.raw.get('density', '')
            # a cell is a button: it opens its intervention's popup, on this combination's card
            # just the study count (colour + border say how many); certainty is in the popup card
            tds.append('<td class="d-%s"><button popovertarget="%s" data-open="%s">%s'
                       '<span class="sr-only"> %s</span></button></td>'
                       % (esc(dens), rpop, q3_cell_id(rid, cid), span('%s/%s/studies' % (qid, item.slug), item.studies),
                          esc(plural(item.studies, 'study', 'studies'))))
            items.append('<li id="%s">%s</li>' % (q3_cell_id(rid, cid), finding_card(
                data, item, sources, subject=False, level=4, quotes_shown=0, compact=True)))
        n_f = len(items)
        n_o = row_n[rid]
        tally = ('<td class="sum"><strong>%d of %d</strong><small>outcomes studied</small></td>' % (n_o, ncols)
                 if n_o else '<td class="sum none"><strong>Not studied</strong></td>')
        trs.append('<tr><th scope="row">%s</th>%s%s</tr>' % (esc(rlbl), ''.join(tds), tally))
        pops.append('<div popover id="%s" class="pop fpop rowpop" role="dialog" aria-label="%s">'
                    '<button type="button" class="pop-x" popovertarget="%s" popovertargetaction="hide">'
                    '<span aria-hidden="true">×</span><span class="sr-only">Close</span></button>'
                    '<p class="pop-h">%s</p><p class="cnt">%d studied, %d not studied (listed under Not studied)</p>'
                    '<ul class="cells">%s</ul><button type="button" class="show-all">Show all %d for %s</button></div>'
                    % (rpop, esc(rlbl), rpop, esc(rlbl), n_f, len(grid['cols']) - n_f, ''.join(items), n_f, esc(rlbl)))
    main += ('<p class="fs-row"><button type="button" class="fs-btn" data-fs="gapmap-wrap" hidden>'
             '<span aria-hidden="true">⤢</span> Full screen</button></p>'
             '<div class="grid-wrap" id="gapmap-wrap" role="region" aria-label="Gap map" tabindex="0"><table class="gapmap">'
             '<caption>Treatments (rows) by outcomes (columns): number of studies in each '
             'combination. Select a filled box for its details.</caption><thead><tr><td class="gm-corner">Treatment</td>%s'
             '<th scope="col" class="sum">Outcomes studied</th></tr></thead><tbody>%s</tbody></table></div>'
             '<dl class="key gm-key"><div><dt class="gm-k">Studies:</dt></div>'
             '<div><dt><span class="swatch d-thin" aria-hidden="true"></span> 1 study</dt></div>'
             '<div><dt><span class="swatch d-some" aria-hidden="true"></span> 2–3 studies</dt></div>'
             '<div><dt><span class="swatch d-dense" aria-hidden="true"></span> 4 or more</dt></div>'
             '<div><dt><span class="swatch empty" aria-hidden="true">–</span> Not studied</dt>'
             '<dd>nobody here tested it (not a negative result)</dd></div></dl>'
             '<p class="gm-note">The number is how many studies tested that pairing: research effort, not effect size. '
             'Select a box for its finding, how sure we can be, and its sources.</p>'
             '<div class="gm-take"><p><strong>Takeaway: most treatment–outcome pairings have never been studied, and many '
             'that have rest on a single study.</strong></p><p>%s of %s combinations studied; %s of those by one study.%s '
             'Blank is not evidence of no effect.</p></div></section>'
             % (head, ''.join(trs), s['filled'], s['cells'], s['thin'],
                (' %d %s no studies for any outcome.' % (none, plural(none, 'treatment has', 'treatments have'))) if none else ''))
    by_id = {f.id: f for f in q.findings}
    dense = []
    for fid in s.get('densest') or []:
        f = by_id[fid]
        d, c, n = finding_cells(f)
        dense.append('<li><a href="#%s">%s</a>: %s · %s · %s</li>' % (
            q3_cell_id(f.subject_id, f.outcome_id), esc(f.subject_label + ' × ' + f.outcome_label), d,
            span('%s/%s/certainty' % (qid, f.slug), certainty_text(f.certainty)), n))
    # the top 3 show; the rest are one click away
    more = ''
    if len(dense) > 3:
        more = ('<details class="more-densest"><summary>Show %d more</summary><ol class="densest" start="4">%s</ol></details>'
                % (len(dense) - 3, ''.join(dense[3:])))
    main += ('<h2 id="densest">Where the evidence is densest</h2><p>The pack\'s %s most-studied combinations, in its '
             'order.</p><ol class="densest">%s</ol>%s' % (number_word(len(dense)), ''.join(dense[:3]), more))
    main += ''.join(pops)
    jumps = [('#map', 'Gap map'), ('#densest', 'Most studied')]
    return question_page(data, prose, q, main, jumps=jumps, short=short, scripts=CHECKS_JS + FULLSCREEN_JS)


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


def _line(cls: str, width: int = 34) -> str:
    return ('<svg width="%d" height="12" aria-hidden="true"><line x1="0" y1="6" x2="%d" y2="6" class="lg %s"/></svg>'
            % (width, width, cls))


def _key_item(sample: str, word: str) -> str:
    return '<li>%s <span>%s</span></li>' % (sample, word)


def _key_group(title: str, items: List[str]) -> str:
    return '<div class="gkey-g"><h3>%s</h3><ul>%s</ul></div>' % (title, ''.join(items))


# The graph's key: one meaning per visual channel.
GRAPH_KEY = ''.join([
    _key_group('Colour + symbol = direction', [
        _key_item(_line('sw up'), '<b class="t-up">↑</b> increase'),
        _key_item(_line('sw down'), '<b class="t-down">↓</b> decrease'),
        _key_item(_line('sw mixed'), '<b class="t-mixed">⇅</b> mixed: studies disagree'),
        _key_item(_line('sw none'), '<b class="t-none">–</b> no effect found (<b>?</b> unclear)')]),
    _key_group('Thickness = number of studies', [
        _key_item(_line('w-1'), '1 study'), _key_item(_line('w-2'), '2–3'),
        _key_item(_line('w-3'), '4–6'), _key_item(_line('w-4'), '7 or more')]),
    _key_group('Line style = certainty', [
        _key_item(_line('w-2 high'), 'solid: high'), _key_item(_line('w-2 moderate'), 'long dashes: moderate'),
        _key_item(_line('w-2 low'), 'short dashes: low'), _key_item(_line('w-2 very_low'), 'very short dashes: very low')]),
    _key_group('Badges, just above each arrowhead', [
        '<li><span class="kb t-up">↑ 7</span> <span>direction and number of studies</span></li>',
        '<li><span class="kb t-mixed">⇅ ↑4 ↓1</span> <span>mixed: 4 studies found an increase, 1 a decrease; '
        'the others mixed or no effect. A zero is left out.</span></li>',
        '<li><span class="kb t-mixed">⇅</span> <span>mixed, no study clearly either way</span></li>']),
    _key_group('Shapes', [
        _key_item('<svg width="34" height="20" aria-hidden="true"><rect x="1" y="2" width="32" height="16" rx="3" '
                  'class="lg-box"/></svg>', 'something you do'),
        _key_item('<svg width="34" height="20" aria-hidden="true"><rect x="1" y="2" width="32" height="16" rx="3" '
                  'class="lg-box condition"/></svg>', 'a condition the treatments change'),
        _key_item('<svg width="34" height="20" aria-hidden="true"><rect x="1" y="2" width="32" height="16" rx="3" '
                  'class="lg-box outcome"/></svg>', 'an outcome'),
        _key_item('<svg width="34" height="20" aria-hidden="true"><path d="M1,10 L8,2 H26 L33,10 L26,18 H8 Z" '
                  'class="lg-box combination"/></svg>', 'two treatments applied together; thin lines join it '
                  'to each one'),
        _key_item('<svg width="34" height="14" aria-hidden="true"><line x1="0" y1="7" x2="34" y2="7" '
                  'class="lg sw up"/><circle cx="17" cy="7" r="5" class="lg-ring"/></svg>',
                  'moderation: a ring on an arrow means another treatment changes how strong that arrow is'),
        _key_item('<svg width="34" height="12" aria-hidden="true"><line x1="0" y1="6" x2="34" y2="6" '
                  'class="lg gapline"/></svg>', '“not studied”: looked for and not found. Not a negative '
                  'result.')]),
])


def matrix_view(g: Any, gp_: str) -> str:
    """The same arrows as a grid: what you do (and the conditions) as rows, the conditions and
    outcomes as columns. A cell shows the direction (symbol and colour), the number of studies
    and the certainty, and links to the arrow's evidence; an empty cell has no arrow."""
    rows, _ = order_rows(g)
    kind = {n['id']: n.get('kind') for n in g.nodes}
    label = {n['id']: n['label'] for n in g.nodes}
    combos = [k for k in rows[1] if kind[k] == 'combination']
    conds = [k for k in rows[1] if kind[k] != 'combination']
    cols = conds + rows[2]
    effects = {(e['source'], e['target']): e for e in g.edges if e.get('kind') == 'effect'}
    gaps = {(gp['source'], gp['target']): gp for gp in g.gaps}

    def cell(s: str, t: str) -> str:
        if s == t:
            return '<td class="mx self"><span aria-hidden="true">·</span><span class="sr-only">same box</span></td>'
        e = effects.get((s, t))
        if e is not None:
            n = e['studies']
            cert = certainty_text(e['certainty']).lower()
            words = '%s → %s: %s, %s certainty, %d %s' % (
                label[s], label[t], e['direction'].replace('_', ' '), cert, n, 'study' if n == 1 else 'studies')
            return ('<td class="mx d-%s"><a href="#e-%s" aria-label="%s"><span class="mx-main">'
                    '<span class="mx-sym">%s</span> %d</span><span class="mx-cert">%s</span></a></td>'
                    % (esc(e['direction']), esc(slug(e['id'])), esc(words), GRAPH_SYM[e['direction']], n, esc(cert)))
        gp = gaps.get((s, t))
        if gp is not None:
            return ('<td class="mx gap"><a href="#e-%s" aria-label="%s → %s: not studied">not studied</a></td>'
                    % (esc(slug(gp['id'])), esc(label[s]), esc(label[t])))
        return '<td class="mx none"><span class="sr-only">no arrow</span></td>'

    head = ('<tr><td></td><th scope="colgroup" colspan="%d">Conditions they change</th>'
            '<th scope="colgroup" colspan="%d">Seedling outcomes</th></tr>' % (len(conds), len(rows[2])))
    head += '<tr><th scope="col">Cause</th>%s</tr>' % ''.join('<th scope="col">%s</th>' % esc(label[c]) for c in cols)
    body = []
    for title, keys in (('Planting stock &amp; site treatments', rows[0] + combos), ('Conditions, as causes', conds)):
        body.append('<tr class="mx-group"><th scope="colgroup" colspan="%d">%s</th></tr>' % (len(cols) + 1, title))
        for k in keys:
            body.append('<tr><th scope="row">%s</th>%s</tr>' % (esc(label[k]), ''.join(cell(k, c) for c in cols)))
    mods = []
    for e in g.edges:
        if e.get('kind') == 'moderation':
            t = g.edge(e['target_edge'])
            mods.append('<a href="#e-%s">%s changes the effect of %s → %s</a> (%s %s, %d %s, %s certainty)'
                        % (esc(slug(e['id'])), esc(label[e['source']]), esc(label[t['source']]),
                           esc(label[t['target']]), GRAPH_SYM[e['direction']], e['direction'].replace('_', ' '),
                           e['studies'], 'study' if e['studies'] == 1 else 'studies',
                           esc(certainty_text(e['certainty']).lower())))
    note = ('<p class="mx-note">Not a cell in the grid: %s.</p>' % '; '.join(mods)) if mods else ''
    return ('<section id="matrix" class="gmatrix" aria-labelledby="matrix-h"><h2 id="matrix-h">Matrix view</h2>'
            '<p>The same arrows as a grid. Each cell shows the direction (symbol and colour), the number of '
            'studies and the certainty, and links to the evidence. An empty cell means there is no arrow.</p>'
            '<div class="table-wrap"><table class="matrix"><caption class="sr-only">Every arrow as a grid: '
            'causes in rows, what they act on in columns</caption><thead>%s</thead><tbody>%s</tbody></table></div>'
            '%s</section>' % (head, ''.join(body), note))


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
    body += ('<figure class="graph"><!--GRAPH--><figcaption>%s boxes linked by %s arrows, each a body of '
             'evidence, and %s %s looked for and not found. Select an arrow to read its evidence '
             'and sources.</figcaption>'
             '<div class="gkey" id="read" role="group" aria-labelledby="read-h"><h2 id="read-h">How to read the '
             'graph</h2>%s</div></figure>'
             % (span(gp_ + '/count/nodes', len(g.nodes)), span(gp_ + '/count/edges', len(g.edges)),
                span(gp_ + '/count/gaps', len(g.gaps)), plural(len(g.gaps), 'pairing', 'pairings'), GRAPH_KEY))
    body += matrix_view(g, gp_)
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
    jumps = [('#read', 'How to read it'), ('#matrix', 'Matrix view'), ('#arrows', 'Evidence behind each arrow'),
             ('#table', 'All arrows as a table'),
             ('%s.html' % qid, 'Back to the answer')]
    return page(data, gfile, 'Q%d graph · %s' % (n, name), 'The %s answer drawn as a causal graph, with the '
                'sources behind every arrow.' % name.lower().replace(' ', '-'), body, jumps=jumps,
                script='static/graph.js', wide=True)


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
        '<h1>Guide</h1>'
        '<nav class="tabs" aria-label="On this page"><ul><li><a href="#read">How to read this site</a></li>'
        '<li><a href="#certainty">Certainty</a></li>'
        '<li><a href="#data">Where the data comes from</a></li><li><a href="#limits">Limits</a></li>'
        '<li><a href="#about">About us</a></li></ul></nav>'
        '<section class="tab" aria-labelledby="read"><h2 id="read">How to read this site</h2>%%READKEY%%</section>'
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
    body = body.replace('%READKEY%', READ_KEY)
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
    jumps = [('#read', 'How to read this site'), ('#certainty', 'Certainty'), ('#data', 'Where the data comes from'),
             ('#limits', 'Limits'), ('#about', 'About us')]
    return page(data, 'method.html', 'Guide', 'How certainty is graded, what the direction '
                'words mean and where every number comes from.', body, jumps=jumps)


# --------------------------------------------------------------- entry

def render_site(data: SiteData, prose: Prose, out: str) -> List[str]:
    os.makedirs(os.path.join(out, 'static'), exist_ok=True)
    # only the hero pictures and cloud drawings this page template uses (hero-q<N>[-clouds].<ext>);
    # a big one is reported so page weight doesn't grow unnoticed
    heroes = [f for f in os.listdir(os.path.join(ROOT, 'static'))
              if re.fullmatch(r'hero-q\d+(?:-clouds)?\.(?:webp|avif|jpg|png|svg)', f)]
    for f in heroes:
        kb = os.path.getsize(os.path.join(ROOT, 'static', f)) // 1024
        if kb > 150:
            print('[build] warning: static/%s is %d KB; it is loaded on its question page' % (f, kb))
    for f in ['style.css', 'favicon.svg', 'graph.js', 'tree.js', 'ns.js', 'mc.js', 'problem.js', 'ov.js', 'pin.webp',
              'ov-wave.svg', 'home-flowers.webp', 'home-papers.webp', 'logo.svg'] + heroes:
        shutil.copyfile(os.path.join(ROOT, 'static', f), os.path.join(out, 'static', f))
    # bundled fonts (no font is loaded from the internet), sorted so builds are repeatable
    fonts = os.path.join(ROOT, 'static', 'fonts')
    if os.path.isdir(fonts):
        os.makedirs(os.path.join(out, 'static', 'fonts'), exist_ok=True)
        for f in sorted(os.listdir(fonts)):
            if f.endswith(('.woff2', '.txt')):
                shutil.copyfile(os.path.join(fonts, f), os.path.join(out, 'static', 'fonts', f))
    # small UI icons from the Figma file (chevrons of the Q2 "How to read this" dropdown)
    icons = os.path.join(ROOT, 'static', 'icons')
    if os.path.isdir(icons):
        os.makedirs(os.path.join(out, 'static', 'icons'), exist_ok=True)
        for f in sorted(os.listdir(icons)):
            if f.endswith('.svg'):
                shutil.copyfile(os.path.join(icons, f), os.path.join(out, 'static', 'icons', f))
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
