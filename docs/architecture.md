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

## Two paths, kept apart

There are two features that both look like "tell me about this area", and the
whole design depends on not confusing them.

```
FAST — a question about places already measured
  NLQueryBar -> /api/llm/query -> nl_query.query()
      gazetteer.resolve(place)      cached JSON, no network
      stl_esd.find_near(lat, lon, r)  haversine over precomputed/
  -> answer in milliseconds, no Earth Engine, deterministic summary

SLOW — start monitoring somewhere new
  LocationRadiusPicker -> POST /api/areas -> BackgroundTasks
      geo.circle_polygon(...)          geodesic circle
      area_processing: GEE -> JRC water bodies -> S2 MNDWI -> STL/ESD -> DB
  -> minutes; status polled at GET /api/areas/{id}
```

The slow path is slow because the science is: STL needs roughly two years of
history before "seasonal" means anything, and `_detect` refuses to flag anything
on a series shorter than 24 months rather than guess. A submitted area therefore
returns 202 and a job to poll, and the UI shows a status with an explanation
instead of a spinner.

`stl_esd.find_near` carries a comment saying it must never gain the ability to
trigger a satellite pull, and a test asserts the fast path never initialises
Earth Engine. That is the boundary; keep it.

## Geometry, and why it is geodesic

`app/core/geo.py`. A degree of longitude is ~103 km at Haldia and ~99 km at
Siliguri, against 111 km for a degree of latitude. Offsetting lat and lon by the
same number of degrees — the obvious implementation — gives a visibly egg-shaped
"circle" that is ~8% too narrow in the north of the state. Since that polygon
decides which Sentinel-2 tiles get pulled, it is worth getting right: we use
`pyproj.Geod.fwd` on WGS84, with a spherical fallback if pyproj is missing.
`tests/test_geo.py` asserts the east-west and north-south spans are equal, which
is the property the naive version fails.

The frontend has its own spherical `circlePolygon` for the live slider preview.
It is a preview only — the authoritative geometry is always built server-side
from the centre and radius that were submitted.

## Place names

`app/rag/gazetteer.py`. A cached JSON file, resolved once from Nominatim at build
time (`python -m app.rag.gazetteer --refresh`) and committed. Lookup at request
time is a dict hit plus `difflib` fuzzy matching — **no network call ever happens
on a live request**, and a test breaks `httpx` to prove it.

Unknown places return None. They do not fall back to a live geocode, and they do
not guess coordinates; the response says which places we do have.

Place parsing runs *after* ward and mouza have claimed their spans in the
sentence. Without that, "ponds in Ward 108" reads "Ward" as a settlement name and
the whole query collapses — a real regression, now covered by a test.

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

## The database, and when it started mattering

Phase 1 needed no database: `precomputed/` served everything and verdicts went to
a JSON file. That is still true of the read path, and deliberately so — the app
boots from a clone with no credentials of any kind.

Two things changed that. Officer verifications carry a foreign key to `anomaly`,
so with a real `DATABASE_URL` set they fail unless the anomalies exist in
Postgres too. And an open-ended set of user-submitted areas cannot live in a
fixed set of files. Hence `python -m app.seed`: an idempotent upsert of
`precomputed/` into `pond` / `observation` / `anomaly`. `precomputed/` remains the
seed for the EKW demo; the database becomes the source of truth once there is one.

`DATABASE_URL` is normalised in `config.py` rather than in the docs. Neon prints
`postgresql://…?sslmode=require&channel_binding=require`; SQLAlchemy's async
engine needs `postgresql+asyncpg://` and asyncpg rejects both of those libpq
parameters. Both failures surface at connect time, not startup, so they are fixed
once in one place and the console string can be pasted verbatim.

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
| **Natural-language query** | Turn a sentence into a filter object, including a place name | See or produce a number, or resolve a coordinate — the filter runs in Python against `precomputed/`, place names resolve against the cached gazetteer, and the filter is shown back to the officer. The area summary is a format string, not model prose |
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

## The LLM cache, and why it is not optional

`app/services/llm/client.py` reads a write-through response cache under
`precomputed/llm/` before it ever reaches the provider, keyed on a hash of
(model, messages).

The golden rule, applied one layer up. The README already says it about
geocoding; it matters more here, because a geocode is one round trip and a report
completion is 1400 tokens generated while an audience watches. Warming the whole
bundle took 93 seconds once; re-running takes 0.17 and makes no requests, and with
the network severed a radius question and a grounded notice both answer in about
two milliseconds.

Three properties are load-bearing:

- **Writing at request time is safe.** The key is a hash of the exact messages, so
  a new question can only add an entry. Nothing warmed and checked can be altered
  by whatever gets asked on stage.
- **A shipped cache needs no configuration to be read.** `cache_read_any` matches
  on messages alone, so a container with `precomputed/llm/` and no
  `GEMINI_MODEL` still serves model-quality output. Without that the cache was
  unreadable in exactly the deployment it was built for — the image has the cache,
  Render has the key, and a demo box may have neither.
- **Features gate on `is_available()`, not `is_configured()`.** A warm cache alone
  counts. Evidence corroboration is the deliberate exception: it needs a live
  search, and a cached answer about what the public record said last week would be
  worse than an honest "search is switched off".

The provider is Google AI Studio, reached through its OpenAI-compatible endpoint
(`/v1beta/openai/`), so the OpenAI SDK code is unchanged. `response_format=
{"type": "json_object"}` was probed and is honored there, which is what the query,
report and evidence features depend on.

When the cache misses and the provider is still rate limited after
`LLM_MAX_RETRIES`, callers get `LLMUnavailable` — a subclass of `LLMError`, so every existing
`except LLMError` already degrades correctly and nothing needed changing.

## Falling back to synthesis, and where it must not

`run_pipeline.sh` with no arguments looks for real inputs, does not find them,
says so loudly, and synthesises instead. Each fallback is announced in the
terminal at the time and recorded in `manifest.json`, which is what `/api/provenance`
reads. A fresh clone therefore produces a working, clearly-labelled bundle with
zero setup, and there is no `--demo` flag to forget.

**The live slow path deliberately does not do this.** `services/area_processing.py`
catches `EarthEngineUnavailable` and tells the officer satellite access is not
configured. Auto-substituting synthetic results for what is a real request about a
real place would be an integrity regression, not a completion of the feature. The
offline pipeline and the live API are different trust contexts: one is building a
demo bundle, the other is answering someone.

## Saying what is real

`GET /api/provenance` and `/data-sources` list every layer with a status of real,
synthetic or not-run, what produced what is on screen, and what would produce it
for real. The layer list and its wording are declared in code; only the evidence —
manifest provenance, the fallback record, file counts — is read from disk, so a
bundle cannot flatter itself.

Today four layers are real (the application, the basemap, the place names, the
law), four are synthetic (pond boundaries, measurements, the spectral verdict, the
comparison chips), the detector is real and computed, and the live area pipeline
has never been run.

## Sessions, and the demo door

Ported from LoopSpill. `app/core/auth.py` verifies a Neon Managed Better Auth JWT
against Neon's published keys and hands routes a `Principal` or a 401.

**Three states, not two.**

| Request carries | Principal | Can write? |
|---|---|---|
| A valid JWT | the operator | yes |
| `X-LoopSatellite-Demo: session` | `is_demo=True` | **no — 403** |
| Neither, auth configured | — | 401 |

The demo principal is the point. A judge opens the URL, clicks *Continue as
demo*, and uses the entire read path — map, queue, pond detail, radius questions,
grounded notices, reports — with no account. What it cannot do is the two things
that cost something: recording a verification, and `POST /api/areas`, which
starts a Sentinel-2 pull billed to a personal Earth Engine token. Those go through
`require_writable_session`.

**The frontend gate is not the gate.** `RequireSession` decides what renders; it
is JavaScript on the visitor's machine and a debugger steps over it. Protection
is a router-level dependency in `main.py`, applied to every data router in one
place, and `tests/test_auth.py` walks the live OpenAPI schema and fails if any
route is reachable anonymously. That walk originally found *nothing* and passed —
FastAPI includes routers lazily, so `app.routes` is empty of them until the app is
built. `test_there_are_protected_paths_to_test` caught the vacuous version.

`/api/provenance` stays public, a deliberate divergence from LoopSpill, which
protects its equivalent. That endpoint exists to answer "how do we know this works
on real data?" with a link someone can open; behind a session it answers nothing.
It names no pond and reveals no finding.

**Unconfigured is a documented state.** With `NEON_AUTH_URL` unset the API runs
open, logs `<- EVERY ROUTE IS OPEN` at startup and reports it in `/api/health`,
and the front door offers only the demo button. `AUTH_REQUIRED=true` makes the app
refuse to boot without an auth URL — which is what Render should run, because a
deployment that asked for auth and silently got none is worse than one that fails.

## Earth Engine authentication

`app/core/gee_auth.py`. A personal OAuth refresh token from `earthengine
authenticate`, held in one environment variable — not a service account.

This is a knowing trade, not an oversight. The token is a person's identity and a
person's quota, cannot be scoped down, and dies with their Google access. It is
acceptable for a hackathon and not beyond one; the module docstring says so, and
so does the README.

`try_initialize()` is called at startup and never raises: Earth Engine being
unreachable must not stop the API from booting, because everything except one
button works without it. `/api/health` and `/api/areas/capability` report the real
state so the UI can disable that button with a reason instead of failing on
submit.

## Shared detection code

`app/services/detection/flagging.py` holds STL + Seasonal-Hybrid ESD as pure
functions. Both callers import it: `data_pipeline/05_stl_esd_flagging.py` (the
offline EKW run) and `services/area_processing.py` (a newly submitted area).

It lives under `app/` because of dependency direction. The pipeline may depend on
the application; the deployed application must not depend on the pipeline. The
Docker image ships `app/` and not `data_pipeline/`, so an earlier version that
loaded `05_stl_esd_flagging.py` by path worked locally and would have failed in
production.

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
- **A real queue for the slow path.** Area processing runs in-process via
  FastAPI `BackgroundTasks`, which is why `render.yaml` asks for a plan that does
  not sleep. A Background Worker plus a queue is the right shape once this
  carries load.
- **A live run of the area pipeline.** The orchestration, the status lifecycle
  and the failure paths are tested with Earth Engine mocked; the `_gee_*`
  functions themselves have never been executed against live GEE. Give them a
  supervised first run well before you need them.
