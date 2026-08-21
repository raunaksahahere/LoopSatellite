import { useMemo, useState } from 'react'
import Map, { Layer, NavigationControl, Popup, ScaleControl, Source } from 'react-map-gl/maplibre'
import type { MapLayerMouseEvent } from 'react-map-gl/maplibre'
import 'maplibre-gl/dist/maplibre-gl.css'

import type { PondCollection, PondProperties } from '../../lib/types'
import { PondPopup } from './PondMarker'

/** East Kolkata Wetlands. */
const INITIAL_VIEW = { longitude: 88.46, latitude: 22.527, zoom: 12.2 }

/**
 * The map is the anchor of the whole app, so it must render something useful
 * with no configuration at all. This fallback uses OpenStreetMap's raster tiles:
 * no API key, no account, real streets and canals under the ponds.
 *
 * Desaturated and lightened so the basemap stays underneath the data rather than
 * competing with it — the pond colours carry the meaning here.
 *
 * OSM's tile policy is fine for local development and a demo. For anything with
 * real traffic, set VITE_MAPLIBRE_STYLE_URL to a proper style (MapTiler, Protomaps,
 * or a self-hosted one).
 */
const FALLBACK_STYLE = {
  version: 8 as const,
  sources: {
    osm: {
      type: 'raster' as const,
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© OpenStreetMap contributors',
    },
  },
  layers: [
    { id: 'ground', type: 'background' as const, paint: { 'background-color': '#eef1ee' } },
    {
      id: 'osm',
      type: 'raster' as const,
      source: 'osm',
      paint: { 'raster-saturation': -0.55, 'raster-brightness-min': 0.28, 'raster-opacity': 0.85 },
    },
  ],
}

const FILL_COLOR: unknown[] = [
  'match',
  ['get', 'worst_confidence_band'],
  'high', '#b3261e',
  'medium', '#c9820f',
  'low', '#3f6b3a',
  /* no anomaly */ '#2b7fb8',
]

interface Props {
  ponds: PondCollection
  /** Pond ids to emphasise — e.g. the result of a natural-language query. */
  highlighted?: string[]
  onSelect?: (pondId: string) => void
  interactive?: boolean
}

export function MapView({ ponds, highlighted, onSelect, interactive = true }: Props) {
  const [popup, setPopup] = useState<{ lon: number; lat: number; props: PondProperties } | null>(
    null,
  )
  // `||`, not `??`: a blank VITE_MAPLIBRE_STYLE_URL in .env is an empty string,
  // and handing MapLibre an empty style URL leaves the map with no style at all —
  // which silently takes the pond layers down with it.
  const styleUrl = import.meta.env.VITE_MAPLIBRE_STYLE_URL || undefined

  const data = useMemo(() => {
    if (!highlighted) return ponds
    const set = new Set(highlighted)
    return {
      ...ponds,
      features: ponds.features.map((f) => ({
        ...f,
        properties: { ...f.properties, highlighted: set.has(f.properties.id) },
      })),
    }
  }, [ponds, highlighted])

  const dimmed = Boolean(highlighted?.length)

  function handleClick(event: MapLayerMouseEvent) {
    const feature = event.features?.[0]
    if (!feature) {
      setPopup(null)
      return
    }
    const props = feature.properties as unknown as PondProperties
    setPopup({ lon: event.lngLat.lng, lat: event.lngLat.lat, props })
  }

  return (
    <Map
      initialViewState={INITIAL_VIEW}
      mapStyle={styleUrl ?? (FALLBACK_STYLE as never)}
      interactive={interactive}
      interactiveLayerIds={['pond-fill']}
      onClick={handleClick}
      cursor="pointer"
      style={{ width: '100%', height: '100%' }}
    >
      <NavigationControl position="bottom-right" showCompass={false} />
      <ScaleControl position="bottom-left" />

      <Source id="ponds" type="geojson" data={data as never}>
        <Layer
          id="pond-fill"
          type="fill"
          paint={{
            'fill-color': FILL_COLOR as never,
            'fill-opacity': dimmed
              ? (['case', ['get', 'highlighted'], 0.75, 0.14] as never)
              : 0.55,
          }}
        />
        <Layer
          id="pond-outline"
          type="line"
          paint={{
            'line-color': FILL_COLOR as never,
            'line-width': dimmed ? (['case', ['get', 'highlighted'], 3, 0.6] as never) : 1.2,
            'line-opacity': 0.9,
          }}
        />
      </Source>

      {popup && (
        <Popup
          longitude={popup.lon}
          latitude={popup.lat}
          onClose={() => setPopup(null)}
          closeOnClick={false}
          maxWidth="280px"
        >
          <PondPopup pond={popup.props} onOpen={onSelect} />
        </Popup>
      )}
    </Map>
  )
}
