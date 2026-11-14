"""Build the Lane 3 site: load -> summarize -> render -> graph -> check.

Exit codes: 0 ok, 1 check failed, 2 load/validation failed, 3 unexpected exception.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from load import LoadError, load_all  # noqa: E402


def dir_size(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    return total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Build the Lane 3 evidence site.')
    ap.add_argument('out', nargs='?', default='site/', help='output directory (deleted and recreated)')
    ap.add_argument('--answers', default='answers/', help='answer pack directory')
    ap.add_argument('--no-llm', action='store_true', help='accepted; the MVP never calls an LLM')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args(argv)

    try:
        try:
            data = load_all(args.answers)
        except LoadError as exc:
            for line in str(exc).splitlines():
                print('[build] LOAD ERROR %s' % line, file=sys.stderr)
            return 2
        if args.verbose:
            for w in data.warnings:
                print('[build] warning: %s' % w)
        n_find = sum(len(q.findings) + len(q.trends) for q in data.questions.values())
        g = data.q1_graph
        print('[build] loaded %d answer files + %d graph: %d findings and trends, %d edges, %d graph quotes'
              % (len(data.questions), 1 if g else 0, n_find, len(g.edges) if g else 0,
                 len(g.evidence) if g else 0))

        from summarize import summarize_all
        prose = summarize_all(data, args)
        print('[build] prose: template only (LLM not enabled in MVP)')

        out = args.out
        if os.path.isdir(out):
            shutil.rmtree(out)
        os.makedirs(out)

        from render import render_site
        pages = render_site(data, prose, out)

        if g is not None:
            from graph_svg import write_graph
            write_graph(g, data.edge_index, out)

        print('[build] wrote %d pages to %s (%d KB)' % (len(pages), out, dir_size(out) // 1024))

        from check import check_site
        problems = check_site(out, data, answers_dir=args.answers)
        for p in problems:
            print('[check] FAIL %s' % p)
        print('[build] check: %d problems' % len(problems))
        return 1 if problems else 0
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 3


if __name__ == '__main__':
    sys.exit(main())
