import json
import logging
import os

import requests


logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENTRIPMAP_URL = "https://api.opentripmap.com/0.1/en/places"

ALLOWED_INTENTS = ["hotel", "places", "booking", "route", "greeting", "thanks", "general"]
ALLOWED_TRANSPORTS = ["car", "two_wheeler", "other"]


class TravelAPIError(Exception):
    """Base error for every outside API used by the travel agent."""


class LanguageModelError(TravelAPIError):
    pass


class PlacesAPIError(TravelAPIError):
    pass


def _get_key(name):
    key = os.environ.get(name, "").strip()
    if not key:
        raise TravelAPIError(f"{name} is not set. Add it to your environment first.")
    return key


# ---------------------------------------------------------------------------
# 1. Language understanding (Groq)
# ---------------------------------------------------------------------------

def _build_instructions(previous_city):
    return (
        "You are the language understanding part of a travel assistant.\n"
        "Read the user's message and reply with ONLY a JSON object that has these keys:\n"
        '  "intents": a list, any of: "hotel", "places", "booking", "route", '
        '"greeting", "thanks", "general"\n'
        '  "source": the city the user starts from, or null\n'
        '  "destination": the city the user wants to go to, or null\n'
        '  "city": the main city the user is asking about, or null\n'
        '  "transport": "car", "two_wheeler" (bike/motorcycle/scooter) or "other" '
        "(bus/train/flight)\n\n"
        "Rules:\n"
        "- The user can write in any language (Hindi, Hinglish, English...). "
        "Always write city names in English.\n"
        '- "hotel" = stay/room/hotel, "places" = attractions/things to see, '
        '"booking" = book/reserve/tickets, "route" = distance/directions/how to reach.\n'
        "- Only use a city the user really mentioned. Do not guess.\n"
        "- If the message is a follow-up with no city (like 'what about hotels?'), "
        "leave the city fields null.\n"
        "- For route questions, choose 'other' only when the user explicitly asks "
        "for bus, train, or flight travel; if no mode is specified, choose 'car'.\n"
        '- If nothing fits, use ["general"].\n\n'
        f"Previous city in the conversation: {previous_city or 'none'}"
    )


def _clean_city_name(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 60:
        return None
    return value


def understand_message(message, previous_city=None):
    """Ask the Groq language model what the user wants. Returns a clean dictionary."""
    api_key = _get_key("GROQ_API_KEY")
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _build_instructions(previous_city)},
            {"role": "user", "content": message},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    try:
        response = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException:
        raise LanguageModelError("I could not reach the language service. Please try again.")

    if response.status_code == 401:
        raise LanguageModelError("The GROQ_API_KEY is not valid. Please check the key.")
    if response.status_code in (429, 503):
        raise LanguageModelError("The language service is busy right now. Please try again in a minute.")
    if response.status_code != 200:
        logger.warning("Groq request failed with HTTP status %s", response.status_code)
        if response.status_code == 400:
            raise LanguageModelError(
                "The language service rejected the request. Check GROQ_MODEL and try again."
            )
        if response.status_code == 404:
            raise LanguageModelError(
                "The language service model was not found. Check GROQ_MODEL and try again."
            )
        raise LanguageModelError(
            f"The language service returned an error (HTTP {response.status_code}). "
            "Please try again later."
        )

    try:
        text = response.json()["choices"][0]["message"]["content"]
        data = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError):
        raise LanguageModelError("I could not understand the language service reply. Please try again.")

    if not isinstance(data, dict):
        raise LanguageModelError("I could not understand the language service reply. Please try again.")

    intents = [i for i in data.get("intents", []) if i in ALLOWED_INTENTS]
    transport = data.get("transport")

    return {
        "intents": intents or ["general"],
        "source": _clean_city_name(data.get("source")),
        "destination": _clean_city_name(data.get("destination")),
        "city": _clean_city_name(data.get("city")),
        "transport": transport if transport in ALLOWED_TRANSPORTS else "car",
    }


# ---------------------------------------------------------------------------
# 2. Cities, attractions and hotels (OpenTripMap, free key)
# ---------------------------------------------------------------------------

def _otm_get(path, params):
    params = dict(params)
    params["apikey"] = _get_key("OPENTRIPMAP_API_KEY")

    try:
        response = requests.get(
            f"{OPENTRIPMAP_URL}/{path}",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException:
        raise PlacesAPIError("I could not reach the places service. Please try again.")

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise PlacesAPIError("The places service returned an error. Please try again.")

    try:
        return response.json()
    except ValueError:
        raise PlacesAPIError("The places service returned unexpected data.")


def geocode_city(name):
    """Turn a city name into latitude/longitude. Returns None if not found."""
    data = _otm_get("geoname", {"name": name})

    if not data or data.get("status") != "OK":
        return None

    return {
        "name": data.get("name", name),
        "country": data.get("country", ""),
        "lat": data["lat"],
        "lon": data["lon"],
    }


def _place_details(xid):
    try:
        return _otm_get(f"xid/{xid}", {}) or {}
    except PlacesAPIError:
        return {}


def _search_nearby(lat, lon, kinds, limit=5):
    """Return a list of simple place dictionaries near a point."""
    params = {
        "radius": 10000,
        "lat": lat,
        "lon": lon,
        "kinds": kinds,
        "format": "json",
        "limit": 20,
    }
    if kinds == "interesting_places":
        params["rate"] = "2"

    results = _otm_get("radius", params) or []
    places = []

    for item in results:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        details = _place_details(item["xid"])
        extract = details.get("wikipedia_extracts", {}).get("text", "")
        places.append({
            "name": name,
            "kinds": item.get("kinds", ""),
            "description": extract[:200],
            "url": details.get("url") or details.get("otm") or "",
        })
        if len(places) == limit:
            break

    return places


def search_attractions(lat, lon, city_name):
    attractions = []
    for place in _search_nearby(lat, lon, "interesting_places"):
        category = place["kinds"].split(",")[0].replace("_", " ").title()
        attractions.append({
            "name": place["name"],
            "city": city_name,
            "category": category,
            "description": place["description"] or f"A popular {category.lower()} spot in {city_name}.",
            "website_url": place["url"],
        })
    return attractions


def search_hotels(lat, lon, city_name):
    hotels = []
    # "accomodations" is spelled this way in the OpenTripMap category list.
    for place in _search_nearby(lat, lon, "accomodations"):
        hotels.append({
            "name": place["name"],
            "city": city_name,
            "description": place["description"] or f"A place to stay in {city_name}.",
            "booking_url": place["url"],
        })
    return hotels
