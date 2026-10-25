
import json
from difflib import get_close_matches
from pathlib import Path

from travel.routes import RouteAPIError, calculate_google_route


DATA_FOLDER = Path(__file__).parent / "data"


def get_cities():
    with open(DATA_FOLDER / "cities.json", encoding="utf-8") as file:
        return json.load(file)


def get_attractions(city_name):
    with open(DATA_FOLDER / "attractions.json", encoding="utf-8") as file:
        attractions = json.load(file)

    return [
        item for item in attractions
        if item["city"].lower() == city_name.lower()
    ]


def get_hotels(city_name):
    with open(DATA_FOLDER / "hotels.json", encoding="utf-8") as file:
        hotels = json.load(file)

    return [
        hotel for hotel in hotels
        if hotel["city"].lower() == city_name.lower()
    ]


def find_city(name):
    cities = get_cities()
    name = name.strip()

    for city in cities:
        if city["name"].lower() == name.lower():
            return {
                "found": True,
                "city": city,
                "suggestions": [],
            }

    city_names = [city["name"] for city in cities]

    return {
        "found": False,
        "city": None,
        "suggestions": get_close_matches(
            name, city_names, n=3, cutoff=0.6
        ),
    }



def extract_cities(message):
    message = message.lower()
    cities = get_cities()
    found = []

    for city in cities:
        city_name = city["name"].lower()

        if city_name in message:
            position = message.find(city_name)
            found.append((position, city))

    found.sort(key=lambda item: item[0])

    return [city for position, city in found]




def identify_intents(message):
    message = message.lower()

    keywords = {
        "hotel": [
            "hotel", "hotels", "accommodation",
            "stay", "room", "rooms", "resort",
            "where can i stay", "places to stay",
            "find me a place to stay",
        ],
        "places": [
            "tourist", "attraction", "attractions",
            "sightseeing", "places to visit",
            "things to do", "what to see",
            "explore", "places to explore",
        ],
        "booking": [
            "book", "booking", "ticket", "reservation",
            "make a reservation", "book a room",
        ],
        "route": [
            "route", "travel", "journey", "transport",
            "distance", "directions", "how to reach",
            "how do i get to", "how can i get to",
            "how far", "travel time", "drive", "driving",
            "bike", "motorcycle", "bus", "train", "flight",
            "plane", "cab", "taxi", "road trip", "go from",
            "go to", "going to", "trip from", "directions to",
        ],
    }

    intents = []

    for intent, words in keywords.items():
        for word in words:
            if word in message:
                intents.append(intent)
                break

    return intents or ["general"]



def identify_intent(message):
    return identify_intents(message)[0]


def process_travel_request(message, previous_city=None):
    message = message.strip()
    intents = identify_intents(message)

    if not message:
        return {
            "success": False,
            "intent": "general",
            "intents": ["general"],
            "cities": [],
            "source": None,
            "destination": None,
            "context_city": previous_city,
            "suggestions": [],
            "attractions": [],
            "hotels": [],
            "route": None,
            "message": "Please describe your travel request.",
        }

    cities = extract_cities(message)

    if not cities and previous_city:
        if "route" in intents:
            return {
                "success": True,
                "intent": intents[0],
                "intents": intents,
                "cities": [],
                "source": previous_city,
                "destination": None,
                "context_city": previous_city,
                "suggestions": [],
                "attractions": [],
                "hotels": [],
                "route": None,
                "message": (
                    f"Are you travelling from {previous_city}? "
                    "Tell me the destination city and I can help you plan."
                ),
            }
        if any(intent in intents for intent in ("hotel", "places", "booking")):
            city_result = find_city(previous_city)
            if city_result["found"]:
                cities = [city_result["city"]]

    if not cities:
        lowered_message = message.lower().strip(" .,!?")
        if lowered_message in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}:
            reply = (
                "Hello! I can help you explore tourist places and hotels, "
                "or plan a journey between supported cities. Where are you going?"
            )
            success = True
        elif lowered_message in {"thanks", "thank you", "thanks a lot"}:
            reply = "You're welcome! Let me know where you'd like to travel next."
            success = True
        elif intents == ["general"]:
            reply = (
                "I'm your local travel assistant. I can suggest hotels and "
                "tourist attractions from my travel guide. Try asking, "
                "\"What places can I visit in Bhopal?\""
            )
            success = True
        else:
            reply = (
                "I couldn't identify that city in my travel guide. "
                "Please try a supported city such as Bhopal, Indore, Jaipur, "
                "Delhi, or Mumbai."
            )
            success = False
        return {
            "success": success,
            "intent": intents[0],
            "intents": intents,
            "cities": [],
            "source": None,
            "destination": None,
            "context_city": previous_city,
            "suggestions": [],
            "attractions": [],
            "hotels": [],
            "route": None,
            "message": reply,
        }

    if "route" in intents and len(cities) == 1 and previous_city:
        if cities[0]["name"].casefold() != previous_city.casefold():
            source = previous_city
            destination = cities[0]["name"]
        else:
            source = cities[0]["name"]
            destination = None
    else:
        source = cities[0]["name"]
        destination = cities[1]["name"] if len(cities) > 1 else None

    destination_city = destination or cities[-1]["name"]

    attractions = []
    hotels = []
    route_data = None
    messages = []

    if "route" in intents:
        if destination:
            lowered_message = message.lower()
            unsupported_modes = ("bus", "train", "flight", "plane")
            if any(mode in lowered_message for mode in unsupported_modes):
                messages.append(
                    "The connected route service currently supports "
                    "driving and two-wheeler routes. Use Search Routes "
                    "for the available options."
                )
            else:
                transport = (
                    "two_wheeler"
                    if any(
                        word in lowered_message
                        for word in ("bike", "motorcycle", "two-wheeler")
                    )
                    else "car"
                )
                transport_label = (
                    "two-wheeler"
                    if transport == "two_wheeler"
                    else "driving"
                )
                try:
                    google_route = calculate_google_route(
                        source,
                        destination,
                        transport,
                    )
                    distance_km = round(
                        float(google_route["distanceMeters"]) / 1000,
                        2,
                    )
                    duration_seconds = int(
                        str(google_route["duration"]).rstrip("s")
                    )
                    hours, remaining_seconds = divmod(
                        duration_seconds,
                        3600,
                    )
                    minutes = round(remaining_seconds / 60)
                    if minutes == 60:
                        hours += 1
                        minutes = 0
                    duration = (
                        f"{hours} hr {minutes} min"
                        if hours
                        else f"{minutes} min"
                    )
                    route_data = {
                        "distance_km": distance_km,
                        "duration": duration,
                        "transport": transport,
                    }
                    messages.append(
                        f"The Google Routes estimate from {source} to "
                        f"{destination} by {transport_label} is about "
                        f"{distance_km} km and {duration}. "
                        "Use Search Routes for passenger and fare options."
                    )
                except RouteAPIError as exc:
                    messages.append(str(exc))
                except (KeyError, TypeError, ValueError):
                    messages.append(
                        "Google returned unexpected route data. "
                        "Please try the route search again."
                    )
        else:
            messages.append(
                f"I have {source} as your starting city. "
                "What city would you like to travel to?"
            )

    if "hotel" in intents:
        hotels = get_hotels(destination_city)

        if hotels:
            names = ", ".join(hotel["name"] for hotel in hotels)
            messages.append(
                f"Here are some hotels in {destination_city}: {names}"
            )
        else:
            messages.append(
                f"No hotels are currently listed for {destination_city}."
            )

    if "places" in intents:
        attractions = get_attractions(destination_city)

        if attractions:
            names = ", ".join(
                attraction["name"] for attraction in attractions
            )
            messages.append(
                f"Here are the tourist attractions listed for "
                f"{destination_city}: {names}"
            )
        else:
            messages.append(
                f"No tourist attractions are currently listed for "
                f"{destination_city} in our local dataset."
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

    return {
        "success": True,
        "intent": intents[0],
        "intents": intents,
        "cities": cities,
        "source": source,
        "destination": destination,
        "context_city": destination_city,
        "suggestions": [],
        "attractions": attractions,
        "hotels": hotels,
        "route": route_data,
        "message": " ".join(messages),
    }
    