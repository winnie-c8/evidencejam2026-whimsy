"""Plain-language prose for each page.

MVP: templates only. Each slot is a ProseItem so a later LLM step can fill the
same slots and fall back to these templates on any failure.

A ProseItem carries `text` (plain) and `html` (the same sentence with every pack
number wrapped in a data-check span, ready to insert into a page).
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any, Dict

from load import Finding, SiteData

DIR_PHRASE = {
    'increase': 'studies found it increases', 'decrease': 'studies found it decreases',
    'mixed': 'studies disagree on', 'no_effect': 'studies found no clear effect on',
    'unclear': 'the direction is unclear for',
    'below_reference': 'created marshes are below natural ones for',
    'comparable': 'created marshes are comparable to natural ones for',
    'above_reference': 'created marshes are above natural ones for',
}

CERT_WORD = {'high': 'High', 'moderate': 'Moderate', 'low': 'Low', 'very_low': 'Very low'}

SHORT_ANSWER = {
    'q1': "Each finding below shows its direction, certainty and number of studies; "
          "open one to read the studies behind it.",
    'q3': "Most combinations have not been studied. Where evidence exists, many cells "
          "rest on a single study.",
}
DEFAULT_SHORT_ANSWER = ("Each finding below shows its direction, certainty and number of "
                        "studies; open one to read the studies behind it.")


@dataclass(frozen=True)
class ProseItem:
    text: str
    html: str
    source: str = 'template'
    reason: str = 'llm disabled'


@dataclass
class Prose:
    short_answer: Dict[str, ProseItem] = field(default_factory=dict)
    finding_sentence: Dict[str, ProseItem] = field(default_factory=dict)
    stats: Dict[str, Any] = field(default_factory=dict)


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _span(path: str, text: str) -> str:
    return '<span data-check="%s">%s</span>' % (_esc(path), _esc(text))


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def finding_template(f: Finding) -> ProseItem:
    base = "%s/%s" % (f.question, f.slug)
    cert = "%s certainty" % CERT_WORD[f.certainty]
    noun = "study" if f.studies == 1 else "studies"
    tail_t = " (%s, %d %s)." % (cert, f.studies, noun)
    tail_h = " (%s, %s %s)." % (_span(base + "/certainty", cert),
                                _span(base + "/studies", str(f.studies)), noun)
    outcome = f.outcome_label.lower()
    if f.kind == 'trend' and f.direction == 'no_effect':
        lead = "Studies found no clear change in %s as marshes age" % outcome
        return ProseItem(lead + tail_t, _esc(lead) + tail_h)
    phrase = DIR_PHRASE[f.direction]
    if f.reference:
        lead = _cap("%s %s" % (phrase, outcome))
    else:
        lead = "%s: %s %s" % (f.subject_label, phrase, outcome)
    return ProseItem(lead + tail_t, _esc(lead) + tail_h)


# ------------------------------------------------------------ short answers
# Built from the pack with fixed rules, no LLM. Each group of findings that share a
# direction and certainty is wrapped in <span data-group="<direction>/<certainty>">,
# and each finding in it is a link to its card; tests/check_independent.py checks
# every linked finding really has that direction and certainty.

CERT_ORDER = ['high', 'moderate', 'low', 'very_low']
# (verb for one subject, verb for several) -> "... increase(s) it"
GROUP_VERB = {
    'increase': ('increases it', 'increase it'),
    'decrease': ('decreases it', 'decrease it'),
    'no_effect': ('has no clear effect', 'have no clear effect'),
}
DIR_ORDER = ['increase', 'decrease', 'no_effect', 'mixed', 'unclear']


def _lower_first(s: str) -> str:
    # "Site preparation" -> "site preparation", but keep "PLFA" or "N fertilization" as is
    return s[:1].lower() + s[1:] if len(s) > 1 and s[1].islower() else s


def _join(items):
    items = list(items)
    if len(items) <= 1:
        return ''.join(items)
    return '%s and %s' % (', '.join(items[:-1]), items[-1])


def _link(f: Finding) -> str:
    return '<a href="%s.html#f-%s">%s</a>' % (_esc(f.question), _esc(f.slug), _esc(_lower_first(f.subject_label)))


def _group_phrase(direction: str, fs) -> tuple:
    """One clause for findings sharing a direction: (text, html)."""
    names_t = _join(_lower_first(f.subject_label) for f in fs)
    names_h = _join(_link(f) for f in fs)
    if direction in GROUP_VERB:
        verb = GROUP_VERB[direction][0 if len(fs) == 1 else 1]
        return '%s %s' % (names_t, verb), '%s %s' % (names_h, _esc(verb))
    word = 'mixed' if direction == 'mixed' else 'unclear'
    lead = 'results for '
    return lead + names_t + ' are ' + word, _esc(lead) + names_h + ' are ' + word


def effects_short_answer(q) -> ProseItem:
    """Q1-style questions: per outcome, what the best-supported findings say."""
    by_outcome: Dict[str, list] = {}
    for f in q.findings:
        by_outcome.setdefault(f.outcome_id, []).append(f)
    texts, htmls = [], []
    for fs in by_outcome.values():
        outcome = fs[0].outcome_label
        top = min(CERT_ORDER.index(f.certainty) for f in fs)
        best = [f for f in fs if CERT_ORDER.index(f.certainty) == top]
        cert = CERT_WORD[CERT_ORDER[top]].lower() + ' certainty'
        parts_t, parts_h = [], []
        for d in DIR_ORDER:
            grp = [f for f in best if f.direction == d]
            if not grp:
                continue
            t, h = _group_phrase(d, grp)
            parts_t.append(t)
            parts_h.append('<span data-group="%s/%s">%s</span>' % (d, CERT_ORDER[top], h))
        sent_t = '%s: with %s, %s.' % (outcome, cert, '; '.join(parts_t))
        sent_h = ('<strong>%s:</strong> <span data-cert="%s">with %s, %s</span>.'
                  % (_esc(outcome), CERT_ORDER[top], _esc(cert), '; '.join(parts_h)))
        rest = [f for f in fs if f not in best]
        n_mixed = sum(f.direction == 'mixed' for f in rest)
        if rest and n_mixed * 2 > len(rest):
            extra = ' The less certain findings are mostly mixed.'
            sent_t += extra
            sent_h += _esc(extra)
        texts.append(sent_t)
        htmls.append(sent_h)
    # one bullet per outcome, so it reads at a glance
    return ProseItem(' '.join(texts), '<ul class="sa">%s</ul>' % ''.join('<li>%s</li>' % h for h in htmls))


def gap_map_short_answer(q) -> ProseItem:
    """Q3-style questions: the gap message, plus what the most-studied cells say."""
    base = SHORT_ANSWER['q3']
    by_id = {f.id: f for f in q.findings}
    dense = [by_id[i] for i in (q.extra['summary'].get('densest') or []) if i in by_id]
    if not dense:
        return ProseItem(base, _esc(base))
    n_mixed = sum(f.direction == 'mixed' for f in dense)
    lo = min(dense, key=lambda f: f.studies)
    hi = max(dense, key=lambda f: f.studies)
    count = NUMBER_WORD.get(len(dense), str(len(dense)))
    if n_mixed == len(dense):
        lead = 'All %s of the most-studied combinations' % count
        tail = ' have mixed results: even the best-studied interventions give inconsistent answers.'
    else:
        lead = '%s of the %s most-studied combinations' % (_cap(NUMBER_WORD.get(n_mixed, str(n_mixed))), count)
        tail = ' have mixed results.'
    rng_t = ' (%d to %d studies each)' % (lo.studies, hi.studies)
    rng_h = ' (%s to %s studies each)' % (_span('q3/%s/studies' % lo.slug, str(lo.studies)),
                                          _span('q3/%s/studies' % hi.slug, str(hi.studies)))
    text = '%s %s%s%s' % (base, lead, rng_t, tail)
    html_ = '%s <a href="q3.html#densest">%s</a>%s%s' % (_esc(base), _esc(lead), rng_h, _esc(tail))
    return ProseItem(text, html_)


NUMBER_WORD = {1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six', 7: 'seven',
               8: 'eight', 9: 'nine', 10: 'ten'}


def short_answer_template(qid: str, data: SiteData) -> ProseItem:
    q = data.questions[qid]
    sa = q.extra.get('short_answer') or {}
    note = sa.get('time_to_reference_note')
    if note:
        return ProseItem(note, _span("%s/short_answer/time_to_reference_note" % qid, note))
    if 'summary' in q.extra:
        return gap_map_short_answer(q)
    if q.findings and not any(f.reference for f in q.findings):
        return effects_short_answer(q)
    text = SHORT_ANSWER.get(qid, DEFAULT_SHORT_ANSWER)
    return ProseItem(text, _esc(text))


def summarize_all(data: SiteData, args: Any = None) -> Prose:
    prose = Prose()
    for qid, q in data.questions.items():
        prose.short_answer[qid] = short_answer_template(qid, data)
        for f in q.all_findings():
            prose.finding_sentence[f.slug] = finding_template(f)
    prose.stats = {
        'llm': False,
        'template': len(prose.short_answer) + len(prose.finding_sentence),
        'llm_filled': 0,
    }
    return prose
