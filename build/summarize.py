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


def short_answer_template(qid: str, data: SiteData) -> ProseItem:
    q = data.questions[qid]
    sa = q.extra.get('short_answer') or {}
    note = sa.get('time_to_reference_note')
    if note:
        return ProseItem(note, _span("%s/short_answer/time_to_reference_note" % qid, note))
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
