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
          'Do not add numbers, years, durations or claims that are not in the facts. Keep each certainty word '
          'next to the finding it belongs to. "Not studied" means nobody tested it, never that it does not work. '
          'Reply with the two sentences only.')


def facts(data: SiteData, q: Question) -> Tuple[str, List[str]]:
    """A compact fact sheet for one question, and the numbers the model may repeat."""
    kind = data.kinds.get(q.qid)
    lines = ['Question: ' + q.text]
    nums: List[str] = []
    if kind == GAPMAP and 'summary' in q.extra:
        s = q.extra['summary']
        lines.append('%s of %s intervention-outcome combinations have been studied; %s of those by a single study.'
                     % (s['filled'], s['cells'], s['thin']))
        lines.append('%d combinations have not been studied (nobody tested them).' % len(q.gaps))
        lines.append('The ten most-studied combinations all have mixed results.')
        nums += [str(s['filled']), str(s['cells']), str(s['thin']), str(len(q.gaps)), 'ten', '10']
    else:
        sa = q.extra.get('short_answer') or {}
        if 'time_to_reference' in sa:
            lines.append('How long until created marshes match natural ones: the studies cannot say.')
        firm = [f for f in q.all_findings() if f.certainty in ('high', 'moderate')]
        for f in firm:
            lines.append('- %s: %s (%s certainty, %d %s)' % (
                f.label.split(': ', 1)[-1] if f.reference or f.kind == 'trend' else f.subject_label + ' on ' + f.outcome_label,
                DIR.get(f.direction, f.direction), CERT[f.certainty], f.studies, 'study' if f.studies == 1 else 'studies'))
            nums.append(str(f.studies))
        rest = len(q.all_findings()) - len(firm)
        if rest:
            lines.append('%d other findings have low or very low certainty.' % rest)
            nums.append(str(rest))
        if q.gaps:
            lines.append('%d pairing(s) not studied.' % len(q.gaps))
            nums.append(str(len(q.gaps)))
    return '\n'.join(lines), nums


def validate(text: str, allowed: List[str]) -> Optional[str]:
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
        sheet, nums = facts(data, q)
        try:
            text = ask(sheet)
        except Exception as exc:  # network, auth, timeout, bad JSON: keep the template
            print('[build] llm %s: request failed (%s); template used' % (qid, type(exc).__name__))
            continue
        why = validate(text, nums)
        if why:
            print('[build] llm %s: rejected (%s); template used' % (qid, why))
            continue
        out[qid] = (text, 'llm')
        print('[build] llm %s: summary written by %s' % (qid, os.environ['BRINE_MODEL']))
    return out
