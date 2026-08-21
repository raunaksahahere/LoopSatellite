# Architecture

## The one rule

> **Statistics detects. The LLM builds the case.**

Water detection, seasonality removal and anomaly flagging are 100% deterministic.
No LLM call appears anywhere in that path. An LLM only ever touches an anomaly
*after* the statistics have already flagged it — corroborating it, explaining it,
drafting around it, or answering questions about it.

This is enforced three ways, not just documented:

1. **Physical separation.** Detection lives in `data_pipeline/` (offline) and
   `app/services/detection/` (read-only). LLM code lives in
   `app/services/llm/`. Detection has no dependency edge to it.
2. **A test that fails the build.** `tests/test_detection.py::test_detection_modules_never_import_the_llm`
   walks the AST of every module under `services/detection/` looking for an
   import of `llm` or `openai` — including lazy imports inside functions. Its
   sibling does the same for `data_pipeline/`.
3. **Shape of the API.** Every LLM endpoint takes an `anomaly_id` that must
   already exist in `precomputed/anomalies.json`. There is no code path by which
   a model produces, alters, or suppresses a finding.

## The golden rule

During a demo the API makes no Earth Engine call, downloads nothing, and computes
nothing. It reads `backend/precomputed/` — about 650 KB of JSON and SVG — and
serves it.

```
backend/precomputed/
├── manifest.json        provenance + the exact constants the run used
├── ponds.geojson        pond polygons, labels, centroids, baseline areas
├── anomalies.json       flagged events, enriched with pond labels
├── timeseries/<ID>.json observed vs seasonally-expected monthly series
└── chips/<EVENT>_*.svg  before/after extent chips
```

Regenerating it is a separate, offline act: `backend/data_pipeline/run_pipeline.sh`.

## Data flow

```
                       OFFLINE (data_pipeline/)                    LIVE (app/)
  ┌──────────────────────────────────────────────────┐   ┌────────────────────────┐
  │ 01  pond polygon mask (EKW bheris)               │   │                        │
  │ 02  geeup → Earth Engine asset                   │   │  FastAPI               │
  │ 03  GEE: Sentinel-2 → MNDWI ≥ 0.1 → zonal stats  │   │   /api/ponds           │
  │       (GPL-3.0, adapted from EOWater)            │   │   /api/anomalies       │
  │ 04  cloud filter → monthly median composite      │   │   /api/queue           │
  │ 05  STL (robust, period 12) → Seasonal-Hybrid    │──▶│   /api/reports         │
  │       ESD → loss/persistence/recovery →          │   │   /api/llm/*           │
  │       deterministic confidence                   │   │                        │
  │ 06  NDBI/BSI before-vs-after → conversion signal │   │  reads precomputed/    │
  │ 07  export precomputed/                          │   │  only                  │
  └──────────────────────────────────────────────────┘   └────────────────────────┘
```

### Why the detector works

Three separations, in order:

1. **Water from land** — MNDWI, thresholded at 0.1. Green and SWIR reflect very
   differently off water.
2. **Season from event** — STL decomposition, period 12, robust. A bheri drawn
   down every April tracks its own seasonal component and never reaches the queue.
3. **Signal from noise** — Seasonal-Hybrid ESD on the residual, median/MAD
   z-scores so a large event doesn't inflate the scale it is judged against.

Then three filters that turn statistics into something an officer can act on:
losses only (a pond that grew is not our problem), a minimum 15% shortfall against
seasonal expectation, and merging adjacent flagged months into one event.

### The subtle part: expectation must be frozen

Loss size and recovery are both judged against a **pre-event** baseline
(`frozen_expected`), not a rolling one. A trailing baseline decays into a
permanent step-down, so a pond that was filled in and never came back appears to
"recover" against its own diminished expectation — precisely the case this tool
exists to catch. The rolling `expected_series` is used only for the chart band.

### Confidence is a formula, not an opinion

```
score = 0.35·loss + 0.20·residual_z + 0.20·persistence + 0.25·non_recovery
score *= 0.7 + 0.3·data_quality
```

Bands: ≥0.70 high, ≥0.45 medium, else low. It is printed in
`manifest.json` and re-derivable by hand from any anomaly record, which is the
point — an officer can be told exactly why a case is ranked where it is.

## Storage: GeoJSON in JSONB, not PostGIS

Geometries live as GeoJSON objects inside `JSONB` columns. No PostGIS extension,
no GeoAlchemy2, no `ST_*` SQL. Bounding-box tests, ward lookup and nearest-pond
run in Python (`app/services/detection/repository.py`).

**Why:** setup speed. At EKW's scale — 42 polygons, ~650 KB — the whole dataset
is in memory and a bbox scan is microseconds. PostGIS would buy query power we
don't need and cost provisioning time we don't have.

**When it stops being right:** once the pond count reaches the thousands, or once
a query needs true intersection rather than bbox overlap. The migration is
contained: enable PostGIS on the same Neon database, convert the JSONB columns to
`geometry`, and rewrite the helpers in `repository.py`. **The API contract does
not change** — GeoJSON in, GeoJSON out — so nothing in `frontend/` moves.

The database is optional for the read path entirely. Officer verifications are
the only writes; without `DATABASE_URL` they go to a JSON file, and
`/api/health` reports which backend is live.

## The four LLM features, and what each is prevented from doing

| Feature | The model's job | What it structurally cannot do |
|---|---|---|
| **Evidence corroboration** | Read search results, return structured findings with links and an explicit relevance verdict | Invent a source or URL; every finding must come from supplied results, and the response carries `searched: false` when nothing ran |
| **Regulatory grounding + notice** | Fill a notice around provisions that were retrieved and quoted for it | Cite anything not retrieved — the draft is re-scanned afterwards and **discarded** if it names an un-retrieved provision. With no retrieval hit, `grounded: false` and no draft at all |
| **Natural-language query** | Turn a sentence into a filter object | See or produce a number — the filter runs in Python against `precomputed/`, and the filter is shown back to the officer |
| **Report writer** | Write prose for six named template slots | Choose the structure, or supply a figure — every number in the PDF comes from `facts`, and the prose is never parsed |

All four go through one client (`app/services/llm/client.py`). No feature builds
its own API call, so the model name, key, headers and timeouts have exactly one
home. Every feature degrades to a deterministic path when no key is set, and says
so in its response rather than failing silently.

### Retrieval is lexical on purpose

`app/rag/store.py` is BM25, not embeddings. Legal retrieval is citation
retrieval — the officer asks about "filling of a wetland" and the statute says
"filling" — and exact-term matching will not quietly return a semantically
adjacent provision that says something different. It also needs no model download
at demo time. The interface is the one a vector store would have, so swapping in
FAISS or ChromaDB means replacing that one file.

Chunking preserves hierarchy: a clause is indexed as `Rule 4(2)(i)`, not `(i)`,
because `(i)` is useless in a notice.

## Frontend

React + Vite + TypeScript. MapLibre for the map, Recharts for the series,
`react-compare-slider` for before/after. One stylesheet, no framework.

Navigation is a straight line with no dead ends: **map → pond detail → verify →
back to the queue → back to the map.** The map is the anchor; every view is
reachable from it and returns to it.

The officer-facing copy contains no "MNDWI", "STL", "ESD", "NDBI" or "z-score" —
a test asserts this over every generated explanation. The technical terms are
present, one disclosure triangle away, in "How this was detected".

Confidence is a colour-coded band ("High confidence" / "Needs a closer look"),
never a decimal. The score is available as a tooltip.

## Deliberately not built (MVP boundaries)

- **Vision-model second opinion.** Extension point: `services/detection/conversion_classifier.py`.
- **Bengali + text-to-speech.** Hook point: `services/report/bhashini.py`, a
  documented stub. It plugs in between `report_writer.write()` and
  `pdf_builder.build_pdf()`; note the PDF needs a Bengali font registered first.
- **Cross-sensor harmonisation back to 1992.** Landsat 5/7/8 need a per-sensor
  MNDWI offset before their series can be joined to Sentinel-2's. `observation.source`
  already carries the sensor.
- **Upstream contribution to EOWater.** The vector `reduceRegions` path in
  `03_run_wsa_gee.js` is a genuine simplification for small polygon counts.
