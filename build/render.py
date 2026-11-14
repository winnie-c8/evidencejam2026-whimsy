"""Render the static pages (the Q1 SVG is added afterwards by graph_svg.py).

Every value from the pack is escaped with html.escape(quote=True). Every pack
number, direction and certainty sits in a data-check span that check.py
verifies against the answer files.
"""
from __future__ import annotations

import datetime
import html
import os
import shutil
import sys
from string import Template
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Tuple

from load import (CERTAINTIES, EFFECT_DIRECTIONS, REFERENCE_DIRECTIONS, Finding, Gap,
                  Question, Quote, SiteData, slug)
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
    pred_pos, pred_neg = PREDICATE.get(q.predicate, (words(q.predicate), 'not ' + words(q.predicate)))
    rows = [
        ('Claim', claim_sentence(q, check_prefix)),
        ('Relation', esc(('not ' if q.negated else '') + words(q.predicate))),
        ('Study design', esc(', '.join(words(t) for t in q.evidence_types) or 'not given')),
        ('Compared with', esc(COMPARATOR.get(q.comparator or '', words(q.comparator) or 'not given'))),
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


def source_page_link(sources: List[SourcePage], quotes: Iterable[Quote], *, fname: str, id_prefix: str,
                     check_prefix: str, label: str, back: str, back_text: str, description: str) -> str:
    """Add a page with these quotes (open, so the sentence shows at once) to sources; return a link to it."""
    boxes = ''.join(evidence_box(q, i + 1, id_prefix, check_prefix, open_=True) for i, q in enumerate(quotes))
    back_link = '<p class="back"><a href="%s">%s</a></p>' % (esc(back), esc(back_text))
    body = ('<h1>Sources: %s</h1>%s%s<div class="sources">%s</div>%s'
            % (esc(label), back_link, SOURCES_NOTE, boxes, back_link))
    sources.append(SourcePage(fname, 'Sources · ' + label, description, body))
    return ('<a class="srclink" href="%s">Read the sources<span class="sr-only"> for %s</span></a>'
            % (esc(fname), esc(label)))


def finding_sources(sources: List[SourcePage], f: Finding, qid: str) -> str:
    return source_page_link(sources, f.quotes, fname='sources-%s.html' % f.slug, id_prefix='ev-' + f.slug,
                            check_prefix=qid, label=f.label, back='%s.html#f-%s' % (qid, f.slug),
                            back_text='Back to the finding',
                            description='The quoted sentences behind one finding.')


def gap_marker(g: Gap, id_: Optional[str] = None) -> str:
    return ('<div class="gap" role="note" id="%s"><strong>Not studied:</strong> %s. '
            '<span class="searched">Searched for: %s</span></div>'
            % (esc(id_ or 'gap-' + g.slug), esc(g.label), esc(g.searched_for)))


def limits_box(prefix: str, limitations: Iterable[str], rule: Optional[str],
               how_built: Optional[str], heading: str = 'Read this first') -> str:
    items = ''.join('<li>%s</li>' % span('%s/limitations/%d' % (prefix, i), t)
                    for i, t in enumerate(limitations))
    built = ''
    if rule or how_built:
        built = ('<details class="built"><summary>How this answer was built</summary>'
                 '<p>Certainty rule: <code>%s</code> (<a href="method.html#certainty">explained</a>)</p>'
                 '<p>%s</p></details>' % (esc(rule or 'not given'), esc(how_built or '')))
    hid = 'limits-' + esc(prefix)
    return ('<section class="limits" aria-labelledby="%s"><h2 id="%s">%s: what this answer '
            'cannot tell you</h2><ul>%s</ul>%s</section>' % (hid, hid, esc(heading), items, built))


def finding_cells(f: Finding) -> Tuple[str, str, str]:
    base = '%s/%s' % (f.question, f.slug)
    return (direction_badge(f.direction, base + '/direction'),
            certainty_badge(f.certainty, f.certainty_rationale, f.label, base),
            counts(base, f.studies, f.claims))


def finding_row(f: Finding, sentence_html: str, row_header: str, cells: List[str],
                evidence_html: str) -> str:
    d, c, n = finding_cells(f)
    base = '%s/%s' % (f.question, f.slug)
    tds = ''.join('<td>%s</td>' % x for x in cells + [d, c, n, evidence_html])
    ncols = 1 + len(cells) + 4
    return ('<tr id="f-%s" class="finding"><th scope="row">%s</th>%s</tr>'
            '<tr class="sub"><td colspan="%d"><p>%s</p><p>%s</p></td></tr>'
            % (esc(f.slug), row_header, tds, ncols, sentence_html,
               vote_split(base, f.study_directions, f.reference)))


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
<header class="site"><nav aria-label="Main"><ul>$nav</ul></nav></header>
<main id="main" tabindex="-1">
$body
</main>
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
    items = [('index.html', 'Home')]
    for qid, q in data.questions.items():
        items.append(('%s.html' % qid, '%s · %s' % (qid.upper(), question_name(q))))
        if qid == 'q1' and data.q1_graph is not None:
            items.append(('q1-graph.html', 'Q1 graph'))
    items.append(('method.html', 'Method'))
    return items


def build_date() -> str:
    sde = os.environ.get('SOURCE_DATE_EPOCH')
    if sde and sde.isdigit():
        return datetime.datetime.fromtimestamp(int(sde), datetime.timezone.utc).strftime('%Y-%m-%d')
    return datetime.date.today().isoformat()


def page(data: SiteData, filename: str, title: str, description: str, body: str,
         script: Optional[str] = None) -> str:
    nav = []
    for href, label in nav_items(data):
        cur = ' aria-current="page"' if href == filename else ''
        nav.append('<li><a href="%s"%s>%s</a></li>' % (href, cur, esc(label)))
    rule = next((q.rule for q in data.questions.values() if q.rule), 'unknown')
    tag = '<script src="%s" defer></script>\n' % esc(script) if script else ''
    return SHELL.substitute(title=esc(title), description=esc(description), nav=''.join(nav),
                            body=body, rule=esc(rule), date=build_date(), script=tag)


# --------------------------------------------------------------- pages

def render_index(data: SiteData, prose: Prose) -> str:
    cards = []
    for qid, q in data.questions.items():
        graph = ''
        if qid == 'q1' and data.q1_graph is not None:
            graph = ' · <a href="q1-graph.html">See it as a causal graph</a>'
        cards.append(
            '<article class="card" aria-labelledby="card-%s"><h2 id="card-%s">%s</h2>'
            '<p class="q">%s</p><p class="who"><strong>For:</strong> %s</p>'
            '<p class="short"><strong>Short answer:</strong> %s</p>'
            '<p><a href="%s.html">Read the answer<span class="sr-only"> to %s</span></a>%s</p></article>'
            % (esc(qid), esc(qid), esc('%s · %s' % (qid.upper(), question_name(q))), esc(q.text),
               esc(AUDIENCE.get(qid, DEFAULT_AUDIENCE)), prose.short_answer[qid].html,
               esc(qid), esc(question_name(q)), graph))
    body = ('<h1>Restoration evidence, in plain words</h1>'
            '<p class="lead">This site works offline and answers %s practitioner questions from a '
            'fixed body of research, showing how sure we can be of each finding and where nothing has '
            'been studied.</p>%s'
            '<p><a href="method.html">How to read these answers and where the numbers come from</a></p>'
            % (number_word(len(data.questions)), ''.join(cards)))
    return page(data, 'index.html', 'Restoration evidence', 'Plain answers to restoration questions, '
                'with certainty, gaps and sources.', body)


def number_word(n: int) -> str:
    return {1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six'}.get(n, str(n))


def q_header(q: Question, prose: Prose, skip_short: bool = False) -> str:
    out = '<h1>%s</h1>' % esc(q.text)
    if not skip_short:
        out += '<p class="short"><strong>Short answer:</strong> %s</p>' % prose.short_answer[q.qid].html
    return out


def gaps_section(q: Question, heading: str = 'Not studied') -> str:
    if not q.gaps:
        return ''
    return ('<section aria-labelledby="gaps-h"><h2 id="gaps-h">%s</h2>'
            '<p>These pairings were looked for and not found in this body of research. That is not '
            'evidence that the treatment fails; nobody here tested it.</p>%s</section>'
            % (esc(heading), ''.join(gap_marker(g) for g in q.gaps)))


def render_q1(data: SiteData, prose: Prose, q: Question, sources: List[SourcePage]) -> str:
    g = data.q1_graph
    rows = []
    for f in q.findings:
        ev = ''
        if f.slug in data.graph_join:
            ev += ('<a href="q1-graph.html#e-%s">On the graph<span class="sr-only">: %s</span></a>'
                   % (esc(slug(data.graph_join[f.slug])), esc(f.label)))
        ev += finding_sources(sources, f, q.qid)
        rows.append(finding_row(f, prose.finding_sentence[f.slug].html, esc(f.subject_label),
                                [esc(f.outcome_label)], ev))
    body = q_header(q, prose)
    body += limits_box(q.qid, q.limitations, q.rule, q.how_built)
    if g is not None:
        body += '<p class="graph-link"><a href="q1-graph.html">See this as a causal graph</a></p>'
    body += ('<h2>Findings</h2>' + table(
        'Each planting-stock trait or site factor and what studies found for seedling survival or growth',
        ['Factor', 'Outcome', 'Direction', 'Certainty', 'Studies', 'Evidence'], ''.join(rows)))
    body += interactions_section(data, q)
    body += gaps_section(q)
    return page(data, 'q1.html', 'Q1 · Tree planting', q.text, body)


def interactions_section(data: SiteData, q: Question) -> str:
    inter = q.extra.get('interactions') or []
    if not inter:
        return ''
    g = data.q1_graph
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
                        shown = 'Shown as %s: <a href="q1-graph.html#e-%s">%s</a>.' % (
                            kind, esc(slug(e['id'])), esc(edge_title(g, e)))
                        break
        rows.append('<tr id="ix-%d"><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            i + 1, evidence_box(quote, 1, 'ev-ix-%d' % (i + 1), q.qid, open_=True),
            direction_badge(it['direction'], '%s/interactions/%d/direction' % (q.qid, i)), shown))
    return ('<section aria-labelledby="ix-h"><h2 id="ix-h">Combined treatments</h2>'
            '<p>These claims are about two treatments together, or one treatment changing another\'s '
            'effect. They are listed one by one, not pooled into the findings above.</p>%s</section>'
            % table('Claims about combined treatments', ['Claim', 'Direction', 'Shown on the graph as'],
                    ''.join(rows), 'interactions'))


def render_q2(data: SiteData, prose: Prose, q: Question, sources: List[SourcePage]) -> str:
    sa = q.extra.get('short_answer') or {}
    note = sa.get('time_to_reference_note') or ''
    ttr = sa.get('time_to_reference')
    if ttr is not None:
        callout = ('<p><strong>Time to reach the reference:</strong> %s</p><p>%s</p>'
                   % (span('q2/short_answer/time_to_reference', ttr),
                      span('q2/short_answer/time_to_reference_note', note)))
    else:
        callout = ('<p><strong>How long? This body of research cannot say.</strong></p><p>%s</p>'
                   % span('q2/short_answer/time_to_reference_note', note))
    body = ('<h1>%s</h1><div class="callout" role="note" aria-label="How long">%s</div>'
            % (esc(q.text), callout))
    if prose.short_answer[q.qid].text != note:
        body += '<p class="short"><strong>Short answer:</strong> %s</p>' % prose.short_answer[q.qid].html
    body += limits_box(q.qid, q.limitations, q.rule, q.how_built)
    lag = sa.get('lagging_attributes') or []
    if lag:
        body += ('<h2>Attributes that lag behind natural marshes</h2><ul class="lagging">%s</ul>'
                 % ''.join('<li>%s</li>' % span('q2/short_answer/lagging_attributes/%d' % i, a)
                           for i, a in enumerate(lag)))

    def when(f: Finding) -> str:
        tps = f.raw.get('time_points') or []
        if not tps:
            return '<span class="muted">No marsh age given</span>'
        return '<ul class="when">%s</ul>' % ''.join(
            '<li>%s</li>' % span('q2/%s/time_points/%d' % (f.slug, i), t) for i, t in enumerate(tps))

    def rows(fs: Iterable[Finding]) -> str:
        out = []
        for f in fs:
            head = esc(f.outcome_label)
            if f.raw.get('lags'):
                head += ' <span class="lags">Lags</span>'
            ev = finding_sources(sources, f, q.qid)
            out.append(finding_row(f, prose.finding_sentence[f.slug].html, head, [when(f)], ev))
        return ''.join(out)

    body += ('<h2>Created marshes compared with natural ones</h2>'
             '<p class="note">“When measured” lists the ages of the marshes studied, not a time to '
             'recovery.</p>')
    body += table('Each attribute of a created or restored marsh compared with a natural reference wetland',
                  ['Attribute', 'When measured', 'Direction', 'Certainty', 'Studies', 'Evidence'],
                  rows(q.findings))
    if q.trends:
        body += '<h2>Change as marshes age</h2>'
        body += table('How each attribute changes with time since the marsh was created or restored',
                      ['Attribute', 'When measured', 'Direction', 'Certainty', 'Studies', 'Evidence'],
                      rows(q.trends))
    body += gaps_section(q)
    return page(data, 'q2.html', 'Q2 · Created marshes', q.text, body)


def q3_cell_id(subject_id: str, outcome_id: str) -> str:
    return 'c-%s--%s-detail' % (slug(subject_id), slug(outcome_id))


OUTCOME_SLOT = '{outcome}'


def row_search_template(grid: Dict[str, Any], rid: str) -> Optional[str]:
    """The pack's "searched for" sentence for a Q3 row's gaps, with the outcome replaced by
    {outcome}, when every gap in the row uses the same sentence apart from its outcome; else None.
    Read from the pack's own text (nothing typed in here), so it says it once per row instead of
    261 times. If the pack's wording ever stops fitting, each gap keeps its full sentence, and the
    build says so."""
    templates = set()
    for cid, clbl in grid['cols']:
        item = grid['cells'][(rid, cid)]
        if isinstance(item, Gap):
            if item.searched_for.count(clbl) != 1:
                templates.add(None)
            else:
                templates.add(item.searched_for.replace(clbl, OUTCOME_SLOT))
    if len(templates) == 1 and None not in templates:
        return templates.pop()
    if templates:
        print('[build] note: Q3 row %s: gaps\' "searched for" wording differs, showing each in full' % rid,
              file=sys.stderr)
    return None


def render_q3(data: SiteData, prose: Prose, q: Question, sources: List[SourcePage]) -> str:
    grid = data.q3_grid
    s = q.extra['summary']
    body = q_header(q, prose, skip_short=True)
    body += ('<p class="short"><strong>Short answer:</strong> %s of %s combinations have been studied; '
             '%s of those by a single study. %s</p>'
             % (span('q3/summary/filled', s['filled']), span('q3/summary/cells', s['cells']),
                span('q3/summary/thin', s['thin']), prose.short_answer['q3'].html))
    body += limits_box(q.qid, q.limitations, q.rule, q.how_built)
    body += ('<h2>Gap map</h2><dl class="key"><div><dt><span class="swatch empty" aria-hidden="true">–</span>'
             ' Not studied</dt><dd>No study in this body of research tested the pairing. Not a negative '
             'result.</dd></div><div><dt><span class="swatch d-thin" aria-hidden="true"></span> thin</dt>'
             '<dd>1 study</dd></div><div><dt><span class="swatch d-some" aria-hidden="true"></span> some</dt>'
             '<dd>2–3 studies</dd></div><div><dt><span class="swatch d-dense" aria-hidden="true"></span> '
             'dense</dt><dd>4 or more studies</dd></div></dl>'
             '<p class="note">Each filled cell shows its number of studies and density word. Study counts '
             'measure research effort, not effect size. Select a cell to read its finding.</p>')
    head = ''.join('<th scope="col"><span>%s</span></th>' % esc(lbl) for _, lbl in grid['cols'])
    trs = []
    for rid, rlbl in grid['rows']:
        tds = []
        for cid, clbl in grid['cols']:
            item = grid['cells'][(rid, cid)]
            if isinstance(item, Gap):
                tds.append('<td class="empty" aria-label="Not studied" title="Not studied: %s">–</td>'
                           % esc(item.label))
            else:
                dens = item.raw.get('density', '')
                tds.append('<td class="d-%s"><a href="#%s">%s <span class="sr-only">%s, </span>%s</a></td>'
                           % (esc(dens), q3_cell_id(rid, cid), span('q3/%s/studies' % item.slug, item.studies),
                              esc(plural(item.studies, 'study', 'studies')), esc(dens)))
        trs.append('<tr><th scope="row">%s</th>%s</tr>' % (esc(rlbl), ''.join(tds)))
    body += ('<div class="grid-wrap" role="region" aria-label="Gap map" tabindex="0"><table class="gapmap">'
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
            span('q3/%s/certainty' % f.slug, certainty_text(f.certainty)), n))
    body += ('<h2>Where the evidence is densest</h2><p>The pack\'s ten most-studied combinations, in its '
             'order.</p><ol class="densest">%s</ol>' % ''.join(dense))

    body += '<h2>Every combination</h2>'
    for rid, rlbl in grid['rows']:
        items = []
        template = row_search_template(grid, rid)
        for cid, clbl in grid['cols']:
            item = grid['cells'][(rid, cid)]
            cell_id = q3_cell_id(rid, cid)
            if isinstance(item, Gap):
                if template is not None:
                    # what was searched for is said once for the row (below the heading)
                    items.append('<li id="%s"><div class="gap" role="note" id="gap-%s"><strong>Not studied:'
                                 '</strong> %s</div></li>' % (cell_id, esc(item.slug), esc(clbl)))
                else:
                    items.append('<li id="%s">%s</li>' % (cell_id, gap_marker(item)))
            else:
                f = item
                d, c, n = finding_cells(f)
                items.append(
                    '<li id="%s"><div class="cell-finding" id="f-%s"><h4>%s</h4>'
                    '<div class="badges">%s %s %s <span class="density">%s</span></div><p>%s</p><p>%s</p>%s'
                    '</div></li>' % (
                        cell_id, esc(f.slug), esc(clbl), d, c, n, esc(f.raw.get('density', '')),
                        prose.finding_sentence[f.slug].html,
                        vote_split('q3/' + f.slug, f.study_directions, f.reference),
                        finding_sources(sources, f, q.qid)))
        note = ''
        if template is not None:
            note = ('<p class="searched" data-template="%s">“Not studied” below means this was searched for and '
                    'nothing was found: %s.</p>' % (esc(template), esc(template.replace(OUTCOME_SLOT, 'that outcome'))))
        body += ('<section class="row-detail" aria-labelledby="r-%s"><h3 id="r-%s">%s</h3>%s'
                 '<ul class="cells">%s</ul></section>'
                 % (esc(slug(rid)), esc(slug(rid)), esc(rlbl), note, ''.join(items)))
    return page(data, 'q3.html', 'Q3 · Grassland gaps', q.text, body)


def render_generic(data: SiteData, prose: Prose, q: Question, sources: List[SourcePage]) -> str:
    """Any future qN file gets a page with no code change."""
    def rows(fs: Iterable[Finding]) -> str:
        return ''.join(finding_row(f, prose.finding_sentence[f.slug].html, esc(f.subject_label),
                                   [esc(f.outcome_label)],
                                   finding_sources(sources, f, q.qid)) for f in fs)
    body = q_header(q, prose) + limits_box(q.qid, q.limitations, q.rule, q.how_built)
    body += '<h2>Findings</h2>' + table('Findings', ['Factor', 'Outcome', 'Direction', 'Certainty',
                                                     'Studies', 'Evidence'], rows(q.findings))
    if q.trends:
        body += '<h2>Trends</h2>' + table('Trends', ['Factor', 'Outcome', 'Direction', 'Certainty',
                                                     'Studies', 'Evidence'], rows(q.trends))
    body += gaps_section(q)
    return page(data, '%s.html' % q.qid, '%s · %s' % (q.qid.upper(), question_name(q)), q.text, body)


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


def render_graph_page(data: SiteData, sources: List[SourcePage]) -> str:
    g = data.q1_graph
    q1 = data.questions.get('q1')
    body = ('<h1>Tree planting as a causal graph</h1>'
            '<p class="lead">Each arrow is a body of evidence. Select one to read its sources.</p>'
            '<p>Planting-stock traits and site treatments (%s) act on seedling survival and growth '
            '(%s), directly and through the conditions they change (middle). ' % (
                ('top', 'bottom') if GRAPH_FLOW == 'down' else ('left', 'right')) +
            'A table of every arrow follows the graph.</p>')
    body += ('<h2>How to read the graph</h2><dl class="legend">'
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
             % (span('q1graph/count/nodes', len(g.nodes)), span('q1graph/count/edges', len(g.edges)),
                span('q1graph/count/gaps', len(g.gaps)), plural(len(g.gaps), 'pairing', 'pairings')))
    body += ('<p class="callout paths" role="note">A route through a middle box joins separate bodies of '
             'evidence. It is not one tested effect.</p>')
    body += limits_box('q1graph', g.limitations, g.raw.get('rule'), g.raw.get('how_built'),
                       heading='Before you trace a path')
    if g.set_aside:
        items = []
        for s in g.set_aside:
            where = ''
            if q1 is not None:
                for i, it in enumerate(q1.extra.get('interactions') or []):
                    if it.get('edge_id') == s.get('edge_id'):
                        where = ' <a href="q1.html#ix-%d">Read the claim</a>.' % (i + 1)
            items.append('<li>%s: %s.%s</li>' % (esc(s.get('edge_id')), esc(s.get('why')), where))
        body += ('<h2>Claim set aside</h2><p>Not drawn on the graph:</p><ul>%s</ul>' % ''.join(items))

    body += '<h2>Evidence behind each arrow</h2>'
    for e in g.edges:
        es = slug(e['id'])
        base = 'q1graph/%s' % es
        title = edge_title(g, e)
        quotes = data.edge_index.get(e['id'], ())
        boxes = source_page_link(sources, quotes, fname='sources-e-%s.html' % es, id_prefix='ev-e-' + es,
                                 check_prefix='q1graph', label=title, back='q1-graph.html#e-' + es,
                                 back_text='Back to the graph',
                                 description='The quoted sentences behind one arrow on the Q1 graph.')
        finding = ''
        for fs, eid in data.graph_join.items():
            if eid == e['id']:
                finding = ('<p>This arrow is the finding <a href="q1.html#f-%s">on the Q1 answer page</a>.</p>'
                           % esc(fs))
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
        base = 'q1graph/%s' % es
        rows.append('<tr><th scope="row"><a href="#e-%s">%s</a></th><td>%s</td><td>%s</td><td>%s</td></tr>'
                    % (es, esc(edge_title(g, e)), direction_badge(e['direction'], base + '/direction'),
                       span(base + '/certainty', certainty_text(e['certainty'])),
                       counts(base, e['studies'], e['claims'])))
    body += '<h2>All arrows as a table</h2>' + table(
        'Every arrow on the graph, with the same data as text',
        ['Arrow', 'Direction', 'Certainty', 'Studies'], ''.join(rows), 'all-edges')
    return page(data, 'q1-graph.html', 'Q1 graph · Tree planting', 'The tree-planting answer drawn as a '
                'causal graph, with the sources behind every arrow.', body, script='static/graph.js')


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
        '<h1>How to read these answers</h1>'
        '<h2>Where the numbers come from</h2>'
        '<p>%s The answer pack pools those claims into findings with simple, visible rules: no '
        'language model and no statistical modelling.</p>'
        '<p>Every direction, certainty grade and study count on this site is read from the pack\'s answer '
        'files when the site is built, and a check compares each one on every page with the pack before '
        'the site is published. Nothing is typed in by hand.</p>'
        '<h2 id="certainty">How certainty is graded</h2>'
        '<p>The pack uses rule <code>%s</code>. In plain words:</p>'
        '<ol><li>Start from the best study design in the body of evidence. A randomized experiment '
        'against an untreated control starts high. Other randomized, quasi-experimental and controlled '
        'long-term designs start moderate. Observational studies start low. Modelling and case studies '
        'start very low.</li>'
        '<li>Go down one step for a single study, one if studies disagree, and one if most claims '
        'report no comparison.</li>'
        '<li>Go up one step if three or more studies agree, and one if there is both evidence of '
        'mechanism and evidence that the treatment made a difference.</li>'
        '<li>A single study never rises above moderate.</li></ol>'
        '<p>Every grade comes with its reasoning: select “Why?” next to any certainty grade.</p>'
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
        'pathway strength.</p>'
        % (src, esc(rule),
           direction_badge('increase'), direction_badge('decrease'), direction_badge('mixed'),
           direction_badge('no_effect'), direction_badge('unclear'), direction_badge('below_reference'),
           direction_badge('comparable'), direction_badge('above_reference')))
    return page(data, 'method.html', 'Method · How to read', 'How certainty is graded, what the direction '
                'words mean and where every number comes from.', body)


# --------------------------------------------------------------- entry

def render_site(data: SiteData, prose: Prose, out: str) -> List[str]:
    os.makedirs(os.path.join(out, 'static'), exist_ok=True)
    for f in ('style.css', 'favicon.svg', 'graph.js'):
        shutil.copyfile(os.path.join(ROOT, 'static', f), os.path.join(out, 'static', f))
    sources: List[SourcePage] = []
    pages: Dict[str, str] = {'index.html': render_index(data, prose)}
    for qid, q in data.questions.items():
        fn = {'q1': render_q1, 'q2': render_q2, 'q3': render_q3}.get(qid, render_generic)
        pages['%s.html' % qid] = fn(data, prose, q, sources)
    if data.q1_graph is not None:
        pages['q1-graph.html'] = render_graph_page(data, sources)
    pages['method.html'] = render_method(data)
    for sp in sources:
        if sp.fname in pages:
            raise RuntimeError('two pages named %s' % sp.fname)
        pages[sp.fname] = page(data, sp.fname, sp.title, sp.description, sp.body)
    for name, text in pages.items():
        with open(os.path.join(out, name), 'w', encoding='utf-8') as fh:
            fh.write(text)
    return list(pages)
