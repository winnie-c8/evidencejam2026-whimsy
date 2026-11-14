#!/usr/bin/env python3
"""Tests for the build and both site checkers.

    python3 -m unittest discover -s tests -v

1. A clean build (no BRINE_* env vars, so no LLM) succeeds, and both checkers pass.
2. "Mutation" tests: each one breaks a copy of the built site in a specific way
   that would cost us points (wrong certainty, deleted finding, gap worded as a
   failure, external script, ...) and asserts the independent checker catches it.
   A checker that never fails proves nothing; these prove it actually catches things.
Standard library only.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from check_independent import Checker  # noqa: E402

SITE: str = ''
TMP: str = ''


# SITE_DIR=site/  reuse an existing build (CI builds once, then runs these tests on it)
# COMPARE_BUILTIN=1  also run build/check.py on every mutation and print a comparison table
#                    (informational and slower: one extra process per mutation)
COMPARE_BUILTIN = os.environ.get('COMPARE_BUILTIN') == '1'


def setUpModule() -> None:
    global SITE, TMP
    TMP = tempfile.mkdtemp(prefix='site-test-')
    if os.environ.get('SITE_DIR'):
        SITE = os.path.abspath(os.environ['SITE_DIR'])
        if not os.path.isfile(os.path.join(SITE, 'index.html')):
            raise RuntimeError('SITE_DIR=%s has no index.html; build it first' % SITE)
        return
    SITE = os.path.join(TMP, 'site')
    env = {k: v for k, v in os.environ.items() if not k.startswith('BRINE_')}
    r = subprocess.run(['bash', os.path.join(ROOT, 'build.sh'), SITE, '--strict'], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('build failed (exit %d):\n%s\n%s' % (r.returncode, r.stdout, r.stderr))


def tearDownModule() -> None:
    shutil.rmtree(TMP, ignore_errors=True)


def mutated(page: str, pattern: str, repl: str, count: int = 1) -> str:
    """Copy the built site, apply one regex edit to one page (created if pattern is
    None), return the copy's path."""
    dst = tempfile.mkdtemp(prefix='mut-', dir=TMP)
    shutil.copytree(SITE, dst, dirs_exist_ok=True)
    path = os.path.join(dst, page)
    if pattern is None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(repl)
        return dst
    with open(path, encoding='utf-8') as fh:
        html = fh.read()
    new, n = re.subn(pattern, repl, html, count=count, flags=re.S)
    if n == 0:
        raise AssertionError('mutation pattern did not match %s: %s (the page layout changed; update the test)'
                             % (page, pattern))
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(new)
    return dst


def independent(site: str) -> list:
    return Checker(site, os.path.join(ROOT, 'answers')).run()


def builtin_fails(site: str) -> bool:
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'build', 'check.py'), site,
                        '--answers', os.path.join(ROOT, 'answers')], capture_output=True, text=True)
    return r.returncode != 0


SUBFOLDER_PAGE = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>x</title>'
                  '<meta name="viewport" content="width=device-width, initial-scale=1">'
                  '<script src="https://cdn.example.com/lib.js"></script></head>'
                  '<body><main><h1>x</h1></main></body></html>')


class CleanBuild(unittest.TestCase):
    def test_independent_checker_passes(self):
        self.assertEqual(independent(SITE), [])

    def test_builtin_checker_passes(self):
        self.assertFalse(builtin_fails(SITE))

    def test_index_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(SITE, 'index.html')))


# (name, page, pattern, replacement, count). Each must make the independent checker fail.
MUTATIONS = [
    ('certainty changed', 'q1.html',
     r'(data-check="q1/q1--site-preparation--survival/certainty">)High', r'\1Low', 1),
    ('direction changed', 'q3.html',
     r'(data-check="q3/[^"/]+/direction">)Mixed', r'\1Increase', 1),
    ('study count changed on a graph arrow', 'q1-graph.html',
     r'(data-check="q1graph/site-preparation--to--growth/studies">)11<', r'\g<1>12<', 0),
    ('finding deleted', 'q1.html',
     r'<tr id="f-q1--seedling-size--growth".*?</tr>', '', 1),
    ('certainty rationale removed', 'q2.html',
     r'(<details class="cert[^"]*"><summary>.*?</summary>)<p>.*?</p>', r'\1', 1),
    ('source quote altered', 'sources-q2--created-marsh--abundance-density.html',
     r'(<blockquote class="quote">)[^<]+', r'\1A sentence no paper wrote.', 1),
    ('DOI link removed', 'sources-q3--seeding--invasive-abundance.html',
     r'href="https://doi\.org/[^"]+"', 'href="#"', 1),
    ('source detached from its finding', 'sources-q1--site-preparation--survival.html',
     r'<details class="ev" data-claim="camo:edge_0ec39c79a398".*?</dl></details>', '', 1),
    ('gap worded as a failure', 'q3.html',
     r'<strong>Not studied:</strong>', '<strong>Ineffective:</strong>', 1),
    ('gap deleted', 'q1.html',
     r'<div class="gap" role="note" id="gap-q1--nursery-fertilization--survival">.*?</div>', '', 1),
    ('Q2 "how long" note replaced with a timeline', 'q2.html',
     r'No study in this corpus reports how long[^<]*', 'Created marshes match natural ones after 10 years.', 0),
    ('limitation removed', 'q3.html',
     r'(data-check="q3/limitations/0">)[^<]+', r'\1Edited.', 1),
    ('external script added (breaks offline)', 'index.html',
     r'</head>', '<script src="https://cdn.example.com/lib.js"></script></head>', 1),
    ('external stylesheet added', 'q2.html',
     r'</head>', '<link rel="stylesheet" href="//fonts.example.com/a.css"></head>', 1),
    ('index no longer links to Q3', 'index.html',
     r'href="q3\.html[^"]*"', 'href="#"', 0),
    ('graph node label removed from SVG text', 'q1-graph.html',
     r'(<tspan[^>]*>)Site preparation(</tspan>)', r'\1\2', 1),
    ('arrow label removed (certainty only on hover)', 'q1-graph.html',
     r'(id="edge-site-preparation--to--growth".*?)<g class="lbl">.*?</g>', r'\1', 1),
    ('graph arrow deleted', 'q1-graph.html',
     r'<a href="#e-vegetation-control--to--growth"[^>]*>.*?</a>', '', 1),
    ('graph drawn on canvas', 'q1-graph.html',
     r'</main>', '<canvas width="10" height="10"></canvas></main>', 1),
    ('duplicate id', 'q2.html',
     r'</main>', '<span id="dup"></span><span id="dup"></span></main>', 1),
    ('second h1', 'q3.html',
     r'</main>', '<h1>Another</h1></main>', 1),
    ('lang attribute removed', 'q1.html',
     r'<html lang="en"', '<html', 1),
    # added after review on #40
    ('arrow screen-reader name says "very low" for "low"', 'q1-graph.html',
     r'(id="edge-seedling-size--to--survival" aria-label="[^"]*?): increase, certainty low', r'\1: increase, certainty very low', 1),
    ('arrow screen-reader name says "1 study" for 11', 'q1-graph.html',
     r'(id="edge-site-preparation--to--growth" aria-label="[^"]*?)11 studies', r'\g<1>1 study', 1),
    ('"no evidence" gap arrow removed from the SVG', 'q1-graph.html',
     r'<a href="#e-nursery-fertilization--to--survival" class="gap-link".*?</a>', '', 1),
    ('claim count changed', 'q1.html',
     r'(data-check="q1/q1--site-preparation--survival/claims">)12<', r'\g<1>13<', 1),
    ('study split (votes) changed', 'q3.html',
     r'(data-check="q3/[^"/]+/study_directions/increase">)\d+<', r'\g<1>99<', 1),
    ('Q2 time point removed', 'q2.html',
     r'(data-check="q2/q2--created-marsh--abundance-density/time_points/0">)[^<]+', r'\1', 1),
    ('Q2 "how long" answer moved below the findings', 'q2.html',
     r'(<div class="callout" role="note" aria-label="How long">.*?</div>)(.*?)(</main>)', r'\2\1\3', 1),
    ('external SVG image via xlink:href', 'q1.html',
     r'</main>', '<svg><image xlink:href="https://img.example.com/a.png"/></svg></main>', 1),
    ('external image via inline style', 'q2.html',
     r'</main>', '<div style="background:url(//img.example.com/a.png)"></div></main>', 1),
    ('form posting to an external site', 'index.html',
     r'</main>', '<form action="https://forms.example.com/x"></form></main>', 1),
    ('page in a subfolder loads an external script', 'extra/page.html', None, SUBFOLDER_PAGE, 0),
    # source pages (quotes moved off the answer pages to keep them light)
    ('finding no longer links to its source page', 'q3.html',
     r'<a class="srclink" href="sources-q3--seeding--invasive-abundance\.html">', '<a class="srclink" href="#">', 1),
    ('finding links to another finding\'s source page', 'q1.html',
     r'href="sources-q1--site-preparation--survival\.html"', 'href="sources-q1--site-preparation--growth.html"', 1),
    ('graph arrow no longer links to its source page', 'q1-graph.html',
     r'href="sources-e-site-preparation--to--growth\.html"', 'href="#"', 1),
    ('source quote altered on a graph source page', 'sources-e-vegetation-control--to--growth.html',
     r'(<blockquote class="quote">)[^<]+', r'\1A sentence no paper wrote.', 1),
    ('source page loads an external script', 'sources-q2--created-marsh--abundance-density.html',
     r'</head>', '<script src="https://cdn.example.com/lib.js"></script></head>', 1),
    # added after review on #41
    ("graph source page shows another arrow's claim", 'sources-e-site-preparation--to--growth.html',
     r'data-claim="camo:[^"]+"', 'data-claim="camo:edge_3fb326f2a6c3"', 1),
    ('made-up time span on a Q2 source page', 'sources-q2--created-marsh--abundance-density.html',
     r'(<div class="sources">)', r'<p>Created marshes recover in 10 years.</p>\1', 1),
    ('Q3 row drops what was searched for', 'q3.html',
     r'data-template="[^"]*"', 'data-template="something else {outcome}"', 0),
    # 2.8 short answers built from the data
    ('short answer says "decreases" for an increase', 'q1.html',
     r'(<span data-group="increase/high">.*?) increase it</span>', r'\1 decrease it</span>', 1),
    ('short answer certainty word changed', 'index.html',
     r'(<span data-cert="high">with )high certainty', r'\1moderate certainty', 1),
    ('short answer lists a finding under the wrong group', 'q1.html',
     r'(<span data-group="decrease/high"><a href=")[^"]+', r'\1q1.html#f-q1--site-preparation--growth', 1),
    ('short answer links to a missing finding', 'index.html',
     r'(<span data-group="increase/high"><a href=")[^"]+', r'\1q1.html#f-q1--nothing', 1),
    ('Q3 short answer study count changed', 'q3.html',
     r'(<p class="short">.*?\(<span data-check="q3/[^"]+/studies">)\d+', r'\g<1>99', 1),
]


class Mutations(unittest.TestCase):
    """Every mutation must be caught. The built-in checker's result is reported for comparison."""
    summary: list = []

    @classmethod
    def tearDownClass(cls):
        if not COMPARE_BUILTIN:
            return
        print('\n  mutation                                                independent  build/check.py')
        for name, ind, built in cls.summary:
            print('  %-56s %-12s %s' % (name, 'caught' if ind else 'MISSED', 'caught' if built else 'missed'))


def _make(name, page, pattern, repl, count):
    def test(self):
        site = mutated(page, pattern, repl, count)
        problems = independent(site)
        if COMPARE_BUILTIN:
            Mutations.summary.append((name, bool(problems), builtin_fails(site)))
        self.assertTrue(problems, 'independent checker missed: %s' % name)
        shutil.rmtree(site, ignore_errors=True)
    test.__doc__ = name
    return test


for _i, _m in enumerate(MUTATIONS):
    setattr(Mutations, 'test_%02d_%s' % (_i, re.sub(r'\W+', '_', _m[0]).strip('_')), _make(*_m))


if __name__ == '__main__':
    unittest.main(verbosity=2)
