from urllib.parse import urlencode

from comparison.distance import DistanceError, get_route_distance
from comparison.services import ComparisonError, recommend
from travel.routes import RouteAPIError, calculate_google_route

from .api_clients import (
    PlacesAPIError,
    TravelAPIError,
    geocode_city,
    search_attractions,
    search_hotels,
    understand_message,
)


def _normalise_text(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.strip()


def find_city(name):
    """Look a city up through the places API."""
    name = _normalise_text(name)
    if not name:
        return {"found": False, "city": None, "suggestions": []}

    try:
        city = geocode_city(name)
    except TravelAPIError:
        city = None

    if city:
        return {"found": True, "city": city, "suggestions": []}

    return {"found": False, "city": None, "suggestions": []}


def get_attractions(city_name):
    result = find_city(city_name)
    if not result["found"]:
        return []
    city = result["city"]
    return search_attractions(city["lat"], city["lon"], city["name"])


def get_hotels(city_name):
    result = find_city(city_name)
    if not result["found"]:
        return []
    city = result["city"]
    return search_hotels(city["lat"], city["lon"], city["name"])


def _make_result(message, intents, success=True, cities=None, source=None,
                 destination=None, context_city=None, attractions=None,
                 hotels=None, route=None):
    return {
        "success": success,
        "intent": intents[0],
        "intents": intents,
        "cities": cities or [],
        "source": source,
        "destination": destination,
        "context_city": context_city,
        "suggestions": [],
        "attractions": attractions or [],
        "hotels": hotels or [],
        "route": route,
        "message": message,
    }


def _format_duration(duration_text):
    total_minutes = round(int(str(duration_text).rstrip("s")) / 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours} hr {minutes} min"
    return f"{minutes} min"


def _requested_transport(message, inferred_transport):
    if inferred_transport != "other":
        return inferred_transport

    message = message.lower()
    transit_words = (
        "bus", "train", "rail", "flight", "plane", "airplane", "transit",
        "बस", "ट्रेन", "रेल", "हवाई",
    )
    for word in message.split():
        if word.strip(".,!?;:") in transit_words:
            return "other"
    return "car"


def _route_comparison(source, destination, distance_km, distance_source):
    comparison = recommend(distance_km).as_dict()
    comparison["distance_source"] = distance_source
    comparison["compare_url"] = (
        f"/compare/?{urlencode({'origin': source, 'destination': destination, 'distance': distance_km})}"
    )
    return comparison


def _plan_comparison_route(source, destination):
    distance = get_route_distance(source, destination)
    comparison = _route_comparison(
        source,
        destination,
        distance.km,
        distance.source_label,
    )
    route = {
        "distance_km": distance.km,
        "duration": None,
        "transport": "other",
        "comparison": comparison,
    }
    best = comparison["recommended"]
    message = (
        f"The estimated road distance from {source} to {destination} "
        f"is {distance.km:g} km. The comparison estimate recommends "
        f"{best['label']} at about ₹{best['cost']:,} and "
        f"{best['time_display']}. These are planning estimates, "
        "not live fares or schedules."
    )
    return route, message


def _plan_google_route(source, destination, transport):
    transport_label = "two-wheeler" if transport == "two_wheeler" else "driving"
    google_route = calculate_google_route(source, destination, transport)
    distance_km = round(float(google_route["distanceMeters"]) / 1000, 2)
    duration = _format_duration(google_route["duration"])
    comparison = _route_comparison(
        source,
        destination,
        distance_km,
        f"Google Routes {transport_label} distance",
    )
    route = {
        "distance_km": distance_km,
        "duration": duration,
        "transport": transport,
        "comparison": comparison,
    }
    best = comparison["recommended"]
    message = (
        f"The Google Routes estimate from {source} to {destination} "
        f"by {transport_label} is about {distance_km} km and {duration}. "
        f"The comparison estimate recommends {best['label']} at about "
        f"₹{best['cost']:,}. Other modes show estimated costs and times, "
        "not live fares or schedules."
    )
    return route, message


def process_travel_request(message, previous_city=None):
    message = _normalise_text(message)
    previous_city = _normalise_text(previous_city) or None

    if not message:
        return _make_result(
            "Please describe your travel request.",
            ["general"],
            success=False,
            context_city=previous_city,
        )

    # Step 1: let Groq understand the message (any language).
    try:
        understood = understand_message(message, previous_city)
    except TravelAPIError as exc:
        return _make_result(
            str(exc), ["general"], success=False, context_city=previous_city
        )

    intents = understood["intents"]
    source = understood["source"]
    destination = understood["destination"]
    transport = _requested_transport(message, understood["transport"])

    # Collect every city name the user mentioned, without repeats.
    city_names = []
    seen_cities = set()
    for name in (source, destination, understood["city"]):
        if name and name.casefold() not in seen_cities:
            city_names.append(name)
            seen_cities.add(name.casefold())

    wants_place_info = any(i in intents for i in ("hotel", "places", "booking"))

    # Step 2: follow-up messages with no city use the previous city.
    if not city_names and previous_city:
        if "route" in intents:
            return _make_result(
                f"Are you travelling from {previous_city}? "
                "Tell me the destination city and I can help you plan.",
                intents,
                source=previous_city,
                context_city=previous_city,
            )
        if wants_place_info:
            city_names = [previous_city]

    if not city_names:
        if "greeting" in intents:
            reply = (
                "Hello! I can help you explore tourist places and hotels, "
                "or plan a journey between cities. Where are you going?"
            )
            success = True
        elif "thanks" in intents:
            reply = "You're welcome! Let me know where you'd like to travel next."
            success = True
        elif intents == ["general"]:
            reply = (
                "I'm your travel assistant. I can suggest hotels and "
                "tourist attractions, or find a route between two cities. "
                "Try asking, \"What places can I visit in Bhopal?\""
            )
            success = True
        else:
            reply = "Which city do you mean? Please tell me the city name."
            success = False
        return _make_result(
            reply, intents, success=success, context_city=previous_city
        )

    # Step 3: decide the source and destination.
    if not (source and destination):
        if "route" in intents and len(city_names) == 1 and previous_city:
            if city_names[0].casefold() != previous_city.casefold():
                source = previous_city
                destination = city_names[0]
            else:
                source = city_names[0]
                destination = None
        else:
            source = city_names[0]
            destination = city_names[1] if len(city_names) > 1 else None

    destination_city = destination or city_names[-1]
    cities = [{"name": name} for name in city_names]

    attractions = []
    hotels = []
    route_data = None
    messages = []

    if "route" in intents:
        if destination:
            if transport == "other":
                try:
                    route_data, route_message = _plan_comparison_route(
                        source, destination
                    )
                    messages.append(route_message)
                except (DistanceError, ComparisonError) as exc:
                    messages.append(str(exc))
            else:
                try:
                    route_data, route_message = _plan_google_route(
                        source, destination, transport
                    )
                    messages.append(route_message)
                except RouteAPIError as exc:
                    if exc.status_code == 429:
                        try:
                            route_data, route_message = _plan_comparison_route(
                                source, destination
                            )
                        except (DistanceError, ComparisonError) as fallback_exc:
                            messages.append(
                                f"{exc} The alternate distance lookup also failed: "
                                f"{fallback_exc}"
                            )
                        else:
                            messages.append(
                                "Google Routes is unavailable (HTTP 429), so I used "
                                f"an alternate distance source. {route_message}"
                            )
                    else:
                        messages.append(str(exc))
                except (ComparisonError, KeyError, TypeError, ValueError):
                    messages.append(
                        "Google returned unexpected route data. "
                        "Please try the route search again."
                    )
        else:
            messages.append(
                f"I have {source} as your starting city. "
                "What city would you like to travel to?"
            )

    # Step 4: fetch hotels / attractions from the places API.
    city_lookup = None
    if "hotel" in intents or "places" in intents:
        city_lookup = find_city(destination_city)
        if not city_lookup["found"]:
            messages.append(
                f"I couldn't find {destination_city} on the map. "
                "Please check the spelling of the city."
            )

    if "hotel" in intents and city_lookup and city_lookup["found"]:
        try:
            hotels = get_hotels(destination_city)
        except PlacesAPIError as exc:
            messages.append(str(exc))
        else:
            if hotels:
                names = ", ".join(hotel["name"] for hotel in hotels)
                messages.append(f"Here are some hotels in {destination_city}: {names}")
            else:
                messages.append(f"I couldn't find any hotels listed for {destination_city}.")

    if "places" in intents and city_lookup and city_lookup["found"]:
        try:
            attractions = get_attractions(destination_city)
        except PlacesAPIError as exc:
            messages.append(str(exc))
        else:
            if attractions:
                names = ", ".join(item["name"] for item in attractions)
                messages.append(
                    f"Here are some tourist attractions in {destination_city}: {names}"
                )
            else:
                messages.append(
                    f"I couldn't find any tourist attractions listed for {destination_city}."
                )

    if "booking" in intents:
        messages.append(
            "Please select a hotel or attraction to visit its available "
            "website and explore booking options."
        )

    if intents == ["general"]:
        names = ", ".join(city["name"] for city in cities)
        messages.append(
            f"You're asking about {names}. Would you like route information, "
            "hotels, tourist places, or booking assistance?"
        )

    if "greeting" in intents and not messages:
        messages.append("Hello! Where would you like to go?")

    # A city that could not be found is the only failure at this point.
    success = not (city_lookup and not city_lookup["found"])

    return _make_result(
        " ".join(messages),
        intents,
        success=success,
        cities=cities,
        source=source,
        destination=destination,
        context_city=destination_city,
        attractions=attractions,
        hotels=hotels,
        route=route_data,
    )
