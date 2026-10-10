"""
Automatic distance lookup between two place names.

Uses free OpenStreetMap services (no API key, standard library only):
  1. Nominatim  -> turns "Indore" into latitude/longitude
  2. OSRM       -> real road distance between the two points
If the routing service is unreachable we fall back to the straight-line
(great-circle) distance x 1.3, clearly flagged as an estimate.

Needs an internet connection when running.
"""
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
USER_AGENT = "SmartTravel-student-project/1.0 (route comparison)"
TIMEOUT_SEC = 8
STRAIGHT_LINE_FACTOR = 1.3  # roads are longer than a straight line
COUNTRY_CODES = None        # e.g. "in" to restrict searches to India


_last_nominatim_call = 0.0


def _throttle():
    """Nominatim's usage policy: max 1 request per second."""
    global _last_nominatim_call
    wait = 1.05 - (time.monotonic() - _last_nominatim_call)
    if wait > 0:
        time.sleep(wait)
    _last_nominatim_call = time.monotonic()


class DistanceError(Exception):
    """Raised when a place can't be found or no distance can be worked out."""


@dataclass
class RouteDistance:
    km: float
    source: str        # "road" or "estimate"
    from_name: str
    to_name: str

    @property
    def source_label(self):
        if self.source == "road":
            return "driving distance via OpenStreetMap"
        return "approximate straight-line estimate (x1.3)"


def _http_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@lru_cache(maxsize=256)
def geocode(place):
    """Return (lat, lon, display_name) for a place name."""
    params = {"q": place, "format": "json", "limit": 1}
    if COUNTRY_CODES:
        params["countrycodes"] = COUNTRY_CODES
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode(params)
    _throttle()
    try:
        results = _http_get_json(url)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        raise DistanceError(
            "Could not reach the map service. Check your internet connection "
            "or enter the distance manually."
        )
    if not results:
        raise DistanceError(f"Could not find the place '{place}'. Try a more specific name.")
    top = results[0]
    name = ", ".join(top.get("display_name", place).split(", ")[:2])
    return float(top["lat"]), float(top["lon"]), name


def _road_km(lat1, lon1, lat2, lon2):
    url = OSRM_URL.format(lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2) + "?overview=false"
    try:
        data = _http_get_json(url)
        if data.get("code") == "Ok" and data.get("routes"):
            return data["routes"][0]["distance"] / 1000
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, KeyError):
        pass
    return None


def get_route_distance(origin, destination):
    """Main entry point: place names in, RouteDistance out."""
    origin, destination = origin.strip(), destination.strip()
    if not origin or not destination:
        raise DistanceError("Please enter both a starting point and a destination.")

    lat1, lon1, name1 = geocode(origin)
    lat2, lon2, name2 = geocode(destination)

    straight = haversine_km(lat1, lon1, lat2, lon2)
    if straight < 0.05:
        raise DistanceError("Start and destination are the same place.")

    road = _road_km(lat1, lon1, lat2, lon2)
    if road:
        return RouteDistance(round(road, 1), "road", name1, name2)
    return RouteDistance(round(straight * STRAIGHT_LINE_FACTOR, 1), "estimate", name1, name2)
