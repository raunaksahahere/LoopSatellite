/**
 * LoopSatellite — Step 03: water surface area (WSA) monitoring over the
 * East Kolkata Wetlands, Sentinel-2.
 *
 * Paste into the GEE Code Editor (https://code.earthengine.google.com/) and Run.
 * Exports one CSV per year to Drive, schema-identical to EOWater's exports:
 *     system_time_utc, UNIQUEID, count, area, tile
 * Download those CSVs into backend/data_pipeline/work/gee_exports/ and continue
 * with 04_postprocess_timeseries.py.
 *
 * ---------------------------------------------------------------------------
 * DERIVATIVE WORK NOTICE — GPL-3.0
 *
 * The cloud-masking (`maskS2Cloud_new`), the MNDWI band + threshold logic
 * (`addmNDWI_01`), the MNDWI threshold of 0.1, the 40% cloud cut and the output
 * CSV schema are adapted from EOWater by Shirui Hao et al.,
 * https://github.com/ShiruiH/EOWater, licensed GPL-3.0.
 * This file is therefore also GPL-3.0. See ../../THIRD_PARTY_NOTICES.md.
 *
 * What differs from upstream: upstream resolves waterbodies through a
 * pre-rasterised label image with neighbour-label arithmetic (built for
 * thousands of NSW farm dams across many MGRS tiles). EKW is 42 polygons inside
 * a single tile, so we use vector zonal statistics (`reduceRegions`) over the
 * uploaded FeatureCollection instead — same MNDWI physics, far less machinery.
 * ---------------------------------------------------------------------------
 */

// ===== CONFIG — edit these three ===========================================
var EKW_PONDS = ee.FeatureCollection('projects/YOUR_GEE_PROJECT/assets/EKW/ekw_ponds');
var DRIVE_FOLDER = 'loopsatellite_gee_exports';
var YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025];
// ===========================================================================

// Must stay in lockstep with data_pipeline/common.py
var T_MNDWI = 0.1;    // MNDWI_THRESHOLD
var T_CLOUD = 40;     // CLOUD_THRESHOLD (%)
var SCALE = 10;       // Sentinel-2 green/SWIR working scale (m)
var PIXEL_AREA = 100; // S2_PIXEL_AREA_M2
var TILE = 'EKW';     // single logical tile; kept for schema compatibility

ee.data.setDefaultWorkloadTag('loopsatellite-ekw-wsa');

print('Ponds', EKW_PONDS.size());
print('AOI', EKW_PONDS.geometry().bounds());

// --- Cloud masking (adapted from EOWater, GPL-3.0) -------------------------
function maskS2Cloud_new(image) {
  var s2Joined = ee.Join.saveFirst('cloud_mask').apply({
    primary: image,
    secondary: ee.ImageCollection('COPERNICUS/S2_CLOUD_PROBABILITY'),
    condition: ee.Filter.equals({leftField: 'system:index', rightField: 'system:index'})
  });

  function cloudMask(s2img) {
    var clouds = ee.Image(s2img.get('cloud_mask')).select('probability');
    var cMask = clouds.lt(T_CLOUD);
    return ee.Image(s2img).updateMask(cMask);
  }
  return s2Joined.map(cloudMask);
}

// --- MNDWI + threshold (adapted from EOWater, GPL-3.0) ---------------------
var addmNDWI_01 = function(image) {
  var mndwi = image.expression(
    '(green-SWIR)/(green+SWIR)', {
      'green': image.select('B3'),
      'SWIR': image.select('B11')
    }).rename('mNDWI');
  var thres = mndwi.gte(T_MNDWI).rename('thres');
  return image.addBands(mndwi).addBands(thres);
};

// --- Per-year export -------------------------------------------------------
var aoi = EKW_PONDS.geometry();

YEARS.forEach(function(year) {
  var start = ee.Date.fromYMD(year, 1, 1);
  var end = start.advance(1, 'year');

  var raw = ee.ImageCollection('COPERNICUS/S2_HARMONIZED')
    .filterBounds(aoi)
    .filterDate(start, end)
    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', T_CLOUD));

  var binary = ee.ImageCollection(maskS2Cloud_new(raw))
    .sort('system:time_start')
    .map(addmNDWI_01);

  // For each scene, per pond: water pixel count, and the number of pond pixels
  // that survived cloud masking (`valid`). `valid` is what lets step 04 assign a
  // quality weight and drop passes where most of the pond was under cloud.
  var rows = binary.map(function(img) {
    var sysDate = ee.Date(img.get('system:time_start')).format(null, 'UTC');

    var stack = img.select('thres').unmask(0).rename('water')
      .addBands(img.select('thres').mask().rename('valid'));

    var stats = stack.reduceRegions({
      collection: EKW_PONDS,
      reducer: ee.Reducer.sum(),
      scale: SCALE,
      crs: 'EPSG:32645'  // UTM 45N — covers Kolkata
    });

    return stats.map(function(f) {
      var count = ee.Number(f.get('water'));
      return ee.Feature(null, {
        'system_time_utc': sysDate,
        'UNIQUEID': f.get('GEEID'),
        'count': count,
        'area': count.multiply(PIXEL_AREA),
        'tile': TILE,
        'valid_px': f.get('valid')
      });
    });
  }).flatten();

  Export.table.toDrive({
    collection: rows,
    description: 'LoopSatellite_EKW_S2_' + year,
    folder: DRIVE_FOLDER,
    fileNamePrefix: 'ekw_s2_' + year,
    fileFormat: 'CSV',
    selectors: ['system_time_utc', 'UNIQUEID', 'count', 'area', 'tile', 'valid_px']
  });
});

print('Queued ' + YEARS.length + ' export tasks — open the Tasks tab and Run each.');
