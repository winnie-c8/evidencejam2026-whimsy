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


def setUpModule() -> None:
    global SITE, TMP
    TMP = tempfile.mkdtemp(prefix='site-test-')
    SITE = os.path.join(TMP, 'site')
    env = {k: v for k, v in os.environ.items() if not k.startswith('BRINE_')}
    r = subprocess.run(['bash', os.path.join(ROOT, 'build.sh'), SITE], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('build failed (exit %d):\n%s\n%s' % (r.returncode, r.stdout, r.stderr))


def tearDownModule() -> None:
    shutil.rmtree(TMP, ignore_errors=True)


def mutated(page: str, pattern: str, repl: str, count: int = 1) -> str:
    """Copy the built site, apply one regex edit to one page, return the copy's path."""
    dst = tempfile.mkdtemp(prefix='mut-', dir=TMP)
    shutil.copytree(SITE, dst, dirs_exist_ok=True)
    path = os.path.join(dst, page)
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
    ('source quote altered', 'q2.html',
     r'(<blockquote class="quote">)[^<]+', r'\1A sentence no paper wrote.', 1),
    ('DOI link removed', 'q3.html',
     r'href="https://doi\.org/[^"]+"', 'href="#"', 1),
    ('source detached from its finding', 'q1.html',
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
     r'href="q3\.html"', 'href="#"', 0),
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
]


class Mutations(unittest.TestCase):
    """Every mutation must be caught. The built-in checker's result is reported for comparison."""
    summary: list = []

    @classmethod
    def tearDownClass(cls):
        print('\n  mutation                                            independent  build/check.py')
        for name, ind, built in cls.summary:
            print('  %-52s %-12s %s' % (name, 'caught' if ind else 'MISSED', 'caught' if built else 'missed'))


def _make(name, page, pattern, repl, count):
    def test(self):
        site = mutated(page, pattern, repl, count)
        problems = independent(site)
        Mutations.summary.append((name, bool(problems), builtin_fails(site)))
        self.assertTrue(problems, 'independent checker missed: %s' % name)
    test.__doc__ = name
    return test


for _i, _m in enumerate(MUTATIONS):
    setattr(Mutations, 'test_%02d_%s' % (_i, re.sub(r'\W+', '_', _m[0]).strip('_')), _make(*_m))


if __name__ == '__main__':
    unittest.main(verbosity=2)
