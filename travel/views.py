import math
import hashlib
import requests

from datetime import date, time
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.cache import cache
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import SavedTrip
from .routes import RouteAPIError, calculate_google_route

import requests
from django.conf import settings
from django.http import JsonResponse

RAILRADAR_BASE_URL = "https://api.railradar.in/v1"

# Cache durations in seconds
STATION_CACHE_TTL = 60 * 60 * 24
TRAIN_CACHE_TTL = 60 * 60
GEOMETRY_CACHE_TTL = 60 * 60 * 24


# =========================================================
# RAILRADAR API HELPER WITH CACHING
# =========================================================

def _railradar_cache_key(path, params=None):
    params = params or {}

    raw = (
        path
        + "|"
        + "&".join(
            f"{key}={params[key]}"
            for key in sorted(params)
        )
    )

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()

    return f"railradar:{digest}"


def railradar_get(path, params=None):
    """
    Fetch RailRadar data with caching.
    Successful responses are cached to reduce API usage.
    """

    api_key = getattr(settings, "TRAIN_API_KEY", "")

    if not api_key:
        raise ValueError(
            "RailRadar API key is not configured."
        )

    params = params or {}
    cache_key = _railradar_cache_key(path, params)

    cached_data = cache.get(cache_key)

    if cached_data is not None:
        return cached_data

    response = requests.get(
        f"{RAILRADAR_BASE_URL}{path}",
        headers={
            "Authorization": f"Bearer {api_key}",
        },
        params=params,
        timeout=15,
    )

    if response.status_code == 429:
        raise requests.HTTPError(
            "RailRadar rate limit reached.",
            response=response,
        )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError(
            "Invalid response from RailRadar."
        )

    if not payload.get("success"):
        raise ValueError(
            payload.get(
                "message",
                "RailRadar request failed.",
            )
        )

    data = payload.get("data", {})

    if path.startswith("/lookup/search/stations"):
        timeout = STATION_CACHE_TTL
    elif "/route" in path:
        timeout = GEOMETRY_CACHE_TTL
    else:
        timeout = TRAIN_CACHE_TTL

    cache.set(
        cache_key,
        data,
        timeout,
    )

    return data


# =========================================================
# STATION HELPERS
# =========================================================

def _norm(value):
    return str(value or "").strip().casefold()


def _station_code(station):
    if not isinstance(station, dict):
        return ""

    return str(
        station.get("code")
        or station.get("stationCode")
        or ""
    ).strip()


def find_station(location):
    """
    Resolve a station name using cached data first.
    """

    location = str(location or "").strip()

    if not location:
        return None

    custom_key = (
        "railradar:station-name:"
        + hashlib.sha256(
            location.casefold().encode("utf-8")
        ).hexdigest()
    )

    cached_station = cache.get(custom_key)

    if cached_station is not None:
        return cached_station

    data = railradar_get(
        "/lookup/search/stations",
        params={
            "q": location,
            "limit": 10,
        },
    )

    if isinstance(data, dict):
        data = data.get(
            "stations",
            data.get("results", []),
        )

    if not isinstance(data, list) or not data:
        return None

    query = _norm(location)
    station = None

    # Exact name/code/city match first.
    for item in data:
        if not isinstance(item, dict):
            continue

        values = {
            _norm(item.get("code")),
            _norm(item.get("stationCode")),
            _norm(item.get("name")),
            _norm(item.get("city")),
        }

        if query in values:
            station = item
            break

    # Prefer exact city match.
    if station is None:
        for item in data:
            if (
                isinstance(item, dict)
                and _norm(item.get("city")) == query
            ):
                station = item
                break

    # Use provider's first result as a last resort.
    if station is None:
        station = next(
            (
                item for item in data
                if isinstance(item, dict)
            ),
            None,
        )

    if station is not None:
        cache.set(
            custom_key,
            station,
            STATION_CACHE_TTL,
        )

    return station


# =========================================================
# POLYLINE HELPERS
# =========================================================

def _decode_polyline(encoded):
    if not encoded:
        return []

    points = []
    index = 0
    lat = 0
    lng = 0

    try:
        while index < len(encoded):
            values = []

            for _ in range(2):
                result = 0
                shift = 0

                while True:
                    byte = ord(encoded[index]) - 63
                    index += 1

                    result |= (
                        (byte & 0x1F) << shift
                    )

                    shift += 5

                    if byte < 0x20:
                        break

                if result & 1:
                    value = ~(result >> 1)
                else:
                    value = result >> 1

                values.append(value)

            lat += values[0]
            lng += values[1]

            points.append(
                (lat / 1e5, lng / 1e5)
            )

    except (
        IndexError,
        TypeError,
        ValueError,
    ):
        return []

    return points


def _encode_polyline(points):
    output = []
    last_lat = 0
    last_lng = 0

    for lat, lng in points:
        lat_i = round(lat * 1e5)
        lng_i = round(lng * 1e5)

        for value, previous in (
            (lat_i, last_lat),
            (lng_i, last_lng),
        ):
            delta = value - previous

            if delta < 0:
                encoded_value = ~(delta << 1)
            else:
                encoded_value = delta << 1

            while encoded_value >= 0x20:
                output.append(
                    chr(
                        (0x20 | (encoded_value & 0x1F))
                        + 63
                    )
                )

                encoded_value >>= 5

            output.append(
                chr(encoded_value + 63)
            )

        last_lat = lat_i
        last_lng = lng_i

    return "".join(output)


# =========================================================
# TRAIN STOP HELPERS
# =========================================================

def _stop_code(stop):
    station = (
        stop.get("station")
        if isinstance(stop.get("station"), dict)
        else {}
    )

    return str(
        stop.get("stationCode")
        or stop.get("code")
        or station.get("code")
        or ""
    ).strip()


def _stop_name(stop):
    station = (
        stop.get("station")
        if isinstance(stop.get("station"), dict)
        else {}
    )

    return str(
        stop.get("stationName")
        or stop.get("name")
        or station.get("name")
        or ""
    ).strip()


def _stop_lat_lng(stop):
    location = (
        stop.get("location")
        if isinstance(stop.get("location"), dict)
        else {}
    )

    lat = stop.get(
        "lat",
        stop.get(
            "latitude",
            location.get("lat"),
        ),
    )

    lng = stop.get(
        "lng",
        stop.get(
            "longitude",
            location.get("lng"),
        ),
    )

    try:
        lat = float(lat)
        lng = float(lng)

        if math.isfinite(lat) and math.isfinite(lng):
            return lat, lng

    except (TypeError, ValueError):
        pass

    return None


def _nearest_polyline_index(points, coordinate):
    if not points or not coordinate:
        return None

    lat, lng = coordinate

    return min(
        range(len(points)),
        key=lambda index: (
            (points[index][0] - lat) ** 2
            + (points[index][1] - lng) ** 2
        ),
    )


# =========================================================
# CLIP TRAIN GEOMETRY
# =========================================================

def clip_train_geometry(
    geometry_data,
    source_station,
    destination_station,
):
    if not isinstance(geometry_data, dict):
        return ""

    encoded = (
        geometry_data.get("encodedPolyline")
        or geometry_data.get("polyline")
        or ""
    )

    points = _decode_polyline(encoded)
    stops = geometry_data.get("stops") or []

    if not isinstance(stops, list) or len(points) < 2:
        return ""

    source_code = _station_code(source_station)
    destination_code = _station_code(destination_station)

    source_name = _norm(source_station.get("name"))
    destination_name = _norm(destination_station.get("name"))

    source_index = None
    destination_index = None

    for index, stop in enumerate(stops):
        if not isinstance(stop, dict):
            continue

        code = _stop_code(stop)
        name = _norm(_stop_name(stop))

        if source_index is None:
            if (
                source_code
                and code.casefold() == source_code.casefold()
            ) or (
                source_name and name == source_name
            ):
                source_index = index

        if destination_index is None:
            if (
                destination_code
                and code.casefold() == destination_code.casefold()
            ) or (
                destination_name and name == destination_name
            ):
                destination_index = index

    if (
        source_index is None
        or destination_index is None
        or source_index == destination_index
    ):
        return ""

    start_coordinate = _stop_lat_lng(
        stops[source_index]
    )

    end_coordinate = _stop_lat_lng(
        stops[destination_index]
    )

    if not start_coordinate or not end_coordinate:
        return ""

    start = _nearest_polyline_index(
        points,
        start_coordinate,
    )

    end = _nearest_polyline_index(
        points,
        end_coordinate,
    )

    if start is None or end is None or start == end:
        return ""

    # Keep geometry in the order travelled.
    if source_index > destination_index:
        start, end = end, start

    if start > end:
        start, end = end, start

    segment = points[start:end + 1]

    if len(segment) < 2:
        return ""

    return _encode_polyline(segment)


# =========================================================
# DURATION FORMATTER
# =========================================================

def _format_duration(minutes):
    hours, mins = divmod(int(minutes), 60)

    if hours and mins:
        return f"{hours} hr {mins} min"

    if hours:
        return f"{hours} hr"

    return f"{mins} min"


# =========================================================
# GET TRAIN ROUTES
# =========================================================

def get_train_routes(source, destination, travel_date=""):
    """
    Train search is cached by station pair and travel date.
    Only the first three train options are processed.
    """

    result_key_raw = (
        f"{_norm(source)}|"
        f"{_norm(destination)}|"
        f"{travel_date}"
    )

    result_key = (
        "railradar:route-result:"
        + hashlib.sha256(
            result_key_raw.encode("utf-8")
        ).hexdigest()
    )

    cached_result = cache.get(result_key)

    if cached_result is not None:
        return cached_result

    try:
        source_station = find_station(source)
        destination_station = find_station(destination)

        if not source_station or not destination_station:
            return [], (
                "Could not identify both railway stations. "
                "Try specific station names."
            )

        source_code = _station_code(source_station)
        destination_code = _station_code(destination_station)

        if not source_code or not destination_code:
            return [], "Railway station codes could not be resolved."

        if source_code.casefold() == destination_code.casefold():
            return [], (
                "Both locations resolved to the same station. "
                "Please enter more specific station names."
            )

        params = {}

        if travel_date:
            params["date"] = travel_date

        result = railradar_get(
            f"/trains/between/{source_code}/{destination_code}",
            params=params,
        )

        trains = (
            result.get("trains", [])
            if isinstance(result, dict)
            else []
        )

        if not trains:
            return [], (
                f"No trains found between "
                f"{source_station.get('name', source_code)} "
                f"and {destination_station.get('name', destination_code)}."
            )

        options = []

        # Do not fetch geometry for every train.
        for item in trains[:3]:
            if not isinstance(item, dict):
                continue

            train = item.get("train") or {}
            from_info = item.get("from") or {}
            to_info = item.get("to") or {}

            number = str(
                train.get("number")
                or train.get("trainNumber")
                or ""
            ).strip()

            if not number:
                continue

            # Geometry is optional. Keep train results even if
            # geometry is rate-limited or unavailable.
            geometry = {}

            try:
                geometry = railradar_get(
                    f"/trains/{number}/route",
                    params={
                        "format": "polyline",
                        "stops": "true",
                    },
                )

            except (
                requests.RequestException,
                ValueError,
                TypeError,
            ):
                pass

            polyline = clip_train_geometry(
                geometry,
                source_station,
                destination_station,
            )

            try:
                distance = float(item.get("distance"))
                duration_minutes = int(item.get("duration"))

                if (
                    not math.isfinite(distance)
                    or distance <= 0
                    or duration_minutes <= 0
                ):
                    continue

            except (TypeError, ValueError):
                continue

            departure = from_info.get("departure") or ""
            arrival = to_info.get("arrival") or ""
            train_name = train.get("name") or "Train"
            
            estimated_fare = None

            if travel_date:
                try:
                    fare_result = railradar_get(
                        f"/trains/{number}/fare",
                        params={
                            "source": source_code,
                            "destination": destination_code,
                            "journeyDate": travel_date,
                            "classCode": "SL",
                            "quotaCode": "GN",
                        },
                    )

                    fare_data = fare_result.get("data", fare_result)
                    breakdown = fare_data.get("breakdown", {})
                    estimated_fare = breakdown.get("totalFare")

                    print(f"Train {number} fare response: {fare_result}")
                    print(f"Train {number} extracted fare: {estimated_fare}")

                except (
                    requests.RequestException,
                    ValueError,
                    TypeError,
                    AttributeError,
                ):
                    pass

            options.append({
                "mode": "train",
                "label": f"{number} · {train_name}",
                "train_number": number,
                "train_name": train_name,
                "source_station": source_station.get(
                    "name",
                    source_code,
                ),
                "destination_station": destination_station.get(
                    "name",
                    destination_code,
                ),
                "departure": departure,
                "arrival": arrival,
                "schedule": (
                    f"Departure: {departure or 'N/A'} · "
                    f"Arrival: {arrival or 'N/A'}"
                ),
                "distance_km": round(distance, 2),
                "duration": _format_duration(duration_minutes),
                "polyline": polyline,
                "segment_polyline": polyline,
                "estimated_fare": estimated_fare,
            })

        if options:
            result_to_cache = (options, "")
            cache.set(
                result_key,
                result_to_cache,
                TRAIN_CACHE_TTL,
            )
            return result_to_cache

        return [], (
            "RailRadar returned no usable train options. "
            "Try checking the station names."
        )

    except requests.HTTPError as exc:
        status = (
            exc.response.status_code
            if exc.response is not None
            else None
        )

        if status == 401:
            return [], (
                "RailRadar rejected the API key. "
                "Check TRAIN_API_KEY in your .env file."
            )

        if status == 429:
            return [], (
                "RailRadar rate limit reached. "
                "Train results are temporarily unavailable."
            )

        return [], (
            f"RailRadar request failed (HTTP {status or 'error'})."
        )

    except (
        requests.RequestException,
        ValueError,
        TypeError,
    ):
        return [], (
            "Unable to fetch trains. Check your internet connection "
            "and RailRadar API configuration."
        )


# =========================================================
# GOOGLE ROUTES API
# =========================================================

def get_road_routes(source, destination):
    api_key = getattr(settings, "GOOGLE_MAPS_API_KEY", "")

    if not api_key:
        return [], "Google Routes API key is not configured."

    endpoint = (
        "https://routes.googleapis.com/"
        "directions/v2:computeRoutes"
    )

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "routes.distanceMeters,"
            "routes.duration,"
            "routes.polyline.encodedPolyline"
        ),
    }

    options = []

    for mode, label, google_mode in (
        ("car", "Car", "DRIVE"),
        ("two_wheeler", "Two-wheeler", "TWO_WHEELER"),
    ):
        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json={
                    "origin": {"address": source},
                    "destination": {"address": destination},
                    "travelMode": google_mode,
                },
                timeout=20,
            )

            if not response.ok:
                print(
                    f"{label} route failed:",
                    response.status_code,
                    response.text[:500],)
                continue

            payload = response.json()
            routes = payload.get("routes", [])

            if not routes:
                continue

            route = routes[0]

            encoded = (
                route.get("polyline", {})
                .get("encodedPolyline", "")
            )

            duration_text = route.get("duration", "")

            if not encoded or not duration_text.endswith("s"):
                continue

            distance_km = round(
                float(route["distanceMeters"]) / 1000,
                2,
            )

            duration_seconds = float(
                duration_text[:-1]
            )

            duration_minutes = max(
                1,
                math.ceil(duration_seconds / 60),
            )

            options.append({
                "mode": mode,
                "label": label,
                "distance_km": distance_km,
                "duration": _format_duration(duration_minutes),
                "polyline": encoded,
                "estimated_fare": round(distance_km * 12),
            })

        except (
            requests.RequestException,
            ValueError,
            TypeError,
            KeyError,
        ):
            continue

    if not options:
        return [], (
            "Google Routes API could not find a road route. "
            "Check your API key, billing and enabled APIs."
        )

    return options, ""


# =========================================================
# SEARCH ROUTES VIEW
# =========================================================

def travel_search(request):
    form_data = {
        "source": "",
        "destination": "",
        "date": "",
        "time": "",
        "passengers": "1",
    }

    context = {
        "form_data": form_data,
        "route_data": None,
        "route_options": [],
        "error": "",
        "notice": "",
    }

    if request.method != "POST":
        return render(
            request,
            "travel_search.html",
            context,
        )

    for field in form_data:
        form_data[field] = request.POST.get(
            field,
            form_data[field],
        ).strip()

    context["form_data"] = form_data

    source = form_data["source"]
    destination = form_data["destination"]

    if not source or not destination:
        context["error"] = (
            "Please enter both starting location and destination."
        )
        return render(request, "travel_search.html", context)

    if source.casefold() == destination.casefold():
        context["error"] = (
            "Starting location and destination must be different."
        )
        return render(request, "travel_search.html", context)

    try:
        passengers = int(form_data["passengers"])

        if not 1 <= passengers <= 50:
            raise ValueError

    except (ValueError, TypeError):
        context["error"] = (
            "Passenger count must be between 1 and 50."
        )
        return render(request, "travel_search.html", context)

    # Get road routes
    road_options, road_error = get_road_routes(
        source,
        destination,
    )

    # Get train routes
    train_options, train_error = get_train_routes(
        source,
        destination,
        form_data["date"],
    )

    # Get flight routes (optional)
    flight_options = get_flight_routes(
        source,
        destination,
        form_data["date"],
    )

    # Combine all available route options
    route_options = (
        road_options
        + train_options
        + flight_options
    )

    print("TOTAL ROUTES:", len(route_options))
    print("FLIGHT ROUTES IN VIEW:", [
        r for r in route_options if r.get("mode") == "flight"
    ])

    if not route_options:
        context["error"] = (
            road_error
            or train_error
            or "No routes were returned for these locations."
        )
        context["notice"] = train_error or ""

        return render(
            request,
            "travel_search.html",
            context,
        )

    # Select a default route
    selected = next(
        (
            route
            for route in route_options
            if route["mode"] == "car"
        ),
        route_options[0],
    )

    context["route_options"] = route_options

    context["route_data"] = {
        "source": source,
        "destination": destination,
        "distance_km": selected.get("distance_km"),
        "duration": selected.get("duration", ""),
        "date": form_data["date"],
        "time": form_data["time"],
        "passengers": passengers,
        "transport": selected["mode"],
        "polyline": selected.get("polyline", ""),
        "estimated_total_fare_raw": (
            selected["estimated_fare"]
            if selected.get("estimated_fare") is not None
            else 0
        ),
        "estimated_total_fare": (
            f'{selected["estimated_fare"]:,}'
            if selected.get("estimated_fare") is not None
            else "Unavailable"
        ),
        "train_number": selected.get("train_number", ""),
        "train_name": selected.get("train_name", ""),
        "departure": selected.get("departure", ""),
        "arrival": selected.get("arrival", ""),
        "schedule": selected.get("schedule", ""),
    }

    if not train_options and train_error:
        context["notice"] = (
            "Road or flight routes loaded. Train results unavailable: "
            + train_error
        )

    elif not road_options and (train_options or flight_options):
        context["notice"] = (
            "Road routes could not be retrieved. "
            "Other available routes are shown."
        )

    return render(
        request,
        "travel_search.html",
        context,
    )

# =========================================================
# SAVE TRIP
# =========================================================

@login_required
def save_trip(request):
    if request.method != "POST":
        return redirect("travel:travel_search")

    source = request.POST.get("source", "").strip()
    destination = request.POST.get("destination", "").strip()
    transport = request.POST.get("transport", "car").strip()
    duration = request.POST.get("duration", "").strip()

    try:
        passengers = int(
            request.POST.get("passengers", "1")
        )

        distance = Decimal(
            request.POST.get("distance_km", "")
        )

        fare = int(
            request.POST.get("estimated_total_fare", "0") or "0"
        )

        travel_date = (
            date.fromisoformat(request.POST["date"])
            if request.POST.get("date")
            else None
        )

        travel_time = (
            time.fromisoformat(request.POST["time"])
            if request.POST.get("time")
            else None
        )

    except (
        ValueError,
        TypeError,
        InvalidOperation,
    ):
        messages.error(
            request,
            "Invalid trip details. Please try again.",
        )
        return redirect("travel:travel_search")

    if (
        not source
        or not destination
        or source.casefold() == destination.casefold()
        or transport not in ("car", "two_wheeler", "train", "flight")
        or not 1 <= passengers <= 50
        or not distance.is_finite()
        or not Decimal("0") < distance <= Decimal("100000")
        or fare < 0
        or not duration
    ):
        messages.error(
            request,
            "Please check your trip details.",
        )
        return redirect("travel:travel_search")

    SavedTrip.objects.create(
        user=request.user,
        source=source,
        destination=destination,
        travel_date=travel_date,
        travel_time=travel_time,
        passengers=passengers,
        transport=transport,
        distance_km=distance,
        duration=duration,
        estimated_total_fare=fare,
    )

    messages.success(
        request,
        "Trip saved successfully!",
    )
    return redirect("travel:saved_trips")


# =========================================================
# SAVED TRIPS
# =========================================================

@login_required
def saved_trips(request):
    trips = SavedTrip.objects.filter(
        user=request.user
    )

    return render(
        request,
        "saved_trips.html",
        {"trips": trips},
    )


# =========================================================
# DELETE SAVED TRIP
# =========================================================

@login_required
def delete_saved_trip(request, trip_id):
    if request.method == "POST":
        trip = get_object_or_404(
            SavedTrip,
            id=trip_id,
            user=request.user,
        )

        trip.delete()

        messages.success(
            request,
            "Saved trip removed.",
        )

    return redirect("travel:saved_trips")


# =========================================================
# BOOKING OPTIONS
# =========================================================

def book_ticket(request):
    source = request.GET.get("source", "").strip()
    destination = request.GET.get("destination", "").strip()

    try:
        distance = float(request.GET.get("distance_km", ""))
        passengers = int(request.GET.get("passengers", "1"))

    except (ValueError, TypeError):
        messages.error(request, "Please search for a route first.")
        return redirect("travel:travel_search")

    if (
        not source
        or not destination
        or source.casefold() == destination.casefold()
        or not math.isfinite(distance)
        or not 0 < distance <= 100000
        or not 1 <= passengers <= 50
    ):
        messages.error(request, "Please search for a valid route first.")
        return redirect("travel:travel_search")

    # External booking websites for each transport mode.
    transport_options = {
        "two_wheeler": {
            "name": "Bike / Two-wheeler",
            "description": "A possible option for shorter journeys.",
            "providers": [
                {
                    "name": "Rapido",
                    "description": "Check bike taxi availability.",
                    "url": "https://www.rapido.bike/",
                },
                {
                    "name": "Uber",
                    "description": "Explore available ride types.",
                    "url": "https://www.uber.com/in/en/ride/",
                },
            ],
        },
        "car": {
            "name": "Car / Cab",
            "description": "Check cab services and available rides.",
            "providers": [
                {
                    "name": "Uber",
                    "description": "Explore cab rides.",
                    "url": "https://www.uber.com/in/en/ride/",
                },
                {
                    "name": "Ola",
                    "description": "Explore cab options.",
                    "url": "https://www.olacabs.com/",
                },
            ],
        },
        "bus": {
            "name": "Bus",
            "description": "Explore bus services for your journey.",
            "providers": [
                {
                    "name": "redBus",
                    "description": "Explore bus routes and booking.",
                    "url": "https://www.redbus.in/",
                },
                {
                    "name": "AbhiBus",
                    "description": "Check available bus services.",
                    "url": "https://www.abhibus.com/",
                },
            ],
        },
        "train": {
            "name": "Train",
            "description": "Check train routes and availability.",
            "providers": [
                {
                    "name": "IRCTC",
                    "description": "Official railway ticket booking.",
                    "url": "https://www.irctc.co.in/",
                },
                {
                    "name": "ixigo",
                    "description": "Explore train options.",
                    "url": "https://www.ixigo.com/trains",
                },
            ],
        },
        "flight": {
            "name": "Flight",
            "description": "Explore flights for your destination.",
            "providers": [
                {
                    "name": "MakeMyTrip",
                    "description": "Explore flight options.",
                    "url": "https://www.makemytrip.com/",
                },
                {
                    "name": "EaseMyTrip",
                    "description": "Search available flights.",
                    "url": "https://www.easemytrip.com/",
                },
            ],
        },
    }

    # Choose a suggested mode based on route distance.
    # This is a heuristic, not a live fare or schedule comparison.
    if distance <= 10:
        recommended_key = "two_wheeler"
        recommendation = (
            "For this short journey, a two-wheeler may be worth "
            "considering. Check local availability and fares before deciding."
        )

    elif distance <= 100:
        recommended_key = "car"
        recommendation = (
            "For this journey, consider a car or cab for a direct trip. "
            "Compare its fare and travel time with bus and train options."
        )

    else:
        recommended_key = "train"
        recommendation = (
            "For this longer journey, train travel may be worth considering. "
            "Compare available schedules and fares; a bus or flight may "
            "also suit your needs."
        )

    recommended_transport = transport_options[recommended_key]

    # Show every remaining mode after the recommendation.
    alternatives = [
    option
    for key, option in transport_options.items()
    if key != recommended_key and key != "bus"
]

    context = {
        "source": source,
        "destination": destination,
        "distance": distance,
        "duration": request.GET.get("duration", "").strip(),
        "passengers": passengers,
        "travel_date": request.GET.get("date", "").strip(),
        "travel_time": request.GET.get("time", "").strip(),

        "recommended_transport": recommended_transport,
        "recommendation": recommendation,
        "alternatives": alternatives,
    }

    return render(
        request,
        "booking_options.html",
        context,
    )


# =========================================================
# OAG FLIGHT API
# =========================================================

AIRPORT_CODES = {
    "delhi": "DEL",
    "new delhi": "DEL",
    "mumbai": "BOM",
    "bombay": "BOM",
    "bhopal": "BHO",
    "indore": "IDR",
    "jabalpur": "JLR",
    "raipur": "RPR",
    "ujjain": "IDR",
    "pune": "PNQ",
    "bengaluru": "BLR",
    "bangalore": "BLR",
    "hyderabad": "HYD",
    "chennai": "MAA",
    "kolkata": "CCU",
    "jaipur": "JAI",
    "lucknow": "LKO",
    "ahmedabad": "AMD",
    "goa": "GOI",
    "nagpur": "NAG",
    "patna": "PAT",
    "varanasi": "VNS",
    "chandigarh": "IXC",
    "kochi": "COK",
    "cochin": "COK",
    "srinagar": "SXR",
    "amritsar": "ATQ",
}


def _get_airport_code(location):
    location = str(location or "").strip()

    # Allow users to enter an airport IATA code directly.
    if len(location) == 3 and location.isalpha():
        return location.upper()

    return AIRPORT_CODES.get(location.casefold())


def get_flight_routes(source, destination, travel_date):
    """
    Fetch scheduled flights from OAG.
    Source and destination must be airport cities or IATA codes.
    """

    api_key = getattr(settings, "OAG_API_KEY", "")

    if not api_key or not travel_date:
        return []

    source_code = _get_airport_code(source)
    destination_code = _get_airport_code(destination)

    # OAG needs airport codes, not street addresses.
    if not source_code or not destination_code:
        return []

    if source_code == destination_code:
        return []

    url = "https://api.oag.com/flight-instances"

    params = {
        "version": "v2",
        "DepartureAirport": source_code,
        "ArrivalAirport": destination_code,
        "DepartureDateTime": travel_date,
        "CodeType": "IATA",
        "Limit": 10,
    }

    headers = {
        "Subscription-Key": api_key,
        "Accept": "application/json",
    }

    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()
        print("OAG STATUS:", response.status_code)
        print("OAG RESPONSE:", response.text[:2000])

        payload = response.json()
        print("OAG DATA TYPE:", type(payload.get("data")))
        print("OAG DATA:", str(payload.get("data"))[:1500])

        flights = payload.get("data", [])

        payload = response.json()
        flights = payload.get("data", [])

        if not isinstance(flights, list):
            return []

        flight_options = []

        for flight in flights:
            if not isinstance(flight, dict):
                continue

            departure = flight.get("departure") or {}
            arrival = flight.get("arrival") or {}
            carrier = flight.get("carrier") or {}

            departure_airport = (
                departure.get("airport") or {}
            )
            arrival_airport = (
                arrival.get("airport") or {}
            )
            departure_time = (
                departure.get("time") or {}
            )
            arrival_time = (
                arrival.get("time") or {}
            )
            segment_info = (
                flight.get("segmentInfo") or {}
            )
            distance_info = (
                flight.get("distance") or {}
            )

            duration_minutes = flight.get("elapsedTime")

            try:
                duration_minutes = int(duration_minutes)
                if duration_minutes <= 0:
                    continue
            except (TypeError, ValueError):
                continue

            airline = carrier.get("iata") or "Unknown"
            flight_number = flight.get("flightNumber")

            flight_options.append({
                "mode": "flight",
                "label": f"{airline} {flight_number or ''}".strip(),
                "airline": airline,
                "flight_number": flight_number,
                "source": departure_airport.get("iata", source_code),
                "destination": arrival_airport.get("iata", destination_code),
                "departure": departure_time.get("local", ""),
                "arrival": arrival_time.get("local", ""),
                "departure_time": departure_time.get("local", ""),
                "arrival_time": arrival_time.get("local", ""),
                "schedule": (
                    f"Departure: {departure_time.get('local', 'N/A')} · "
                    f"Arrival: {arrival_time.get('local', 'N/A')}"
                ),
                "distance_km": distance_info.get(
                    "accumulatedGreatCircleKilometers"
                ),
                "duration": _format_duration(duration_minutes),
                "duration_minutes": duration_minutes,
                "stops": segment_info.get("numberOfStops"),
                "polyline": "",
                "estimated_fare": None,
            })

            print("FLIGHT OPTIONS COUNT:", len(flight_options))
            print("FLIGHT OPTIONS:", flight_options)
            
        return flight_options

    except (
        requests.RequestException,
        ValueError,
        TypeError,
    ) as exc:
        print("OAG flight request failed:", str(exc))
        return []

def compare_routes(request):
    return render(request, "compare.html")


from urllib.parse import quote_plus
from django.shortcuts import render


def hotel_booking(request):
    destination = request.GET.get("destination", "").strip()
    passengers = request.GET.get("passengers", "1").strip()

    try:
        passengers = int(passengers)
        if not 1 <= passengers <= 50:
            passengers = 1
    except (ValueError, TypeError):
        passengers = 1

    search_destination = quote_plus(destination)

    hotels = []

    if destination:
        hotels = [
            {
                "name": f"Hotels in {destination}",
                "description": (
                    f"Explore hotels, guest ratings, prices "
                    f"and amenities in {destination}."
                ),
                "booking_url": (
                    "https://www.booking.com/searchresults.html"
                    f"?ss={search_destination}"
                    f"&group_adults={passengers}&no_rooms=1"
                ),
                "google_url": (
                    "https://www.google.com/travel/hotels"
                    f"?q={search_destination}"
                ),
            },
            {
                "name": f"Accommodation in {destination}",
                "description": (
                    "Compare accommodation options and "
                    "check availability on a travel website."
                ),
                "booking_url": (
                    "https://www.makemytrip.com/hotels/"
                ),
                "google_url": (
                    "https://www.agoda.com/"
                ),
            },
        ]

    return render(
        request,
        "hotel_booking.html",
        {
            "destination": destination,
            "passengers": passengers,
            "hotels": hotels,
        },
    )



from urllib.parse import quote_plus
from django.shortcuts import render


def hotel_booking(request):
    destination = request.GET.get("destination", "").strip()
    passengers = request.GET.get("passengers", "1")

    try:
        passengers = max(1, min(int(passengers), 50))
    except (ValueError, TypeError):
        passengers = 1

    query = quote_plus(destination)

    hotels = []

    if destination:
        hotels = [
            {
                "name": "Booking.com",
                "description": "Explore hotels, photos, prices and guest reviews.",
                "url": f"https://www.booking.com/searchresults.html?ss={query}",
            },
            {
                "name": "MakeMyTrip",
                "description": "Compare hotel options for your destination.",
                "url": f"https://www.makemytrip.com/hotels/",
            },
            {
                "name": "Google Hotels",
                "description": "Discover hotels and compare available options.",
                "url": f"https://www.google.com/travel/hotels?q={query}",
            },
        ]

    return render(request, "hotel_booking.html", {
        "destination": destination,
        "passengers": passengers,
        "hotels": hotels,
    })