"""Build-time LLM summaries for the home page (one per question), with a safe fallback.

The model is called only when BRINE_URL, BRINE_MODEL and BRINE_API_KEY are all set (README:
"Read the LLM endpoint, model and key from the environment"). It gets a short fact sheet built
from the answer pack and writes two plain sentences. Its text is used only if it passes
validate(): no number that is not in the fact sheet, no invented durations, no wording that turns
a gap into a negative result, and a sane length. Otherwise the template sentence is used, so the
build never depends on the network. Standard library only; small prompts and max_tokens to keep
token use (and so build energy) low.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Dict, List, Optional, Tuple

from load import EFFECTS, GAPMAP, Question, SiteData

CERT = {'high': 'high', 'moderate': 'moderate', 'low': 'low', 'very_low': 'very low'}
DIR = {'increase': 'increases', 'decrease': 'decreases', 'mixed': 'mixed results', 'no_effect': 'no clear effect',
       'unclear': 'unclear', 'below_reference': 'behind natural marshes', 'above_reference': 'ahead of natural marshes',
       'comparable': 'level with natural marshes'}
# words that would make "not studied" read as a failed or harmful result
NEGATIVE = ('ineffective', 'does not work', "doesn't work", 'no effect on', 'harmful', 'fails', 'failed', 'useless')
MAX_CHARS = 420
SYSTEM = ('You write for restoration practitioners who are not scientists. Using ONLY the facts given, write '
          'exactly two short plain-English sentences summarising what the evidence says for this question. '
          'Refer to each item by the exact name given before its colon. Keep each item\'s direction and '
          'certainty exactly as given, in the same clause as its name. Do not add numbers, years, durations or '
          'claims that are not in the facts. "Not studied" means nobody tested it, never that it does not work. '
          'Reply with the two sentences only.')

# Words that state a direction, and which pack directions each one is consistent with. A clause
# of the reply that uses one must name a fact whose direction it fits (see check_claims).
DIR_WORDS = [
    (r'\bno (?:clear )?(?:effect|change|difference)\b', {'no_effect', 'comparable'}),
    (r'\b(?:increas\w*|rais\w*|improv\w*|boost\w*|helps?|helped|helping|benefit\w*)\b', {'increase', 'above_reference'}),
    (r'\b(?:decreas\w*|reduc\w*|lowers?|lowered|lowering|hurts?|harms?|harmed|hold\w* (?:\w+ )?back|worsen\w*)\b',
     {'decrease', 'below_reference'}),
    (r'\b(?:behind|lag\w*|below|trail\w*|fall short)\b', {'below_reference', 'decrease'}),
    (r'\b(?:ahead|above|exceed\w*|outperform\w*)\b', {'above_reference', 'increase'}),
    (r'\b(?:level with|comparable|similar|match\w*|catch\w* up)\b', {'comparable', 'no_effect'}),
    (r'\b(?:mixed|disagree\w*|inconsistent|conflicting)\b', {'mixed'}),
    (r'\b(?:unclear|uncertain direction)\b', {'unclear'}),
]
CERT_RE = re.compile(r'\b(very low|high|moderate|low)(?:-| )certainty\b|\bcertainty (?:is |of )?(very low|high|moderate|low)\b')


class Fact:
    """One line of the fact sheet: the names that point to it, its directions and certainties."""
    def __init__(self, line: str, names: List[str], dirs=(), certs=()):
        self.line, self.names = line, [n.lower() for n in names if n]
        self.dirs, self.certs = set(dirs), set(certs)


def _names(label: str) -> List[str]:
    """How a reply may name an item: its label without brackets, and its first two words."""
    base = re.sub(r'\s*\(.*?\)', '', label).strip().lower()
    words = [w for w in re.split(r'[\s,&/]+', base) if w]
    head = ' '.join(words[:1] if len(words) > 1 and words[1] in ('or', 'and', 'of', 'at', 'in', 'to') else words[:2])
    return [base, head] if head and head != base else [base]


def facts(data: SiteData, q: Question) -> Tuple[str, List[str], List[Fact]]:
    """A compact fact sheet for one question, the numbers the model may repeat, and the facts
    each clause of its reply is checked against."""
    kind = data.kinds.get(q.qid)
    lines = ['Question: ' + q.text]
    nums: List[str] = []
    fl: List[Fact] = []
    if kind == GAPMAP and 'summary' in q.extra:
        s = q.extra['summary']
        lines.append('%s of %s intervention-outcome combinations have been studied; %s of those by a single study.'
                     % (s['filled'], s['cells'], s['thin']))
        lines.append('%d combinations have not been studied (nobody tested them).' % len(q.gaps))
        nums += [str(s['filled']), str(s['cells']), str(s['thin']), str(len(q.gaps))]
        by_id = {f.id: f for f in q.findings}
        dense = [by_id[i] for i in (s.get('densest') or []) if i in by_id]
        if dense:
            n_mixed = sum(f.direction == 'mixed' for f in dense)
            line = ('Most-studied combinations: all %d have mixed results.' % len(dense) if n_mixed == len(dense)
                    else 'Most-studied combinations: %d of the %d have mixed results.' % (n_mixed, len(dense)))
            lines.append(line)
            nums += [str(len(dense)), str(n_mixed)]
            fl.append(Fact(line, ['most-studied', 'most studied', 'best-studied', 'best studied'],
                           {f.direction for f in dense}, {f.certainty for f in dense}))
    else:
        sa = q.extra.get('short_answer') or {}
        if 'time_to_reference' in sa:
            line = 'How long until created marshes match natural ones: the studies cannot say.'
            lines.append(line)
            fl.append(Fact(line, ['how long', 'cannot say', "can't say", 'catch up'], {'comparable'}))
        firm = [f for f in q.all_findings() if f.certainty in ('high', 'moderate')]
        for f in firm:
            name = f.outcome_label if f.reference or f.kind == 'trend' else f.subject_label
            line = '- %s: %s (%s certainty, %d %s%s)' % (
                name, DIR.get(f.direction, f.direction), CERT[f.certainty], f.studies,
                'study' if f.studies == 1 else 'studies', '' if (f.reference or f.kind == 'trend') else ', on ' + f.outcome_label)
            lines.append(line)
            nums.append(str(f.studies))
            fl.append(Fact(line, _names(name), {f.direction}, {f.certainty}))
        rest = [f for f in q.all_findings() if f not in firm]
        if rest:
            levels = [CERT[c] for c in ('high', 'moderate', 'low', 'very_low') if any(f.certainty == c for f in rest)]
            line = '%d other findings have %s certainty.' % (len(rest), ' or '.join(levels))
            lines.append(line)
            nums.append(str(len(rest)))
            fl.append(Fact(line, ['other', 'less certain', 'remaining', 'rest'],
                           {f.direction for f in rest}, {f.certainty for f in rest}))
        if q.gaps:
            lines.append('%d pairing(s) not studied.' % len(q.gaps))
            nums.append(str(len(q.gaps)))
    return '\n'.join(lines), nums, fl


def check_claims(text: str, fl: List[Fact]) -> Optional[str]:
    """Hard rule 1: every direction or certainty the reply states must belong to a fact named in the
    same clause. Fails closed: a clause that states one without naming a fact is rejected."""
    for clause in re.split(r'[.;:]\s+|[.;]$|, (?:and|but|while|whereas) ', text.lower()):
        clause = clause.strip()
        if not clause:
            continue
        dirs = set()
        for rx, ok in DIR_WORDS:
            if re.search(rx, clause):
                dirs.add(frozenset(ok))
        certs = {(m.group(1) or m.group(2)).replace(' ', '_') for m in CERT_RE.finditer(clause)}
        if not dirs and not certs:
            continue
        hit = [f for f in fl if any(n in clause for n in f.names)]
        if not hit:
            return 'states a result without naming a fact: %r' % clause[:60]
        allowed_d = set().union(*(f.dirs for f in hit))
        allowed_c = set().union(*(f.certs for f in hit))
        for ok in dirs:
            if not ok & allowed_d:
                return 'direction not in the facts: %r' % clause[:60]
        if certs - allowed_c:
            return 'certainty not in the facts: %r' % clause[:60]
    return None


def validate(text: str, allowed: List[str], fl: Optional[List[Fact]] = None) -> Optional[str]:
    """Why the model's text cannot be used, or None if it is fine."""
    t = text.strip()
    if not t:
        return 'empty'
    if len(t) > MAX_CHARS:
        return 'too long'
    low = t.lower()
    if re.search(r'\byears?\b|\bmonths?\b', low):
        return 'mentions a duration'
    for w in NEGATIVE:
        if w in low:
            return 'negative wording: %r' % w
    for n in re.findall(r'\d+(?:\.\d+)?', t):
        if n not in allowed:
            return 'number %s not in the facts' % n
    if '<' in t or '>' in t:
        return 'markup'
    if fl is not None:
        return check_claims(t, fl)
    return None


def ask(fact_sheet: str, timeout: float = 60.0) -> str:
    """One chat completion from the LiteLLM (OpenAI-compatible) endpoint."""
    url = os.environ['BRINE_URL'].rstrip('/')
    if not url.endswith('/chat/completions'):
        url += '/chat/completions' if url.endswith('/v1') else '/v1/chat/completions'
    body = json.dumps({
        'model': os.environ['BRINE_MODEL'],
        'messages': [{'role': 'system', 'content': SYSTEM},
                     {'role': 'user', 'content': fact_sheet + '\n/no_think'}],
        'temperature': 0.2, 'max_tokens': 160,
    }).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json', 'Authorization': 'Bearer ' + os.environ['BRINE_API_KEY']})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    text = out['choices'][0]['message'].get('content') or ''
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.S)   # Qwen3 reasoning, if any
    return ' '.join(text.split())


def enabled() -> bool:
    return all(os.environ.get(k) for k in ('BRINE_URL', 'BRINE_MODEL', 'BRINE_API_KEY'))


def home_summaries(data: SiteData, templates: Dict[str, str], use_llm: bool = True) -> Dict[str, Tuple[str, str]]:
    """{qid: (text, source)}: the model's summary where it passed validate(), else the template."""
    out: Dict[str, Tuple[str, str]] = {}
    on = use_llm and enabled()
    for qid, q in data.questions.items():
        out[qid] = (templates[qid], 'template')
        if not on:
            continue
        sheet, nums, fl = facts(data, q)
        try:
            text = ask(sheet)
        except Exception as exc:  # network, auth, timeout, bad JSON: keep the template
            print('[build] llm %s: request failed (%s); template used' % (qid, type(exc).__name__))
            continue
        why = validate(text, nums, fl)
        if why:
            print('[build] llm %s: rejected (%s); template used' % (qid, why))
            continue
        out[qid] = (text, 'llm')
        print('[build] llm %s: summary written by %s' % (qid, os.environ['BRINE_MODEL']))
    return out
