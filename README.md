# Lane 3 — Decision Support

## The challenge

> **Build the website that serves up the answers to three practitioner**
> **questions. Show how sure we can be of each finding, show gaps as gaps,**
> **and link every claim back to its source sentence.**

The answers are already in this pack. `make_answers.py` built them from the
Lane 2 graph (5,554 claims from 293 papers) with simple, visible rules: no
LLM and no modelling. They are deliberately barebones: tables of findings,
each with a direction, a certainty grade, a study count and the claims behind
it. Your job is the interface: how a restoration practitioner asks a question,
reads the answer, sees what it rests on and reaches the paper.

Q1 also comes as a **graph** (`answers/q1_tree_planting_graph.json`), and your
site must draw it: an interactive node-link view of how planting stock and
site treatments act on seedlings, directly and through the conditions they
change. Building that view is part of the challenge (see "The Q1 graph"
below).

## The three questions

| File | Question | What the answer is |
| --- | --- | --- |
| `answers/q1_tree_planting.json` | For tree planting in Canadian forest restoration, how do planting-stock traits (seedling size, nursery fertilization, mycorrhizal inoculation) affect survival and growth, and how do competing vegetation and site preparation change that? | 13 findings (trait or site factor x survival or growth) from 239 claims in 29 papers, 1 gap, and 5 claims on combined treatments |
| `answers/q1_tree_planting_graph.json` | The same question, as a network | 12 nodes and 29 edges from 330 claims in 33 papers: Q1's 13 findings plus the links through competing vegetation, seedling nutrient status and soil conditions, one combined treatment and one edge that changes another edge |
| `answers/q2_created_marshes.json` | How long do created marshes take to reach biodiversity and function comparable to natural reference wetlands, and which attributes lag? | 8 comparisons with a reference wetland and 3 trends with marsh age, from 27 claims in 5 papers. No paper gives a time to reach the reference: that is the honest answer to "how long" |
| `answers/q3_grassland_gaps.json` | For grassland restoration in Canada, which intervention-outcome combinations have little or no evidence, and where is the graph densest? | An evidence gap map: 24 interventions x 16 outcomes, 123 cells filled (72 of them by a single study), 261 empty |

`answers/answers.md` shows all of them as readable tables.

## What's in the box

```
answers/
  q1_tree_planting.json     the three answers (shape below)
  q2_created_marshes.json
  q3_grassland_gaps.json
  q1_tree_planting_graph.json   Q1 as a graph: nodes, edges, claims (shape below)
  answers.md                the same, readable
make_answers.py             rebuilds answers/ from graph/ and groups/ (python make_answers.py, about 10 s)
graph/
  causal_graph.yaml         the CAMO graph: every claim, its quote, its paper
  causalmosaic.yaml         the CAMO schema it conforms to
groups/
  lane3_groups.yaml         the 24 intervention and 16 outcome groups used by Q2 and Q3
  grouping_audit.csv        every node's group and the pattern that matched
manifest.json               what was built, from what
```

## The answer files

Every answer file has the same core:

```json
{
  "id": "q1-tree-planting",
  "question": "...",
  "how_built": "which claims were selected and how they were pooled",
  "findings": [
    {
      "id": "q1:site_preparation:survival",
      "subject": {"id": "site_preparation", "label": "Site preparation"},
      "outcome": {"id": "survival", "label": "Seedling survival"},
      "studies": 4, "claims": 12,
      "direction": "mixed",
      "study_directions": {"decrease": 1, "increase": 1, "mixed": 1, "no_effect": 1},
      "claim_directions": {"decrease": 2, "increase": 5, "no_effect": 5},
      "certainty": "high",
      "certainty_rationale": "start high (...); -1 studies disagree; +1 mechanistic and difference-making evidence -> high",
      "edge_ids": ["camo:edge_..."],
      "document_ids": ["10.1139/..."]
    }
  ],
  "gaps": [
    {"id": "q1:nursery_fertilization:survival", "status": "no_evidence", "studies": 0,
     "searched_for": "what was looked for and not found", "subject": {...}, "outcome": {...}}
  ],
  "limitations": ["what this answer must not be read as saying"],
  "evidence": {
    "camo:edge_...": {"subject": "...", "predicate": "causes", "negated": false, "object": "...",
                      "direction": "increase", "certainty_grade": "moderate", "quote": "the sentence in the paper",
                      "title": "...", "year": 2016, "doi": "..."}
  }
}
```

Each question adds a little of its own:

* **Q1** has `interactions`: claims about combined treatments ("scarification
  and fertilization") or one factor changing another's effect. These are the
  direct evidence for "how do competing vegetation and site preparation change
  that?" and are listed, not pooled.
* **Q2** has `short_answer` (`time_to_reference` is `null`, with a note on
  why, plus the attributes that lag), `with_time` (how attributes change as the
  marsh ages), and on each finding `lags`, `attribute_kind` and `time_points`.
  Its `direction` is relative to the reference: `below_reference`,
  `comparable`, `above_reference`, `mixed` or `unclear`.
* **Q3** has `summary` (cells filled, thin, empty; the ten densest) and a
  `density` on each finding: `thin` (1 study), `some` (2-3) or `dense` (4+).

`direction` (Q1 and Q3) is what happens to the outcome: `increase`,
`decrease`, `no_effect` (tested, nothing found), `mixed` (studies disagree) or
`unclear`. A direction holds when at least two thirds of studies share it.

## The Q1 graph

`answers/q1_tree_planting_graph.json` is Q1 as a directed graph:

```json
{
  "nodes": [
    {"id": "site_preparation", "label": "Site preparation", "kind": "site_treatment"},
    {"id": "fertilization_at_planting+site_preparation", "label": "Fertilization at planting + Site preparation",
     "kind": "combination", "members": ["fertilization_at_planting", "site_preparation"]}
  ],
  "edges": [
    {"id": "site_preparation->competing_vegetation", "kind": "effect",
     "source": "site_preparation", "target": "competing_vegetation",
     "direction": "mixed", "certainty": "moderate", "studies": 4, "claims": 4,
     "certainty_rationale": "...", "claim_directions": {...}, "edge_ids": ["camo:edge_..."]},
    {"id": "fertilization_at_planting~>site_preparation->growth", "kind": "moderation",
     "source": "fertilization_at_planting", "target": null,
     "target_edge": "site_preparation->growth", "direction": "increase", "...": "..."}
  ],
  "gaps": [{"id": "nursery_fertilization->survival", "source": "...", "target": "...", "status": "no_evidence"}],
  "set_aside": [{"edge_id": "camo:edge_...", "why": "..."}],
  "evidence": {"camo:edge_...": {"quote": "...", "title": "...", "...": "..."}}
}
```

* **Node kinds:** `planting_stock` (a trait of the seedling as planted),
  `site_treatment`, `condition` (competing vegetation, seedling nutrient
  status, soil and microsite: what treatments change on the way to the
  seedling), `outcome` (survival, growth) and `combination` (two treatments
  applied together; `members` names them).
* **Edge kinds:** an `effect` edge goes from `source` to `target`. A
  `moderation` edge goes from `source` to another *edge* (`target_edge`): the
  claim is that the source changes the size of that effect. Every edge carries
  the same pooled fields as a finding, so it has a direction, a certainty and
  claims you can open.
* **Gaps** are pairs that were looked for and not found. Draw them as gaps
  (e.g. a dashed, labelled "no evidence" link), never as a weak or negative
  edge.
* The edges into survival and growth from stock traits and site treatments
  are exactly the findings in `q1_tree_planting.json`, so the two views can't
  disagree.

What the view must do:

1. Show every node and edge, with each edge's direction and certainty
   readable without hovering (colour alone isn't enough).
2. Let a user select an edge and reach its claims and their source sentences.
3. Draw a moderation edge as pointing at the edge it changes, and a
   combination node so that its members are visible.
4. Keep paths honest. Site preparation → competing vegetation → survival is
   two bodies of evidence, mostly from different papers. Don't draw or
   describe it as one tested effect, and don't multiply the edges into a
   pathway strength.
5. Put labels in the DOM as text (HTML or SVG `<text>`), not only on a
   canvas, so screen readers and the crawler can read them.

You may write the layout and rendering yourself or bundle a library, as long
as it is served from your own site and works offline.

## How certainty is graded

Rule `lane3-barebones-1`, in `pool()` in `make_answers.py`. Start from the
best study design in the body of evidence: randomized against an untreated
control is high; other randomized, quasi-experimental and controlled
longitudinal designs moderate; observational low; modelling and case studies
very low. Then −1 for a single study, −1 if studies disagree, −1 if most
claims report no comparator; +1 if three or more studies agree, +1 if
mechanistic and difference-making evidence are both present. One study never
exceeds moderate. Every grade carries its `certainty_rationale`: show it.

The authors' `causal_language` is not an input. How loudly a paper claims
something and how strong its evidence is are separate questions.

## Five things to get right

**An empty cell is not a negative result.** A gap means nobody in this corpus
tested that pairing. It does not mean the intervention fails. Q3 is mostly
gaps; rendering them as "ineffective" gets the question backwards.

**Certainty is part of the finding, not decoration.** Every finding has a
`certainty`. Put it next to the finding, not on another page.

**"Mixed" and "no effect" are findings.** Fertilization at planting raises
black spruce growth and does nothing for jack pine on the same site. A
practitioner needs to see that the studies disagree, and a tested null is
different from a gap.

**Say what can't be answered.** Q2 asks "how long?" and the corpus can't say.
A site that invents a number, or hides the question, fails the user.

**Serve the pack's numbers.** Plain-language summaries, explanations, layout
and visuals are yours, and you may use the LLM at build time to write them.
Directions, certainty grades and study counts come from the answer files, and
the scripts check them. If you think a rule in `make_answers.py` misreads the
graph, say so on the page, next to the pack's number.

## Provenance

Every finding lists `edge_ids`, and each one is in that file's `evidence` with
its quote, paper title, year and DOI. The full edge, with character offsets
into the article where they exist, is in `graph/causal_graph.yaml`. A claim in
your UI should be traceable to a sentence in a paper in about two clicks.

## Add a new question

Drop its JSON in `answers/` and rebuild; the layout is picked from the data's
shape, not its id: a gap map if it has cell counts and densities, a comparison
if it is measured against a reference or over time, an effects page if its
findings increase, decrease or are mixed, and a plain page otherwise. A
`qN_..._graph.json` next to it gets its own graph page.

## Submitting

The last commit before **6 p.m. EST on Sunday, November 15** will be used for judging.

Judges run every submission on one machine, one at a time: an NVIDIA DGX Spark
(GB10, **ARM64 / aarch64** Linux, CUDA). Check that your dependencies install
on aarch64. The LLM is Qwen3.8-27B on the shared LiteLLM endpoint, the same
endpoint and model you use during development, so what works for you will work
for the judges. You don't have to use it.

1. **One command, from a clean checkout.** Your README gives a single command
   that runs the whole pipeline, for example `./build.sh site/`: from this
   pack's files to a finished site. Pin your dependencies (a lock file or `==`
   versions). The only network call your build may make is to the LLM
   endpoint: no other downloads or APIs at build time.
2. **Read the LLM endpoint, model and key from the environment.** Use exactly
   these variables: `BRINE_URL` (the endpoint URL), `BRINE_MODEL` (the model
   name) and `BRINE_API_KEY` (your key). Judges set the same three to run you
   with their own key on the same endpoint. Don't hardcode any of them, and
   don't commit keys.
3. **Output.** A directory of static files with an `index.html`, which judges serve
   with `python -m http.server` and test with Lighthouse, axe-core and
   practitioners. It must answer all three questions, draw the Q1 graph, and work offline from
   those files: anything an LLM contributes is computed at build time, not at
   view time. Page weight per view is scored separately from build energy.

Footprint is energy (Wh) per build: what your code uses on the judging machine
plus the model's share, estimated from the tokens your build uses on the
LiteLLM endpoint. It's ranked against the other teams, and it only counts once your submission clears the lane's
accuracy floor. A command that doesn't run from a clean checkout halves your
automatic scores until it is fixed.
