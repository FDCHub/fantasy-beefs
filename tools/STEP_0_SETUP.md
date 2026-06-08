# Fantasy Beefs — Step 0: Setup & Verification (Before Coding)

> Created: June 7, 2026
> Do this BEFORE opening the dev thread. It confirms the foundation is real and
> lays down the file structure so the twin-engine build (Claude Code + Qwen) starts clean.
> Location: `fantasy-beefs/tools/`

---

## A. Save the docs (local + repo + project folder)

The five design docs from this session:
1. `DECISION_ENGINE_ROADMAP.md`
2. `P3_1_REV1_MODULE_SPEC.md`
3. `NEW_THREAD_HANDOFF.md`
4. `STEP_0_SETUP.md`  (this file)
5. `the_sitdown_rev1.html`  (early trade-tool demo — reference only, NOT the build target)

Save to all three:
- **Local:** `C:\Users\frase\PycharmProjects\fantasy-beefs\tools\`
- **Repo:** commit to `FDCHub/fantasy-beefs` under `tools/`
- **Project folder:** upload to the Claude project knowledge so future threads see them

```
cd C:\Users\frase\PycharmProjects\fantasy-beefs
git add tools/
git commit -m "Decision engine design docs — roadmap, Rev 1 spec, handoff, Step 0"
git push
```

---

## B. Step 0 verification — confirm reuse claims are REAL

The roadmap assumes two things exist from P0. Claude was wrong about the Monte Carlo
once this session, so VERIFY before building on either. Run these in the repo root.

### B1. Does the per-week Monte Carlo exist, and what does it take?

```
git grep -l -i "monte" -- "*.py"
git grep -n -i "def .*sim" -- "*.py"
git grep -n -i "win_prob\|win probability\|10000\|n_sims\|simulations" -- "*.py"
```

**Looking for:** a function that takes two lineup point totals (+ variance) and returns
a win probability. Note its exact signature — the season wrapper calls it as-is.

- **Found as described** → reuse it. Lock its signature into `season_sim.py`.
- **Different shape** → adjust the SeasonSimulator interface to match reality.
- **Not found** → bigger scope; the per-week sim becomes new work. Flag before Rev 1.

### B2. Do the normalized models exist?

```
git grep -n "NormalizedLeague\|NormalizedRoster\|NormalizedMatchup" -- "*.py"
git grep -rn "class Normalized" -- "*.py"
```

**Looking for:** the model classes and their fields (column names). These define the
shapes the provider seam emits and every engine module consumes.

- **Found** → lock their fields into the `DataProvider` ABC.
- **Named differently** → use the real names; update the spec's seam section.
- **Not found** → the seam defines them fresh; more work in step 1.

### B3. FantasyPros projections — raw stats or pre-scored?

```
git grep -n -i "fantasypros\|projection" -- "*.py"
git grep -n -i "scoring\|league_settings\|points_per" -- "*.py"
```

**Looking for:** whether stored projections are RAW production (yards/rec/TDs) or
already converted to fantasy points, and where league scoring rules live.

- **Raw production stored** → ProjectionEngine converts. As specced.
- **Pre-scored points stored** → decide: re-derive from raw (preferred, league-correct)
  or accept stored points (simpler, but may not match league scoring). Note the choice.

### B4. Mock league — confirm it is seeded and deterministic

```
git grep -n "seed_from_mock\|mock_league" -- "*.py"
python -c "import mock_league"   # or wherever it lives — confirm it imports + loads
```

**Looking for:** the 17-week seeded data the MockProvider will read.

---

## C. Record the findings

Create `tools/STEP_0_FINDINGS.md` with the real answers:

```
PER-WEEK SIM:     <path> · signature: <fn(args) -> return>  | NOT FOUND
NORMALIZED MODELS:<path> · fields: <list>                   | NAMED: <real names>
PROJECTIONS:      RAW | PRE-SCORED · scoring rules at: <path>
MOCK LEAGUE:      <path> · loads: yes/no
```

This file goes to the dev thread alongside the others. It corrects any spec assumption
with ground truth — so the seam is built on what's real, not what was remembered.

---

## D. Folder structure to create (Rev 1 target)

```
fantasy-beefs/
├── data/
│   └── provider.py              [CLAUDE-CODE]  step 1 — the seam
├── engine/
│   ├── projection_engine.py     [QWEN]         raw → league points
│   ├── lineup_optimizer.py      [QWEN]
│   ├── season_sim.py            [CLAUDE-CODE]  wraps existing per-week sim
│   └── team_health.py           [QWEN]
├── api/
│   └── health_routes.py         [QWEN]
├── tools/
│   ├── team_health.html         [QWEN]         Playbook theme, mock-first
│   └── *.md                      (design docs + findings)
└── tests/
    └── test_rev1.py             regression suite on mock data
```

---

## E. Twin-engine readiness

- **Claude Code (PyCharm CLI):** confirm signed in (Google account, Flava Frase).
  Owns the seam + sim wrapper — the load-bearing joins.
- **Qwen coder-node (10.0.0.11, Ollama, Qwen2.5-Coder):** confirm reachable
  (`curl http://10.0.0.11:11434/api/tags`). Owns the four single-file modules once the
  seam interface is locked.
- **Rule:** Qwen does not start a module until its interface is fixed by the seam.
  Otherwise it builds against a guess and the join breaks.

---

## F. Then — and only then — open the dev thread

Order to hand the new thread:
1. `NEW_THREAD_HANDOFF.md`
2. `STEP_0_FINDINGS.md`   ← ground truth, corrects assumptions
3. `DECISION_ENGINE_ROADMAP.md`
4. `P3_1_REV1_MODULE_SPEC.md`

First build action in that thread: **step 1 — `data/provider.py` + MockProvider**, with
the seam interface set to the REAL shapes from STEP_0_FINDINGS, on Claude Code.

---

*Step 0 complete = foundation verified, structure laid, both engines reachable.*
*Fantasy Beefs · June 7, 2026*
