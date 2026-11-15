"""Build-time LLM summaries for the home page (one per question), with a safe fallback.

The model is called only when BRINE_URL, BRINE_MODEL and BRINE_API_KEY are all set (README:
"Read the LLM endpoint, model and key from the environment"). It gets a short fact sheet built
from the answer pack and writes three plain sentences: the answer, the firmest evidence, the limit.
Its text is used only if it passes validate(): every direction and certainty it states belongs to
the item it names, no number that is not in the fact sheet, no durations, no overclaiming, no
wording that turns a gap into a negative result. Otherwise the template sentence is used, so the
build never depends on the network. Standard library only; three small calls with max_tokens set
to keep token use (and so build energy) low.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Dict, List, Optional, Tuple

from load import COMPARISON, GAPMAP, Question, SiteData

FIRM = ('high', 'moderate')
CERT = {'high': 'high', 'moderate': 'moderate', 'low': 'low', 'very_low': 'very low'}
EFFECT = {'increase': 'increases it', 'decrease': 'decreases it', 'mixed': 'mixed results (the studies disagree)',
          'no_effect': 'no clear effect (tested, nothing found)', 'unclear': 'direction unclear'}
REF = {'below_reference': 'behind natural marshes', 'above_reference': 'ahead of natural marshes',
       'comparable': 'level with natural marshes', 'mixed': 'mixed results (the studies disagree)',
       'unclear': 'unclear'}
TREND = {'increase': 'rises as marshes age', 'decrease': 'falls as marshes age',
         'no_effect': 'no clear change as marshes age', 'mixed': 'mixed results as marshes age (the studies disagree)',
         'unclear': 'unclear as marshes age'}
DENSEST = ['most-studied', 'most studied', 'best-studied', 'best studied', 'densest']

MAX_CHARS = 640
MAX_SENTENCES = 3
SYSTEM = (
    'You write the home-page summary of one research question for restoration practitioners '
    '(conservation staff, consultants) who are not scientists. Use ONLY the facts given.\n\n'
    'Write exactly three plain-English sentences, about 70 words in total, following the PLAN:\n'
    '1. Answer the question as it was asked.\n'
    '2. Give the firmest evidence. Name each item exactly as written before its colon, with its direction, '
    'and put its certainty in brackets straight after it, for example "site preparation gives mixed results '
    '(high certainty)". Never merge certainties ("high and moderate certainty"). An item can have different '
    'results for different outcomes: give each outcome its own clause.\n'
    '3. Say what this evidence cannot tell the reader.\n\n'
    'Meanings you must keep:\n'
    '- "mixed" means the studies disagree. It does not mean the treatment sometimes works.\n'
    '- "no clear effect" means it was tested and nothing was found.\n'
    '- "not studied" means nobody tested it. Never say or imply that it does not work.\n'
    '- Certainty (high, moderate, low, very low) is how far the evidence can be trusted, not how big '
    'the effect is. Never raise, lower or generalise it, and never call evidence strong, weak, proven '
    'or clear.\n\n'
    'Do not add numbers, years, durations, advice or causes that are not in the facts. Write numbers '
    'as digits.\n\n'
    'Style: write like a field ecologist talking to a colleague, in plain everyday words. Write item names '
    'in lower case (unless one starts the sentence), with "and" instead of "&" and "or" instead of "/". '
    'Say "most studied", not "densest" or "graph". No dashes, no semicolons, no lists, headings, markdown '
    'or abbreviations, and no filler such as "notably", "importantly", "highlights" or "it is worth noting". '
    'Reply with the three sentences only.')

# Words that state a direction, and which pack directions each one is consistent with. A clause
# of the reply that uses one must name items whose direction it fits (see check_claims).
DIR_WORDS = [
    (r'\bno (?:clear )?(?:effect|change|difference)\b', {'no_effect', 'comparable'}),
    (r'\b(?:increas\w*|rais\w*|ris(?:e|es|ing)|improv\w*|boost\w*|helps?|helped|helping|benefit\w*)\b',
     {'increase', 'above_reference'}),
    (r'\b(?:decreas\w*|reduc\w*|lowers?|lowered|lowering|hurts?|harms?|harmed|hold\w* (?:\w+ )?back|worsen\w*'
     r'|falls?|drops?|declin\w*)\b', {'decrease', 'below_reference'}),
    (r'\b(?:behind|lag\w*|below|trail\w*|fall short)\b', {'below_reference', 'decrease'}),
    (r'\b(?:ahead|above|exceed\w*|outperform\w*)\b', {'above_reference', 'increase'}),
    (r'\b(?:level with|comparable|similar|match\w*|catch\w* up)\b', {'comparable', 'no_effect'}),
    (r'\b(?:mixed|disagree\w*|inconsistent|conflicting)\b', {'mixed'}),
    (r'\b(?:unclear|uncertain direction)\b', {'unclear'}),
]
CERT_RE = re.compile(r'\b(very low|high|moderate|low)(?:-| )certainty\b|\bcertainty (?:is |of )?(very low|high|moderate|low)\b')
# words that would make "not studied" read as a failed or harmful result
NEGATIVE = ('ineffective', 'does not work', "doesn't work", 'no effect on', 'harmful', 'fails', 'failed', 'useless')
# claims stronger than any grade in the pack, or advice the pack doesn't give
OVERCLAIM = re.compile(r'\b(?:proven|proves?|clearly|clear evidence|definitely|certainly|always|guarantee\w*|'
                       r'conclusive\w*|strong(?:ly)?|weak(?:ly)?|robust|well[- ](?:established|supported)|'
                       r'will|should|must|recommend\w*|best practice)\b')
# reads as machine-written: dashes, and stock filler phrases
STYLE = re.compile(r'[\u2012-\u2015]|\s-\s|--|\b(?:notably|importantly|crucial(?:ly)?|delve\w*|underscor\w*|'
                   r'highlight\w*|landscape|comprehensive|it is worth noting|it is important to note|'
                   r'in summary|overall|furthermore|moreover|additionally)\b')
TIMELINE = re.compile(r'\b(?:years?|months?|decades?|eventually|quickly|rapidly|soon|slowly|long[- ]term|short[- ]term)\b')
NUMBER_WORDS = {w: i for i, w in enumerate(
    'zero _ two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen '
    'seventeen eighteen nineteen twenty'.split()) if w != '_'}
NUMBER_WORDS.update({'thirty': 30, 'forty': 40, 'fifty': 50, 'hundred': 100})


class Fact:
    """One line of the fact sheet: the item it is about (key), the names that point to it, its
    directions and certainties, and the outcome words that tell its findings apart."""
    def __init__(self, line: str, key: str, names: List[str], dirs=(), certs=(), outcomes=(), exclusive=False):
        self.line, self.key = line, key
        self.names = [n.lower() for n in names if n]
        self.dirs, self.certs, self.outcomes = set(dirs), set(certs), set(outcomes)
        self.exclusive = exclusive   # combined treatments: when named, the clause is about them alone


def _names(label: str) -> List[str]:
    """How a reply may name an item: its label without brackets, its first part, its first two words."""
    base = re.sub(r'\s*\(.*?\)', '', label).strip().lower()
    seg = re.split(r'\s*(?:&|/|,|\+| or | and )\s*', base)[0].strip()
    two = ' '.join(seg.split()[:2])
    said = base.replace(' & ', ' and ').replace(' / ', ' or ')   # how a plain sentence writes it
    return list(dict.fromkeys(n for n in (base, said, seg, two) if len(n) > 3))


def _studies(n: int) -> str:
    return '%d %s' % (n, 'study' if n == 1 else 'studies')


def _words(label: str) -> set:
    return {w for w in re.findall(r'[a-z]+', label.lower()) if len(w) > 3}


def empty_lines(q: Question) -> Tuple[List[str], int, List[str], int]:
    """Gap map: interventions with no studies on any outcome, the number of outcomes, outcomes no
    intervention was studied for, the number of interventions."""
    subs: Dict[str, List[int]] = {}
    outs: Dict[str, List[int]] = {}
    for f in q.findings:
        subs.setdefault(f.subject_label, [0, 0])[0] += 1
        outs.setdefault(f.outcome_label, [0, 0])[0] += 1
    for g in q.gaps:
        subs.setdefault(g.subject_label, [0, 0])[1] += 1
        outs.setdefault(g.outcome_label, [0, 0])[1] += 1
    return ([k for k, v in subs.items() if v[0] == 0], len(outs),
            [k for k, v in outs.items() if v[0] == 0], len(subs))


def combined(data: SiteData, qid: str) -> List[Tuple[List[str], str, dict]]:
    """Graph edges from a combination node (two treatments together) with high or moderate certainty:
    (member labels, target label, edge)."""
    g = data.graphs.get(qid)
    out = []
    for e in (g.edges if g else ()):
        if e.get('kind') != 'effect' or e.get('certainty') not in FIRM:
            continue
        src = g.node(e['source'])
        if src.get('kind') != 'combination':
            continue
        members = [g.node(m)['label'] for m in src.get('members') or []]
        out.append((members, g.node(e['target'])['label'], e))
    return out


def facts(data: SiteData, q: Question) -> Tuple[str, List[str], List[Fact]]:
    """A compact fact sheet for one question, the numbers the model may repeat, and the facts
    each clause of its reply is checked against."""
    kind = data.kinds.get(q.qid)
    lines = ['Question: ' + q.text]
    nums: List[str] = []
    fl: List[Fact] = []

    def add(line: str, fact: Optional[Fact] = None, *ns) -> None:
        lines.append(line)
        nums.extend(str(n) for n in ns)
        if fact:
            fl.append(fact)

    sa = q.extra.get('short_answer') or {}
    if kind == GAPMAP and 'summary' in q.extra:
        s = q.extra['summary']
        lines.insert(0, 'PLAN: sentence 1 says where evidence is missing, naming the interventions and outcomes '
                        'with no studies at all. Sentence 2 says where it is densest and what those results show. '
                        'Sentence 3 says that an empty cell means nobody tested it.')
        add('%s of %s intervention-outcome combinations have been studied; %s of those by a single study.'
            % (s['filled'], s['cells'], s['thin']), None, s['filled'], s['cells'], s['thin'])
        add('%d combinations have not been studied (nobody tested them).' % len(q.gaps), None, len(q.gaps))
        rows, n_out, cols, n_sub = empty_lines(q)
        if rows:
            line = '- %d of the %d interventions, not studied for any of the %d outcomes: %s' % (
                len(rows), n_sub, n_out, '; '.join(rows))
            add(line, Fact(line, 'empty-rows', [n for r in rows for n in _names(r)]), n_out, len(rows), n_sub)
        if cols:
            line = '- Not measured for any of the %d interventions: %s' % (n_sub, '; '.join(cols))
            add(line, Fact(line, 'empty-cols', [n for c in cols for n in _names(c)]), n_sub, len(cols))
        by_id = {f.id: f for f in q.findings}
        dense = [by_id[i] for i in (s.get('densest') or []) if i in by_id]
        if dense:
            n_mixed = sum(f.direction == 'mixed' for f in dense)
            head = ('all %d have mixed results (the studies disagree)' % len(dense) if n_mixed == len(dense)
                    else '%d of the %d have mixed results (the studies disagree)' % (n_mixed, len(dense)))
            line = 'Most-studied combinations: %s.' % head
            add(line, Fact(line, 'densest', DENSEST, {f.direction for f in dense}, {f.certainty for f in dense}),
                len(dense), n_mixed)
            for f in dense[:3]:
                line = '- %s on %s: %s (%s certainty, %s)' % (f.subject_label, f.outcome_label, EFFECT[f.direction],
                                                              CERT[f.certainty], _studies(f.studies))
                add(line, Fact(line, 'cell:' + f.subject_id, _names(f.subject_label), {f.direction}, {f.certainty}),
                    f.studies)
    elif kind == COMPARISON:
        if 'time_to_reference' in sa:
            lines.insert(0, 'PLAN: sentence 1 says the studies cannot say how long. Sentence 2 names the attributes '
                            'that differ from natural marshes, with their certainty. Sentence 3 says how little '
                            'else is known.')
            line = 'How long until created marshes match natural ones: the studies cannot say.'
            add(line, Fact(line, 'how-long', ['how long', 'cannot say', "can't say", 'catch up'], {'comparable'}))
        for f in q.findings:
            if f.certainty in FIRM:
                line = '- %s: %s (%s certainty, %s)' % (f.outcome_label, REF.get(f.direction, EFFECT.get(f.direction)),
                                                      CERT[f.certainty], _studies(f.studies))
                add(line, Fact(line, f.outcome_id, _names(f.outcome_label), {f.direction}, {f.certainty}), f.studies)
        for f in q.trends:
            if f.certainty in FIRM:
                line = '- As marshes age, %s: %s (%s certainty, %s)' % (f.outcome_label, TREND[f.direction],
                                                                      CERT[f.certainty], _studies(f.studies))
                add(line, Fact(line, f.outcome_id, _names(f.outcome_label), {f.direction}, {f.certainty}), f.studies)
        _rest(q, add)
        if q.gaps:
            labels = [g.outcome_label for g in q.gaps]
            line = '- Never compared with natural marshes (nobody tested it), %d attributes: %s' % (
                len(labels), '; '.join(labels))
            add(line, Fact(line, 'gaps', [n for lb in labels for n in _names(lb)]), len(labels))
    else:
        lines.insert(0, 'PLAN: sentence 1 names what helps or holds back the outcome with high certainty. '
                        'Sentence 2 covers the rest of the question: mixed results and combined treatments. '
                        'Sentence 3 says what is less certain or not studied.')
        for f in q.findings:
            if f.certainty in FIRM:
                line = '- %s, effect on %s: %s (%s certainty, %s)' % (f.subject_label, f.outcome_label,
                                                                    EFFECT[f.direction], CERT[f.certainty],
                                                                    _studies(f.studies))
                add(line, Fact(line, f.subject_id, _names(f.subject_label), {f.direction}, {f.certainty},
                               _words(f.outcome_label)), f.studies)
        for members, target, e in combined(data, q.qid):
            line = '- %s combined with %s, effect on %s: %s (%s certainty, %s)' % (
                members[0], ' and '.join(members[1:]), target, EFFECT[e['direction']], CERT[e['certainty']],
                _studies(e['studies']))
            add(line, Fact(line, 'combo:' + e['id'], ['combined', 'together', 'combination'], {e['direction']},
                           {e['certainty']}, _words(target), exclusive=True), e['studies'])
        _rest(q, add)
        for g in q.gaps:
            line = '- Not studied (nobody tested it): %s, effect on %s' % (g.subject_label, g.outcome_label)
            add(line, Fact(line, 'gap:' + g.subject_id, _names(g.subject_label)))
        # outcome words that also appear in an item's name ("size") can't tell findings apart
        named = {w for f in fl for n in f.names for w in n.split()}
        for f in fl:
            f.outcomes -= named
    return '\n'.join(lines), nums, fl


def _rest(q: Question, add) -> None:
    rest = [f for f in q.all_findings() if f.certainty not in FIRM]
    if rest:
        levels = [CERT[c] for c in ('high', 'moderate', 'low', 'very_low') if any(f.certainty == c for f in rest)]
        line = '%d other findings have %s certainty.' % (len(rest), ' or '.join(levels))
        add(line, Fact(line, 'rest', ['other', 'less certain', 'remaining', 'rest'],
                       {f.direction for f in rest}, {f.certainty for f in rest}), len(rest))


def check_claims(text: str, fl: List[Fact]) -> Optional[str]:
    """Hard rule 1: every direction or certainty the reply states must belong to the items it names.
    Each item named in a clause must fit every direction word in it, and each certainty must fit the
    items named next to it. Fails closed: a clause that states a result without naming a fact is rejected."""
    known = set().union(*(f.outcomes for f in fl)) if fl else set()
    for clause in re.split(r'[.;:]\s+|[.;]$|, (?:and|but|while|whereas) ', text.lower()):
        clause = clause.strip()
        if not clause:
            continue
        dirs = [ok for rx, ok in DIR_WORDS if re.search(rx, clause)]
        certs = [(m.start(), (m.group(1) or m.group(2)).replace(' ', '_')) for m in CERT_RE.finditer(clause)]
        if not dirs and not certs:
            continue
        hits = []
        for f in fl:
            at = [clause.find(n) for n in f.names if n in clause]
            if at:
                hits.append((min(at), f))
        if any(f.exclusive for _, f in hits):
            hits = [(p, f) for p, f in hits if f.exclusive]
        if not hits:
            return 'states a result without naming a fact: %r' % clause[:60]
        said = {w for w in known if re.search(r'\b%s\b' % w, clause)}
        items: Dict[str, Tuple[int, List[Fact]]] = {}
        for p, f in hits:
            pos, fs = items.get(f.key, (p, []))
            items[f.key] = (min(pos, p), fs + [f])
        for key, (pos, fs) in items.items():
            if said:
                fs = [f for f in fs if not f.outcomes or f.outcomes & said]
                if not fs:
                    return 'no such finding: %r' % clause[:60]
            items[key] = (pos, fs)
        # an item with several findings left (say, mixed for survival but increases growth) must fit
        # the direction word in every one of them, so a clause can't blur two findings into one
        for ok in dirs:
            for _, fs in items.values():
                if not all(ok & f.dirs for f in fs if f.dirs) or not any(f.dirs for f in fs):
                    return 'direction not in the facts: %r' % clause[:60]
        # a certainty belongs to the items named since the previous one; if none, to those after it
        prev = -1
        for i, (at, c) in enumerate(certs):
            nxt = certs[i + 1][0] if i + 1 < len(certs) else len(clause)
            near = [fs for pos, fs in items.values() if prev < pos < at] or \
                   [fs for pos, fs in items.values() if at < pos < nxt]
            if not near:
                return 'certainty not tied to a named fact: %r' % clause[:60]
            for fs in near:
                if not all(c in f.certs for f in fs):
                    return 'certainty not in the facts: %r' % clause[:60]
            prev = at
    return None


def validate(text: str, allowed: List[str], fl: Optional[List[Fact]] = None) -> Optional[str]:
    """Why the model's text cannot be used, or None if it is fine."""
    t = text.strip()
    if not t:
        return 'empty'
    if len(t) > MAX_CHARS:
        return 'too long'
    if len(re.findall(r'[.!?](?=\s|$)', t)) > MAX_SENTENCES:
        return 'more than %d sentences' % MAX_SENTENCES
    if '<' in t or '>' in t or '*' in t or '#' in t:
        return 'markup'
    low = t.lower()
    m = TIMELINE.search(low)
    if m:
        return 'mentions a duration: %r' % m.group(0)
    m = OVERCLAIM.search(low)
    if m:
        return 'overclaims: %r' % m.group(0)
    m = STYLE.search(low)
    if m:
        return 'machine-sounding wording: %r' % m.group(0)
    for w in NEGATIVE:
        if w in low:
            return 'negative wording: %r' % w
    for n in re.findall(r'\d+(?:\.\d+)?', t):
        if n not in allowed:
            return 'number %s not in the facts' % n
    for w in re.findall(r'[a-z]+', low):
        if w in NUMBER_WORDS and str(NUMBER_WORDS[w]) not in allowed:
            return 'number %r not in the facts' % w
    if fl is not None:
        return check_claims(t, fl)
    return None


def ask(fact_sheet: str, timeout: float = 45.0) -> Tuple[str, int]:
    """One chat completion from the LiteLLM (OpenAI-compatible) endpoint: (text, tokens used)."""
    url = os.environ['BRINE_URL'].rstrip('/')
    if not url.endswith('/chat/completions'):
        url += '/chat/completions' if url.endswith('/v1') else '/v1/chat/completions'
    body = json.dumps({
        'model': os.environ['BRINE_MODEL'],
        'messages': [{'role': 'system', 'content': SYSTEM},
                     {'role': 'user', 'content': fact_sheet}],
        'temperature': 0, 'max_tokens': 220,
        # Qwen3 thinks by default (and ignores /no_think here): minutes and hundreds of tokens, empty reply
        'chat_template_kwargs': {'enable_thinking': False},
    }).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json', 'Authorization': 'Bearer ' + os.environ['BRINE_API_KEY']})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    text = out['choices'][0]['message'].get('content') or ''
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.S)   # Qwen3 reasoning, if any
    return ' '.join(text.split()), int((out.get('usage') or {}).get('total_tokens') or 0)


def enabled() -> bool:
    return all(os.environ.get(k) for k in ('BRINE_URL', 'BRINE_MODEL', 'BRINE_API_KEY'))


def home_summaries(data: SiteData, templates: Dict[str, str], use_llm: bool = True) -> Dict[str, Tuple[str, str]]:
    """{qid: (text, source)}: the model's summary where it passed validate(), else the template."""
    out: Dict[str, Tuple[str, str]] = {}
    on = use_llm and enabled()
    tokens = calls = 0
    for qid, q in data.questions.items():
        out[qid] = (templates[qid], 'template')
        if not on:
            continue
        sheet, nums, fl = facts(data, q)
        try:
            text, used = ask(sheet)
        except Exception as exc:  # network, auth, timeout, bad JSON: keep the templates, stop calling
            print('[build] llm %s: request failed (%s); templates used from here on' % (qid, type(exc).__name__))
            on = False
            continue
        calls += 1
        tokens += used
        why = validate(text, nums, fl)
        if why:
            print('[build] llm %s: rejected (%s); template used. Reply was: %s' % (qid, why, text[:300]))
            continue
        out[qid] = (text, 'llm')
        print('[build] llm %s: summary written by %s' % (qid, os.environ['BRINE_MODEL']))
    if calls:
        print('[build] llm: %d calls, %d tokens in total' % (calls, tokens))
    return out
