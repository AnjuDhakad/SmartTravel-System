import re

import requests

from django.conf import settings


class RouteAPIError(ValueError):
    """Raised when Google Routes cannot return a usable route."""


def _google_error_message(response, api_key):
    try:
        error = response.json().get("error", {})
    except (AttributeError, TypeError, ValueError):
        error = {}

    if not isinstance(error, dict):
        error = {}

    status = error.get("status", "")
    message = error.get("message", "")
    details = []
    if isinstance(status, str) and status:
        details.append(status)
    if isinstance(message, str) and message:
        safe_message = (
            message.replace(api_key, "[redacted]") if api_key else message
        )
        safe_message = re.sub(r"AIza[0-9A-Za-z_-]{30,}", "[redacted]", safe_message)
        details.append(safe_message[:300])

    reason = " ".join(details)
    status_code = getattr(response, "status_code", None)

    if status_code == 403:
        hint = (
            "Check that Routes API is enabled, billing is active, and "
            "the API key restrictions allow Routes API."
        )
    elif status_code == 401:
        hint = "Check that the API key is valid and accepted by this project."
    elif status_code == 429:
        hint = "The Google Routes API quota may be exhausted."
    elif status_code == 400:
        hint = "Check that both locations are valid and supported."
    else:
        hint = "Check the locations and Google Cloud API settings."

    status_text = f" (HTTP {status_code})" if status_code else ""
    reason_text = f" Google response: {reason}." if reason else ""
    return (
        f"Google Routes could not calculate this route{status_text}."
        f"{reason_text} {hint}"
    )


def calculate_google_route(origin, destination, transport="car"):
    if not settings.GOOGLE_MAPS_API_KEY:
        raise RouteAPIError("Google Routes API key is not configured.")

    travel_mode = {
        "car": "DRIVE",
        "two_wheeler": "TWO_WHEELER",
    }.get(transport)

    if travel_mode is None:
        raise RouteAPIError("Please select a valid transport option.")

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": (
            "routes.distanceMeters,"
            "routes.duration,"
            "routes.polyline.encodedPolyline"
        ),
    }
    payload = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": travel_mode,
    }

    try:
        response = requests.post(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            headers=headers,
            json=payload,
            timeout=25,
        )
    except requests.RequestException as exc:
        raise RouteAPIError(
            "Unable to connect to Google Routes. Please try again."
        ) from exc

    if not response.ok:
        raise RouteAPIError(
            _google_error_message(response, settings.GOOGLE_MAPS_API_KEY)
        )

    try:
        data = response.json()
        routes = data.get("routes", [])
    except (AttributeError, TypeError, ValueError) as exc:
        raise RouteAPIError(
            "Unexpected route data received. Please try again."
        ) from exc

    if not routes:
        raise RouteAPIError("No route was found for these locations.")

    if not isinstance(routes[0], dict):
        raise RouteAPIError(
            "Unexpected route data received. Please try again."
        )

    return routes[0]
