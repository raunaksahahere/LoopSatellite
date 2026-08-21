# Third-party notices

## EOWater — GPL-3.0

`backend/data_pipeline/03_run_wsa_gee.js` is a **derivative work** of
[EOWater](https://github.com/ShiruiH/EOWater) by Shirui Hao et al., licensed under
the GNU General Public License v3.0.

Specifically adapted from `EOWater/GEE_scripts/WSA_monitoring_S2.js`:

- the s2cloudless join and cloud-probability masking (`maskS2Cloud_new`)
- the MNDWI band expression and threshold logic (`addmNDWI_01`)
- the MNDWI threshold of 0.1 and the 40% cloudy-pixel cut
- the output CSV schema `system_time_utc, UNIQUEID, count, area, tile`

**That file is therefore GPL-3.0.** The obligation is scoped to it: no other file
in this repository copies EOWater code. `04_postprocess_timeseries.py` consumes
EOWater's *output format*, which is an interface, not code.

The full GPL-3.0 text is at <https://www.gnu.org/licenses/gpl-3.0.txt> and in the
EOWater clone under `reference-repos/EOWater/LICENSE`.

## Seasonal-Hybrid ESD — MIT

The generalised ESD implementation in
`backend/data_pipeline/05_stl_esd_flagging.py` follows
[nachonavarro/seasonal-esd-anomaly-detection](https://github.com/nachonavarro/seasonal-esd-anomaly-detection)
(MIT licensed), which in turn implements Hochenbaum, Vallis & Kejariwal,
*Automatic Anomaly Detection in the Cloud Via Statistical Learning* (2017).

Re-implemented rather than depended on, for two reasons: the upstream package is
unmaintained on PyPI, and the MAD scale collapses to zero on a flat series, which
happens on a pond that has been completely filled — exactly the case that matters
most here. See the `scale` fallback in `_test_statistic`.

## Wetlands (Conservation and Management) Rules, 2017

`backend/app/rag/documents/wetlands_rules_2017.txt` is the verbatim text of an
Indian statutory instrument, published in The Gazette of India: Extraordinary,
Part II—Section 3—Sub-section (i), G.S.R. 1203(E), 26 September 2017. Retrieved
from the Tamil Nadu State Wetlands Authority's published copy:
<https://tnswa.tn.gov.in/pdf/wetlands%20rules.pdf>

Government of India works of this kind are not under third-party copyright
restriction for reproduction of the text of the law. Page headers, footers and
page numbers were removed during extraction; **no wording was altered**.

## Reference repositories

The clones under `../reference-repos/` (sibling to this project, not inside it,
and gitignored at the workspace level) are consulted, not vendored. They keep
their own licences. Nothing from `WaterDetect`, `geeup`, `legalRAG`,
`fastapi-postgis`, `vite-maplibre-react`, `HLS_with_GEE`, `india-geodata`,
`Leaflet-Before-After-Map-Comparison-Slider`, or the Random-Forest land-cover
notebook has been copied into this repository.

`geeup` is invoked as an external command-line tool by
`backend/data_pipeline/02_upload_gee_assets.py`, which creates no derivative work.

## Runtime dependencies

Python and npm dependencies are declared in `backend/pyproject.toml` and
`frontend/package.json` and carry their own licences.
