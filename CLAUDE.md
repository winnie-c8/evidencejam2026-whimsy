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
10. Page weight per view is scored and ranked against other teams. Keep answer pages light: quotes live on `sources-<slug>.html` pages, not on the answer pages. Don't add images, fonts or libraries without checking the size (the independent checker prints every page's size).

## Code layout
- `build.sh` → `build/build.py` (entry), `load.py` (read answers), `render.py` (HTML), `graph_svg.py` (Q1 SVG), `summarize.py` (prose; template-only, LLM off), `check.py` (built-in checker)
- `static/style.css`; `static/graph.js` (Q1 graph only: drag boxes/arrows, pin highlight, filters, sort, side panel with sources; its routing mirrors `route_all` in graph_svg.py, keep them in step). `FLOW` in graph_svg.py switches the graph between top-down ('down', default) and left-to-right ('right')
- **Add a new question:** drop its JSON in `answers/` and rebuild; the layout is picked from the data's shape (`detect_kind()` in `load.py`: gap map → comparison → effects → generic), and a `qN_..._graph.json` gets its own `qN-graph.html`. Per-question wording (`AUDIENCE`, `GRAPH_INTRO` in `render.py`) falls back to a default.
- `tests/check_independent.py` (stdlib-only second checker), `tests/test_checkers.py` (build + mutation tests: each breaks the site on purpose and must be caught), `tests/a11y/` (axe, phone width, keyboard Tab order and focus outlines; CI only, needs Node)
- `.github/workflows/check.yml` runs all of this on PRs.
- Page contract the checkers rely on: `id="f-<slug>"` findings, `id="gap-<slug>"` gaps, `id="edge-<slug>"` SVG arrows, `id="e-<slug>"` evidence sections, `data-check="<q>/<slug>/direction|certainty|studies"`, `data-claim="<edge id>"`, and one `sources-<finding slug>.html` / `sources-e-<arrow slug>.html` page per finding / graph arrow, linked from it, showing exactly its quotes. If you change markup, update the mutation patterns in tests/test_checkers.py.

## Before pushing
```
./build.sh site/ && python3 build/check.py site/ && python3 tests/check_independent.py site/ && python3 -m unittest discover -s tests
grep -rnE "sk-[A-Za-z0-9_-]{20,}" --exclude-dir=.git --exclude-dir=site --exclude-dir=node_modules .   # must print nothing (looks for real keys)
```
Optional, the browser checks CI runs (needs Node): `cd tests/a11y && npm ci && npx playwright install chromium && node a11y.mjs ../../site`

## How we work
- Plan: issue #22 (Roadmap) lists every step; each issue's "Done when" is the spec. Start a session with "read issue #N".
- One issue per branch and per PR. Never push straight to `main`: a ruleset blocks merging until all 3 CI checks pass.
- Ask a teammate to review anything that changes the site; small docs-only PRs can be merged once the checks pass. Fix review comments by pushing to the same branch (no new PR). Merge with a merge commit.
- Phase 2 pages overlap (`render.py`, `style.css`): keep PRs small and merge often to avoid conflicts.

## Deadlines
Last commit before 6 p.m. Eastern, Sun Nov 15 2026 is judged. 3-minute team presentation Mon Nov 16, 1 p.m.

## Personal preferences
Put notes about yourself (experience level, how you like things explained) in `CLAUDE.local.md` in the repo root. It is gitignored, so it only affects your own Claude Code sessions.
