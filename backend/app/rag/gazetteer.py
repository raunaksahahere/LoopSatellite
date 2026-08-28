"""Place-name lookup for radius queries.

Two layers, and the split matters:

  1. **A cached JSON gazetteer** (`gazetteer.json`, tracked in git) that this
     module loads at import. Every lookup at request time is a dict lookup and a
     `difflib` fuzzy match against names already in memory. **No network call
     ever happens on a live request** — which is the only reason
     "problems around Haldia within 5 km" can answer in milliseconds.

  2. **Nominatim** (OpenStreetMap, free, no key), used *only* by
     `python -m app.rag.gazetteer --refresh` to build that cache ahead of time,
     or to resolve a genuinely new name during development.

If a place is not in the cache, `resolve()` returns None and the caller says so
plainly. It does not guess coordinates, and it does not reach for the network to
cover the gap — a demo that silently makes an outbound call is a demo that breaks
on conference wifi.
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

GAZETTEER_PATH = Path(__file__).resolve().parent / "gazetteer.json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim's usage policy requires an identifying User-Agent and at most one
# request per second. Both are honoured in `_geocode`.
USER_AGENT = "LoopSatellite/0.2 (wetland monitoring; contact via repository)"
REQUEST_INTERVAL_S = 1.1

# Places a West Bengal officer might plausibly ask about. Resolved once.
SEED_PLACES: list[str] = [
    # The study area itself, and the city it sits inside.
    "East Kolkata Wetlands, West Bengal, India",
    "Kolkata, West Bengal, India",
    "Salt Lake City, Kolkata, West Bengal, India",
    "New Town, Kolkata, West Bengal, India",
    "Rajarhat, West Bengal, India",
    "Bhangar, West Bengal, India",
    "Sonarpur, West Bengal, India",
    "Bidhannagar, West Bengal, India",

    # Other Ramsar and wetland-adjacent sites in the state. A question about
    # water loss is not only a question about the EKW.
    "Sundarbans, West Bengal, India",
    "Santragachi Jheel, Howrah, West Bengal, India",
    "Rasikbil, Cooch Behar, West Bengal, India",
    "Ahiron Beel, Murshidabad, West Bengal, India",

    # District and divisional headquarters — the places an officer names.
    "Howrah, West Bengal, India",
    "Haldia, West Bengal, India",
    "Kharagpur, West Bengal, India",
    "Durgapur, West Bengal, India",
    "Asansol, West Bengal, India",
    "Siliguri, West Bengal, India",
    "Malda, West Bengal, India",
    "Digha, West Bengal, India",
    "Bardhaman, West Bengal, India",
    "Krishnanagar, West Bengal, India",
    "Barasat, West Bengal, India",
    "Diamond Harbour, West Bengal, India",
    "Canning, West Bengal, India",
    "Baharampur, West Bengal, India",
    "Berhampore, West Bengal, India",
    "Raiganj, West Bengal, India",
    "Balurghat, West Bengal, India",
    "Jalpaiguri, West Bengal, India",
    "Cooch Behar, West Bengal, India",
    "Alipurduar, West Bengal, India",
    "Darjeeling, West Bengal, India",
    "Kalimpong, West Bengal, India",
    "Purulia, West Bengal, India",
    "Bankura, West Bengal, India",
    "Suri, Birbhum, West Bengal, India",
    "Tamluk, West Bengal, India",
    "Contai, West Bengal, India",
    "Jhargram, West Bengal, India",
    "Midnapore, West Bengal, India",
    "Serampore, West Bengal, India",
    "Chandannagar, West Bengal, India",
    "Chinsurah, West Bengal, India",
    "Kalyani, West Bengal, India",
    "Ranaghat, West Bengal, India",
    "Basirhat, West Bengal, India",
    "Bongaon, West Bengal, India",
    "Habra, West Bengal, India",
    "Baruipur, West Bengal, India",
    "Budge Budge, West Bengal, India",
    "Uluberia, West Bengal, India",
    "Arambagh, West Bengal, India",
    "Katwa, West Bengal, India",
    "Kalna, West Bengal, India",
    "Bolpur, West Bengal, India",
    "Islampur, Uttar Dinajpur, West Bengal, India",
    "Dhupguri, West Bengal, India",
    "Mekliganj, West Bengal, India",
]

# Match threshold for difflib. Below this, we would rather say "not found" than
# send an officer to the wrong district.
FUZZY_CUTOFF = 0.72


@dataclass(frozen=True)
class Place:
    name: str            # short display name, e.g. "Haldia"
    query: str           # the string that was resolved
    lat: float
    lon: float
    display_name: str    # Nominatim's full label, kept for provenance
    osm_type: str | None = None
    osm_id: int | None = None
    source: str = "nominatim"


# ---------------------------------------------------------------------------
# Runtime — cache only, never the network
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _cache() -> dict[str, Place]:
    if not GAZETTEER_PATH.exists():
        logger.warning(
            "No gazetteer at %s — run `python -m app.rag.gazetteer --refresh`", GAZETTEER_PATH
        )
        return {}
    with GAZETTEER_PATH.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    return {p["name"].lower(): Place(**p) for p in payload.get("places", [])}


def reload_cache() -> None:
    _cache.cache_clear()


def all_places() -> list[Place]:
    return sorted(_cache().values(), key=lambda p: p.name)


def names() -> list[str]:
    return [p.name for p in all_places()]


def resolve(query: str) -> Place | None:
    """Find a place by name. Exact, then substring, then fuzzy. Never networked."""
    if not query:
        return None
    cache = _cache()
    if not cache:
        return None

    key = query.strip().lower()

    if key in cache:
        return cache[key]

    # Substring: "the East Kolkata Wetlands" -> "east kolkata wetlands".
    # Longest name first so "Kolkata" doesn't win over "East Kolkata Wetlands".
    for name in sorted(cache, key=len, reverse=True):
        if name in key or key in name:
            return cache[name]

    matches = difflib.get_close_matches(key, list(cache), n=1, cutoff=FUZZY_CUTOFF)
    return cache[matches[0]] if matches else None


def suggestions(query: str, n: int = 5) -> list[str]:
    """Names to offer when a lookup failed — used in the 'not found' response."""
    cache = _cache()
    if not cache:
        return []
    close = difflib.get_close_matches(query.strip().lower(), list(cache), n=n, cutoff=0.4)
    out = [cache[c].name for c in close]
    # Top up with real names. One weak fuzzy hit is worse than no hint at all:
    # "Chittagong" scrapes past the cutoff against "Canning", and offering that
    # alone reads as "did you mean Canning?" rather than "here is what we cover".
    for name in names():
        if len(out) >= n:
            break
        if name not in out:
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# Build time — Nominatim
# ---------------------------------------------------------------------------
def _geocode(query: str) -> Place | None:
    import httpx

    try:
        response = httpx.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1, "addressdetails": 0},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
            timeout=20.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        results = response.json()
    except Exception as exc:  # noqa: BLE001 - one bad lookup must not abort the refresh
        logger.warning("Nominatim failed for %r: %s", query, exc)
        return None

    if not results:
        return None

    hit = results[0]
    return Place(
        name=query.split(",")[0].strip(),
        query=query,
        lat=float(hit["lat"]),
        lon=float(hit["lon"]),
        display_name=hit.get("display_name", query),
        osm_type=hit.get("osm_type"),
        osm_id=int(hit["osm_id"]) if hit.get("osm_id") else None,
    )


def refresh(queries: list[str] | None = None, *, merge: bool = True) -> list[Place]:
    """Resolve place names against Nominatim and write the cache. Build-time only."""
    queries = queries or SEED_PLACES
    existing = {p.name.lower(): p for p in all_places()} if merge else {}

    for i, query in enumerate(queries):
        if i:
            time.sleep(REQUEST_INTERVAL_S)  # Nominatim: max 1 request per second
        place = _geocode(query)
        if place is None:
            print(f"  MISS  {query}")
            continue
        existing[place.name.lower()] = place
        print(
            f"  ok    {place.name:<22} {place.lat:>9.5f}, {place.lon:>9.5f}"
            f"  {place.display_name[:58]}"
        )

    places = sorted(existing.values(), key=lambda p: p.name)
    with GAZETTEER_PATH.open("w", encoding="utf-8") as fh:
        json.dump(
            {
                "source": "OpenStreetMap / Nominatim, © OpenStreetMap contributors (ODbL)",
                "note": "Resolved at build time. The running service never calls Nominatim.",
                "places": [asdict(p) for p in places],
            },
            fh,
            indent=1,
            ensure_ascii=False,
        )
        fh.write("\n")
    reload_cache()
    return places


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="re-resolve the seed list")
    ap.add_argument("--add", nargs="+", metavar="PLACE", help="resolve extra place names")
    ap.add_argument("--check", metavar="QUERY", help="test a lookup against the cache")
    args = ap.parse_args()

    if args.refresh or args.add:
        queries = SEED_PLACES if args.refresh else []
        queries += args.add or []
        print(f"Resolving {len(queries)} place(s) via Nominatim (~{len(queries) * 1.1:.0f}s)…")
        places = refresh(queries)
        print(f"\nGazetteer now holds {len(places)} places -> {GAZETTEER_PATH}")
    elif args.check:
        place = resolve(args.check)
        if place:
            print(f"{args.check!r} -> {place.name} ({place.lat}, {place.lon})")
            print(f"   {place.display_name}")
        else:
            print(f"{args.check!r} -> not found. Did you mean: {', '.join(suggestions(args.check))}")
    else:
        for p in all_places():
            print(f"  {p.name:<22} {p.lat:>9.5f}, {p.lon:>9.5f}")


if __name__ == "__main__":
    main()
