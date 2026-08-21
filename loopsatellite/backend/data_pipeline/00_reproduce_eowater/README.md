# Step 00 — Reproduce EOWater's NSW sample, unmodified

This is the **go/no-go test**. Before pointing anything at the East Kolkata Wetlands,
confirm that the upstream EOWater pipeline runs end-to-end on the data its authors
shipped, on your machine, with your GEE account. If this step fails, every number
downstream is untrustworthy and the failure is in your setup, not in EKW.

Do **not** edit anything here to make it pass.

## What you need

- A Google Earth Engine account with a cloud project (`GEE_PROJECT_ID` in `.env`)
- `earthengine authenticate` already run
- The EOWater clone at `../../../../reference-repos/EOWater/`

## Procedure

1. Open <https://code.earthengine.google.com/> and paste
   `reference-repos/EOWater/GEE_scripts/WSA_monitoring_S2.js` **unmodified**.
   It reads the authors' public NSW assets
   (`projects/nsw-dpe-gee-tst/assets/OFS/...`), so no upload is needed.
2. Set `var tileList = ['55JEG']` (their single test tile — this is the one edit
   the upstream README itself sanctions, to keep the run small).
3. Run it and export the CSV to Drive.
4. Download the CSV into this folder and run the checker:

   ```bash
   python run_check.py path/to/your_export.csv
   ```

## Pass criteria

`run_check.py` compares the schema and the value distribution of your export
against the reference export the EOWater authors committed
(`reference-repos/EOWater/outputs/GEE_outputs/test_S2_OFS_2015_2024_4Y_Tile_55JGH.csv`).

It passes when:

- columns are exactly `system_time_utc, UNIQUEID, count, area, tile`
- `area == count * 100` for every row (S2 10 m pixels)
- there is at least one row per `UNIQUEID` per year in range
- the water-area series for at least one waterbody is non-degenerate
  (not all-zero, not constant)

Only once this passes do you move to `01_polygon_mask.py`.
