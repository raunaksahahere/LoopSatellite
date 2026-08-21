/**
 * Client-side circle preview.
 *
 * Spherical forward calculation, not the WGS84 geodesic the backend uses. At
 * these radii the two differ by well under a metre — invisible on screen. The
 * authoritative geometry is always the one the server builds from the centre and
 * radius it is sent; this exists only so dragging the slider is instant.
 */
const EARTH_RADIUS_KM = 6371.0088

export function circlePolygon(
  lon: number,
  lat: number,
  radiusKm: number,
  numPoints = 64,
): GeoJSON.Feature<GeoJSON.Polygon> {
  const ring: [number, number][] = []
  const angular = radiusKm / EARTH_RADIUS_KM
  const lat1 = (lat * Math.PI) / 180
  const lon1 = (lon * Math.PI) / 180

  for (let i = 0; i <= numPoints; i += 1) {
    const bearing = ((i % numPoints) * 2 * Math.PI) / numPoints
    const lat2 = Math.asin(
      Math.sin(lat1) * Math.cos(angular) + Math.cos(lat1) * Math.sin(angular) * Math.cos(bearing),
    )
    const lon2 =
      lon1 +
      Math.atan2(
        Math.sin(bearing) * Math.sin(angular) * Math.cos(lat1),
        Math.cos(angular) - Math.sin(lat1) * Math.sin(lat2),
      )
    ring.push([(((lon2 * 180) / Math.PI + 540) % 360) - 180, (lat2 * 180) / Math.PI])
  }

  return {
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [ring] },
  }
}

/** Rough zoom that fits a circle of this radius in a typical viewport. */
export function zoomForRadius(radiusKm: number): number {
  return Math.max(8, Math.min(15, 13.5 - Math.log2(Math.max(radiusKm, 0.5))))
}
