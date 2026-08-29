# LoopSatellite

**Built by Loop Errors.**

A satellite-based monitoring tool that tells the difference between a wetland pond
that shrank *because it's April* and one that shrank *because someone filled it
in* — then builds an evidence-backed case an officer can act on.

**Study area:** the East Kolkata Wetlands, West Bengal — 125 km² of Ramsar-protected
bheris under a 1992 Calcutta High Court order, being encroached with no reliable,
current, reproducible measurement of how much water surface is left.

---

## The rule the whole codebase is built around

> **Statistics detects. The LLM builds the case.**

Water detection, seasonality removal and anomaly flagging are 100% deterministic:
MNDWI thresholding, STL decomposition, Seasonal-Hybrid ESD. **No LLM call appears
anywhere in that path.** A language model only touches a finding *after* the
statistics have made it — corroborating it, explaining it, drafting around it, or
answering questions about it.

Never let a model decide whether a pond shrank. Only let it explain or act on a
shrinkage that statistics already flagged. A test walks the import graph and fails
the build if that line is ever crossed.

## The golden rule

All satellite processing happens **offline, before the demo**, and lands in
`backend/precomputed/`. The live app only reads those files: it never triggers an
Earth Engine computation and never downloads anything.

The one deliberate exception is "monitor a new area", which is a different
feature with a different contract — it is explicitly slow, it says so on screen,
and it never falls back to synthesis. See below.

---

## Fast path and slow path are two different features

Blurring them ruins both, so they are separate in the code and a tab apart in the UI.

| | **Ask about an area** | **Monitor a new area** |
|---|---|---|
| The question | "what's going on around Haldia within 5 km?" | "start watching this circle" |
| Cost | milliseconds | **minutes** |
| Touches Earth Engine | never | yes |
| Code | `services/llm/nl_query.py` → `stl_esd.find_near` | `services/areas.py` → `services/area_processing.py` |
| Demo it live? | yes — this *is* the demo | only if you have two minutes |

The slow path is slow for a real reason: telling a filled-in pond apart from one
that is simply between seasons needs about two years of history for that specific
pond. No amount of engineering makes that instant, so the UI shows a status with
an explanation rather than a spinner implying it is nearly done.

**Before any demo, process the areas you might be asked about.** The fast path can
only answer for places already measured — and when they haven't been, it says so
plainly instead of reporting a false all-clear.

The slow path does work now, and finishes in about two minutes, but it is still
the wrong thing to run live: it is billed to a personal Earth Engine quota, it is
capped per user per day, and a free-tier restart can still take a job with it.

---

## Google Earth Engine, without a service account

`earthengine authenticate` writes a personal OAuth refresh token to
`~/.config/earthengine/credentials`. That whole file, on one line, goes into
`EARTHENGINE_CREDENTIALS_JSON`; the project id goes into `GEE_PROJECT_ID`.

Three things that each look like a broken credential and are not:

- Current versions of that command write **no `client_id` or `client_secret`** —
  the OAuth client is the Earth Engine library's own. The file is complete
  without them.
- **Quoting depends on where you paste it.** A `.env` file needs it in single
  quotes, because the value is full of double quotes and dotenv stops at the
  first one. A hosting dashboard takes the value literally, so paste it bare.
  Both are accepted, but the wrong one used to read as "not valid JSON".
- **Enabling the Earth Engine API and registering the project are two different
  steps**, in two different consoles, and the errors are easy to confuse. The
  token must also belong to an account with access to that project — a Cloud
  console URL carrying `authuser=3` is a warning sign.


**Know what this trades away.** The token carries a *person's* Google identity and
a *person's* Earth Engine quota — every tile the service pulls is billed to them,
it cannot be scoped down, and revoking their account breaks production. A service
account remains the correct long-term answer. This is a deliberate short-term
substitution, documented at the top of `backend/app/core/gee_auth.py`, and it
should not outlive the hackathon.

Only the slow path uses it. Nothing an officer asks about an existing area
touches Earth Engine.

---

## Deployment

Backend on Render, frontend on Vercel, database on Neon.

```
render.yaml               blueprint — Docker web service, health check, env var names
backend/Dockerfile        python:3.12-slim + the [server] extra, RAG index baked in
frontend/vercel.json      Vite build + SPA rewrite so /queue survives a refresh
```

Set the secrets in the Render dashboard (all are `sync: false`, so none is in the
repository) and point `CORS_ORIGINS` at the Vercel URL — the allowlist is
explicit, never `*`. On Vercel, set `VITE_API_BASE_URL` to the Render URL.

Two things to know before relying on it:

- **The slow path runs inside the web process.** Its Earth Engine calls are
  synchronous and take minutes, so they run in a worker thread — awaiting them on
  the event loop starved the health check, Render restarted the instance as
  unresponsive, and the restart killed the job along with the handler that would
  have recorded the failure. Jobs that stop reporting for twelve minutes are
  marked failed rather than left spinning. If this ever becomes load-bearing it
  belongs in a Background Worker with a real queue, not in the web process at all.
- **Neon's connection string works exactly as printed.** `config.py` rewrites the
  driver to asyncpg and translates `sslmode` / `channel_binding`, which asyncpg
  rejects outright.

---

## Getting in

`/` is a public homepage explaining what the tool measures and how. `/welcome` is
the door: **sign in, or create an account** — both through Clerk, both on the same
screen.

There is no "continue as demo". There used to be, because a visitor with no
account had no way in at all; Clerk offers sign-up, so the reason is gone, and
with it a header anyone could send to read the entire API without ever having an
account. Two states now: a valid Clerk JWT, or 401.

The API verifies the token itself against Clerk's published keys — `iss` against
`CLERK_ISSUER`, and `azp` against `CLERK_AUTHORIZED_PARTIES` when set, which is
what stops a token minted for this instance being replayed from someone else's
page. The React route guard decides what *renders*; it guards nothing on its own.

**Any signed-in user can submit an area.** That is deliberate, and it is also the
one route that costs money — a real Sentinel-2 pull billed to a personal Earth
Engine token. So it is capped over a rolling 24 hours, per person and per
deployment (`AREA_QUOTA_PER_USER_PER_DAY`, `AREA_QUOTA_PER_DAY`), counted in
Postgres rather than in memory because a free-tier instance sleeps and may run
more than one worker. Over the cap is a 429 with `Retry-After`, and
`/api/areas/capability` reports the remaining allowance so the button can say so
before anyone fills in a form.

With `CLERK_ISSUER` unset — which is how this ships — the API runs open and says
so at startup and in `/api/health`. Set `AUTH_REQUIRED=true` on a deployment and
it refuses to boot unconfigured rather than quietly serving everything to
everyone.

---

## A demo should make zero network calls

Three things could reach for the network mid-demo. None of them does.

| | How |
|---|---|
| Satellite imagery | Processed offline into `backend/precomputed/`. The API only reads it. |
| Geocoding | A gazetteer resolved once from Nominatim and committed. A test breaks `httpx` to prove lookups still work. |
| The language model | A write-through response cache under `precomputed/llm/`, warmed ahead of time. |

```bash
cd backend && .venv/bin/python -m app.llm_warm
```

Warming the demo surface — the four example questions, plus a report and a notice
for the events a demo touches, plus the whole-site report — takes about a minute
once. Re-running makes no requests at all. Verified with `httpx` patched to raise
on any send: **every warm job served from cache, zero network calls, 0.01
seconds**.

The cache is keyed on a hash of the exact messages, so warming can safely happen
at request time too — a new question adds an entry and can never overwrite a
warmed one. It is also keyed loosely enough to survive a provider change: when
this moved from OpenRouter to Google AI Studio, `llm_warm` reported *"warmed 0 ·
already cached 27"* and the migration cost nothing to re-warm.

If the cache misses anyway, a 429 is retried with exponential backoff (honouring
Google's `Retry-After`), inside a wall-clock budget (`LLM_TOTAL_BUDGET`, default
75s) with an explicit per-request timeout — so a stalled free-tier endpoint
degrades to the deterministic path in bounded time instead of holding a web
request open for minutes. The notice still quotes the real Rules either way; that
comes from retrieval, not from the model.

One caveat: the notice prompt embeds today's date, so notice cache entries go
stale at midnight. Re-run `llm_warm` on the morning of a demo.

---

## Data — read this before demoing

**The bundle in `backend/precomputed/` is measured, not invented.**
`manifest.json` carries `is_synthetic: false`, there are no recorded fallbacks,
and the pipeline finishes with *"Done — every step ran on real inputs."*

| | |
|---|---|
| Pond boundaries | **160 real polygons**, OpenStreetMap water and aquaculture over the EKW extent (ODbL) |
| Water surface | **104,160 Sentinel-2 measurements**, 2019–2026, 84 monthly points per pond |
| What replaced the water | **Real NDBI/BSI**, 414 windows, none failed |
| Findings | **414 water-loss events** — 35 high confidence, 239 medium, 140 low; 39 never recovered |

Real data is noisier than invented data and the numbers say so: an earlier
synthetic bundle produced 12 tidy events, and the conversion split moved the
other way once a generator told to make encroachment obvious was replaced by a
measurement that was not.

Some of it is worth knowing before you trust a single finding. **Median 6 clear
satellite passes** stand behind a flagged window, but the range runs 0 to 59, and
**14 of the 414 rest on no clear pass at all** — windows reconstructed entirely
from neighbouring months because cloud left nothing usable. Every finding states
its own pass count on screen rather than leaving you to assume.

Running `./run_pipeline.sh` with no arguments still uses whatever real inputs
exist and synthesises only what is missing, announcing each fallback in the
terminal **and** in `manifest.json` — so a fresh clone with no credentials gets a
working, clearly-labelled bundle with zero setup. There is no flag to remember;
dropping real inputs in is what makes it stop synthesising.

## Seeing what is real

`/data-sources` answers "how do we know this works on real data?" with a URL
rather than a paragraph in this file. Every layer carries a status, what produced
what is on screen right now, and what would produce it for real. The statuses are
declared in the code that serves the page and the evidence is read from disk, so
a bundle cannot flatter itself.

**Eight of ten layers are real:** the application, the basemap, place names, the
legal corpus, pond boundaries, water measurements, the detector, and the spectral
verdict. The two that are not say so — the before/after chips are scale diagrams
of measured extent rather than photographs, and the live "monitor a new area"
path is listed as what it is.

**Reproducing the bundle from scratch**, with Earth Engine credentials and a
registered Cloud project:

1. `data_pipeline/00_reproduce_eowater/` — reproduce EOWater's NSW sample first.
   A go/no-go: if upstream does not reproduce on your machine, nothing downstream
   is trustworthy.
2. `01a_fetch_osm_ponds.py` — real pond boundaries from OpenStreetMap, with block
   and locality labels taken from OSM administrative relations and place nodes.
   KMC ward numbers are not mapped in OSM, so they are left empty rather than
   invented.
3. `03_run_wsa_gee.py` — monthly water area per pond, straight to CSV. The
   `.js` twin still works in the Code Editor; the Python port exists because a
   step needing a human in a browser is a step that never runs, which is why this
   project shipped on synthetic measurements for as long as it did.
4. `06a_export_spectral.py` — NDBI/BSI before and after each flagged window.
5. `./run_pipeline.sh` — steps 01 and 04–07, using every real input it finds.

Nothing else changes. The API, the UI and the tests are indifferent to which
bundle they serve — except that the synthetic warnings disappear.

## What it does

### The map — `/map`

160 measured pond boundaries over the wetlands, coloured by whether anything is
flagged and how confident it is. Click a pond for its case. Two modes sit above
it, and they are two different features rather than two spellings of one:

**Ask about an area** answers in milliseconds from measurements already made.
**Monitor a new area** starts a real satellite pull and takes minutes.

### The verification queue — `/queue`

A ranked list of the water losses the season does not explain, highest confidence
and largest loss first, each with a before/after chip, a confidence badge and one
button. This is the working screen.

### One finding — `/pond/:id`

- **The chart** — 84 monthly points of measured water area with the seasonal
  expectation drawn over it, the flagged window shaded, and months with no usable
  pass drawn hollow rather than silently interpolated into the line.
- **Before and after** — a slider over scale diagrams of the measured extent.
  Labelled as diagrams, because they are not photographs.
- **How well observed it is** — the confidence band, how many clear satellite
  passes fell inside the window, how many months had none, and how much of the
  pond was visible on average. Deliberately *not* an error bar: the detector
  scores confidence, it does not estimate a range around the loss percentage, and
  inventing one would be the same sin as inventing the measurement.
- **Where it has got to** — awaiting review, or the verdict recorded against it
  and what that means next. There is no "filed with the pollution control board"
  state, because nothing here files anything.
- **Why it was flagged** — the loss, the area, the window, whether it came back,
  in plain words, with the statistics one disclosure triangle away.
- **What replaced the water** — the measured spectral verdict: built up, bare
  earth, or neither.
- **Record a verdict** — confirmed, seasonal, unclear, or already being dealt
  with, with a note. The one write in the product.

### Four things a language model does — none of which can change a finding

1. **Evidence corroboration** — searches the public record for this locality and
   this window; returns findings with links and an explicit relevance verdict, or
   says plainly that it found nothing.
2. **Regulatory grounding and notice drafting** — retrieves the provisions
   engaged from the source instruments (96 chunks of the Wetlands (Conservation
   and Management) Rules, 2017, quoted verbatim with citations) and drafts a
   show-cause notice around them. If retrieval finds nothing relevant it **does
   not draft**. If a draft cites a provision that was not retrieved, the draft is
   discarded.
3. **Natural-language query** — "which ponds in Ward 108 lost more than 20% and
   never recovered", or "problems around Haldia within 5 km". The model turns the
   sentence into a filter; the filter runs in Python against measured data; the
   map flies to the place, draws the radius and highlights the answer. The model
   never sees a number and never resolves a coordinate — every coordinate comes
   from a **cached gazetteer of 56 West Bengal places**, built once from Nominatim
   and committed, so no geocoding call happens at request time. A place we do not
   have says so and offers the ones we do. A distance is only ever drawn if the
   question actually contained one; otherwise the default radius is used and
   labelled as an assumption.
4. **Report writer** — fills a fixed template and hands off to a ReportLab PDF.
   Every figure in that PDF comes from the data, not from the prose.

### Monitoring somewhere new

Submit a point and a radius and the app measures it for real: persistent water
bodies from JRC Global Surface Water, then three years of monthly Sentinel-2
water area for each, then the same detector. **About two minutes**, and radius
barely matters — the work is 36 sequential monthly requests whether the circle
holds one water body or fifty.

It reports progress by month while it runs, and it fails honestly: no water
bodies found says why and suggests a wider radius, and a job killed by a restart
is marked failed rather than left spinning. Results are written to Postgres and
are queryable afterwards.

## Built for a wetlands officer, not a developer

One primary action per screen. No "MNDWI" or "STL residual" in the copy — a test
enforces that — with the technical terms one disclosure triangle away under *How
this was detected*. Colour-coded confidence bands instead of decimals. 48px
minimum touch targets, because this may be read on a phone in the field. Loading
and empty states are designed screens: *"No water loss flagged — that is a good
result, not an error."* The map is the anchor and every path returns to it.

---

## Layout

```
LoopSatellite/
├── backend/
│   ├── app/           FastAPI — reads precomputed/, never computes
│   ├── data_pipeline/ OFFLINE satellite pipeline, steps 00–07
│   │                  01a fetches real OSM boundaries; 03 and 06a run the
│   │                  Earth Engine exports from Python, no Code Editor needed
│   ├── precomputed/   the only thing the live app reads
│   └── tests/
├── frontend/          React + Vite + MapLibre + Recharts
├── docs/architecture.md
├── render.yaml
└── reference-repos/   cloned repos — gitignored, never in this history
```

`docs/architecture.md` has the detector's internals, the fast/slow split, the JSONB-not-PostGIS
decision and its migration path, and what was deliberately left unbuilt.
`THIRD_PARTY_NOTICES.md` scopes the GPL-3.0 obligation from EOWater to the one
file that inherits it.

## Stack

PostgreSQL (Neon, geometries as GeoJSON in JSONB — no PostGIS) · FastAPI ·
SQLAlchemy + Alembic · Clerk (JWT verified against its JWKS) · Google AI Studio
(Gemini, through the OpenAI SDK's compatibility layer) · React + Vite +
TypeScript · MapLibre GL · Recharts · ReportLab · Earth Engine (personal OAuth
token) + `statsmodels` + `pyproj` · OpenStreetMap Overpass and Nominatim (build
time only) · Render + Vercel.
