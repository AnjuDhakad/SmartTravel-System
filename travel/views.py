
import math
import requests

from datetime import date, time
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import SavedTrip


def travel_search(request):
    form_data = {
        "source": "",
        "destination": "",
        "date": "",
        "time": "",
        "passengers": "1",
        "transport": "car",
    }

    context = {
        "form_data": form_data,
        "route_data": None,
        "error": "",
    }

    # Demo rates per vehicle per km; these are not live fares.
    demo_rate_per_km = {
        "car": 12,
        "two_wheeler": 5,
    }

    transport_labels = {
        "car": "Car / Cab",
        "two_wheeler": "Bike / Two-wheeler",
    }

    # Assumed passenger capacity per vehicle.
    passenger_capacity = {
        "car": 4,
        "two_wheeler": 1,
    }

    if request.method == "POST":
        for field in form_data:
            form_data[field] = request.POST.get(
                field, form_data[field]
            ).strip()

        context["form_data"] = form_data

        source = form_data["source"]
        destination = form_data["destination"]
        transport = form_data["transport"]

        if not source or not destination:
            context["error"] = (
                "Please enter both starting location and destination."
            )

        elif source.casefold() == destination.casefold():
            context["error"] = (
                "Starting location and destination must be different."
            )

        elif transport not in transport_labels:
            context["error"] = "Please select a valid transport option."

        else:
            try:
                passengers = int(form_data["passengers"])
            except (ValueError, TypeError):
                passengers = 0

            if not 1 <= passengers <= 50:
                context["error"] = (
                    "Passenger count must be between 1 and 50."
                )

            elif not settings.GOOGLE_MAPS_API_KEY:
                context["error"] = (
                    "Google Routes API key is not configured."
                )

            else:
                payload = {
                    "origin": {"address": source},
                    "destination": {"address": destination},
                    "travelMode": (
                        "TWO_WHEELER"
                        if transport == "two_wheeler"
                        else "DRIVE"
                    ),
                }

                headers = {
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
                    "X-Goog-FieldMask": (
                        "routes.distanceMeters,"
                        "routes.duration,"
                        "routes.polyline.encodedPolyline"
                    ),
                }

                try:
                    response = requests.post(
                        "https://routes.googleapis.com/directions/v2:computeRoutes",
                        headers=headers,
                        json=payload,
                        timeout=25,
                    )

                    if not response.ok:
                        context["error"] = (
                            "Google could not calculate this route. "
                            "Check the locations, API settings and try again."
                        )

                    else:
                        data = response.json()
                        routes = data.get("routes", [])

                        if not routes:
                            context["error"] = (
                                "No route was found for these locations."
                            )

                        else:
                            result = routes[0]

                            distance_km = (
                                result.get("distanceMeters", 0) / 1000
                            )

                            duration_seconds = int(
                                result.get("duration", "0s").rstrip("s")
                            )

                            total_minutes = max(
                                1, round(duration_seconds / 60)
                            )

                            hours, minutes = divmod(total_minutes, 60)

                            duration = (
                                f"{hours} hr {minutes} min"
                                if hours
                                else f"{minutes} min"
                            )

                            encoded_polyline = result.get(
                                "polyline", {}
                            ).get("encodedPolyline", "")

                            if not encoded_polyline:
                                context["error"] = (
                                    "Route was found, but map geometry "
                                    "was not returned."
                                )

                            else:
                                distance_km = round(distance_km, 2)

                                capacity = passenger_capacity[transport]

                                vehicles_required = math.ceil(
                                    passengers / capacity
                                )

                                rate = demo_rate_per_km[transport]

                                estimated_total = round(
                                    distance_km
                                    * rate
                                    * vehicles_required
                                )

                                # English travel recommendation.
                                if vehicles_required > 1:
                                    vehicle_word = (
                                        "bikes"
                                        if transport == "two_wheeler"
                                        else "cars/cabs"
                                    )

                                    recommendation_reason = (
                                        f"For {passengers} passengers, "
                                        f"{vehicles_required} {vehicle_word} "
                                        "are recommended."
                                    )

                                else:
                                    vehicle_word = (
                                        "bike"
                                        if transport == "two_wheeler"
                                        else "car/cab"
                                    )

                                    passenger_word = (
                                        "passenger"
                                        if passengers == 1
                                        else "passengers"
                                    )

                                    recommendation_reason = (
                                        f"For {passengers} {passenger_word}, "
                                        f"1 {vehicle_word} is sufficient."
                                    )

                                context["route_data"] = {
                                    "source": source,
                                    "destination": destination,
                                    "transport_label": (
                                        transport_labels[transport]
                                    ),
                                    "transport": transport,
                                    "estimated_total_fare_raw": (
                                        estimated_total
                                    ),
                                    "distance_km": distance_km,
                                    "duration": duration,
                                    "date": form_data["date"],
                                    "time": form_data["time"],
                                    "passengers": passengers,
                                    "vehicles_required": vehicles_required,
                                    "show_vehicle_count": (
                                        vehicles_required > 1
                                    ),
                                    "recommendation_reason": (
                                        recommendation_reason
                                    ),
                                    "polyline": encoded_polyline,
                                    "estimated_total_fare": (
                                        f"{estimated_total:,}"
                                    ),
                                }

                except requests.RequestException:
                    context["error"] = (
                        "Unable to connect to Google Routes. "
                        "Please try again."
                    )

                except (ValueError, TypeError, KeyError):
                    context["error"] = (
                        "Unexpected route data received. Please try again."
                    )

    return render(request, "travel_search.html", context)


@login_required
def save_trip(request):
    if request.method != "POST":
        return redirect("travel:travel_search")

    source = request.POST.get("source", "").strip()
    destination = request.POST.get("destination", "").strip()
    transport = request.POST.get("transport", "").strip()
    duration = request.POST.get("duration", "").strip()

    try:
        passengers = int(request.POST.get("passengers", "1"))
        distance = Decimal(request.POST.get("distance_km", ""))
        fare = int(request.POST.get("estimated_total_fare", "0"))

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

    except (ValueError, TypeError, InvalidOperation):
        messages.error(
            request,
            "Invalid trip details. Please try again."
        )
        return redirect("travel:travel_search")

    if (
        not source
        or not destination
        or source.casefold() == destination.casefold()
        or transport not in ("car", "two_wheeler")
        or not 1 <= passengers <= 50
        or not distance.is_finite()
        or not Decimal("0") < distance <= Decimal("100000")
        or fare < 0
        or not duration
    ):
        messages.error(
            request,
            "Please check your trip details."
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

    messages.success(request, "Trip saved successfully!")
    return redirect("travel:saved_trips")


@login_required
def saved_trips(request):
    trips = SavedTrip.objects.filter(user=request.user)

    return render(
        request,
        "saved_trips.html",
        {"trips": trips},
    )


@login_required
def delete_saved_trip(request, trip_id):
    if request.method == "POST":
        trip = get_object_or_404(
            SavedTrip,
            id=trip_id,
            user=request.user,
        )

        trip.delete()

        messages.success(request, "Saved trip removed.")

    return redirect("travel:saved_trips")


def book_ticket(request):
    source = request.GET.get("source", "").strip()
    destination = request.GET.get("destination", "").strip()
    transport = request.GET.get("transport", "").strip()

    try:
        distance = float(request.GET.get("distance_km", ""))
        passengers = int(request.GET.get("passengers", "1"))
    except (ValueError, TypeError):
        return redirect("travel:travel_search")

    if (
        not source
        or not destination
        or source.casefold() == destination.casefold()
        or transport not in ("car", "two_wheeler")
        or not math.isfinite(distance)
        or not 0 < distance <= 100000
        or not 1 <= passengers <= 50
    ):
        messages.error(
            request,
            "Please search for a valid route first."
        )
        return redirect("travel:travel_search")

    selected_transport = (
        "Car / Cab" if transport == "car"
        else "Bike / Two-wheeler"
    )

    providers = {
        "car": [
            {
                "name": "Uber",
                "description": "Explore cab rides",
                "url": "https://www.uber.com/in/en/ride/",
            },
            {
                "name": "Ola",
                "description": "Explore cab options",
                "url": "https://www.olacabs.com/",
            },
        ],
        "two_wheeler": [
            {
                "name": "Rapido",
                "description": "Check bike taxi availability",
                "url": "https://www.rapido.bike/",
            },
            {
                "name": "Uber",
                "description": "Check available ride types",
                "url": "https://www.uber.com/in/en/ride/",
            },
        ],
    }

    alternatives = [
        {
            "name": "Bus",
            "description": "Explore intercity bus services",
            "providers": [
                {
                    "name": "redBus",
                    "url": "https://www.redbus.in/",
                },
                {
                    "name": "AbhiBus",
                    "url": "https://www.abhibus.com/",
                },
            ],
        },
        {
            "name": "Train",
            "description": "Check train routes and schedules",
            "providers": [
                {
                    "name": "IRCTC",
                    "url": "https://www.irctc.co.in/",
                },
                {
                    "name": "ixigo",
                    "url": "https://www.ixigo.com/trains",
                },
            ],
        },
        {
            "name": "Flight",
            "description": "Explore flight options",
            "providers": [
                {
                    "name": "MakeMyTrip",
                    "url": "https://www.makemytrip.com/",
                },
                {
                    "name": "EaseMyTrip",
                    "url": "https://www.easemytrip.com/",
                },
            ],
        },
    ]

    if transport == "car":
        alternatives.insert(
            0,
            {
                "name": "Two-wheeler",
                "description": "An alternative for suitable short journeys",
                "providers": [
                    {
                        "name": "Rapido",
                        "url": "https://www.rapido.bike/",
                    },
                    {
                        "name": "Uber",
                        "url": "https://www.uber.com/in/en/ride/",
                    },
                ],
            },
        )
    else:
        alternatives.insert(
            0,
            {
                "name": "Car / Cab",
                "description": "An alternative for your journey",
                "providers": providers["car"],
            },
        )

    if distance <= 10:
        recommendation = (
            "Your selected transport may be practical for this short "
            "journey. Compare available alternatives before deciding."
        )
    elif distance <= 100:
        recommendation = (
            "Consider comparing your selected transport with cab or "
            "bus options, depending on route availability."
        )
    else:
        recommendation = (
            "For this longer journey, compare train and bus options. "
            "Flights may also be worth checking for suitable routes."
        )

    context = {
        "source": source,
        "destination": destination,
        "distance": distance,
        "duration": request.GET.get("duration", "").strip(),
        "passengers": passengers,
        "travel_date": request.GET.get("date", "").strip(),
        "travel_time": request.GET.get("time", "").strip(),
        "selected_transport": selected_transport,
        "selected_options": providers[transport],
        "alternatives": alternatives,
        "recommendation": recommendation,
    }

    return render(request, "booking_options.html", context)