# CLAUDE.md — context for Claude Code

## What this project is
Evidence Jam 2026 ("Causapalooza") hackathon, Lane 3 — Interface / Decision Support.
Hosted by Tim Alamenciak (EcoWeaver project) at the Waterloo DRAGEN Lab, Nov 13–16 2026.
Team repo: winnie-c8/evidencejam2026-whimsy (fork of timalamenciak/evidencejam2026-lane3). MIT licence — keep LICENSE.

**Goal:** build a static website that presents the answers to 3 fixed practitioner questions
(already computed in `answers/`). We do NOT compute new answers. Users pick a question and explore it.
Audience: restoration practitioners (non-coders, e.g. conservation authorities, NGOs, consultants).

## The 3 questions (data in answers/)
- Q1 `q1_tree_planting.json` — what helps planted seedlings survive/grow (findings, gaps, interactions)
- Q1 graph `q1_tree_planting_graph.json` — same as a node-link graph we must draw (12 nodes, 29 edges, 1 gap, 1 moderation edge)
- Q2 `q2_created_marshes.json` — how long until created marshes match natural ones. Honest answer: the corpus can't say (`time_to_reference: null`). Show that FIRST.
- Q3 `q3_grassland_gaps.json` — evidence gap map, 24 interventions x 16 outcomes, mostly empty cells
- `answers/answers.md` = same data as readable tables. README.md = the full challenge spec; read it before big changes.

## How the data reads
- `id` = machine name (never show). `label` = human name (show this).
- Finding: subject → outcome, `direction`, `certainty`, `studies`, `certainty_rationale`, `edge_ids`.
- `edge_ids` → look up in the same file's `evidence` dict → `quote`, `title`, `year`, `doi` (doi may be null: no link then).
- `gaps` = nobody studied it. Never render as negative/"ineffective".
- `rule: lane3-barebones-1` = name of the certainty grading recipe (see README "How certainty is graded").

## Hard rules (judged, some by script)
1. Never change pack numbers: direction, certainty, study counts come from the JSON. Our own wording is fine.
2. Quotes shown verbatim. Any claim → its source sentence + paper in ~2 clicks.
3. Certainty + rationale shown next to every finding. "Mixed" and "no effect" are findings; show them.
4. Gaps look like gaps (grey/dashed, "Not studied"), distinct from tested nulls.
5. Q1 graph: labels as DOM/SVG text (no canvas), direction + certainty readable without hover and not by colour alone, moderation edge points at the edge it changes, combination node shows members, don't present multi-hop paths as one tested effect.
6. Output = static files with index.html, works OFFLINE (no CDNs, no external fonts/scripts). Judges serve with `python -m http.server`, test with Lighthouse + axe-core.
7. One command from a clean checkout: `./build.sh site/`. Pinned deps. Judges run on ARM64 (aarch64) Linux. A broken build halves automatic scores.
8. LLM optional, build time only. Read BRINE_URL / BRINE_MODEL / BRINE_API_KEY from env. NEVER hardcode or commit keys. Token use counts against the sustainability score (we currently use no LLM).
9. Accessibility (WCAG 2.1 AA) is also Lane 3's sustainability prize: keyboard nav, contrast, semantic HTML, one h1, lang attr, table view of the graph, no sideways scroll at 375px.
10. Page weight per view is scored — q3.html (~1.3 MB) and q1-graph.html (~525 KB) are currently too heavy.

## Code layout
- `build.sh` → `build/build.py` (entry), `load.py` (read answers), `render.py` (HTML), `graph_svg.py` (Q1 SVG), `summarize.py` (prose; template-only, LLM off), `check.py` (built-in checker)
- `static/style.css`; `static/graph.js` (Q1 graph only: drag boxes/arrows, pin highlight, filters, sort, side panel with sources; its routing mirrors `route_all` in graph_svg.py, keep them in step). `FLOW` in graph_svg.py switches the graph between top-down ('down', default) and left-to-right ('right')
- `tests/check_independent.py` (stdlib-only second checker), `tests/test_checkers.py` (build + 22 mutation tests), `tests/a11y/` (axe + phone width, CI only)
- `.github/workflows/check.yml` runs all of this on PRs.
- Page contract the checkers rely on: `id="f-<slug>"` findings, `id="gap-<slug>"` gaps, `id="edge-<slug>"` SVG arrows, `id="e-<slug>"` evidence sections, `data-check="<q>/<slug>/direction|certainty|studies"`, `data-claim="<edge id>"`. If you change markup, update the mutation patterns in tests/test_checkers.py.

## Before pushing
```
./build.sh site/ && python3 build/check.py site/ && python3 tests/check_independent.py site/ && python3 -m unittest discover -s tests
grep -rn "sk-" --exclude-dir=.git --exclude-dir=site .   # must print nothing
```

## Deadlines
Last commit before 6 p.m. Eastern, Sun Nov 15 2026 is judged. 3-minute team presentation Mon Nov 16, 1 p.m.

## About me (Brian)
First-year, new to hackathons and git. Explain things simply and step by step; say what a command does before running it.
