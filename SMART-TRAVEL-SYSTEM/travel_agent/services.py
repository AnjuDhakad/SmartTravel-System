
import json
from difflib import get_close_matches
from pathlib import Path


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
            "how far", "travel time",
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


def process_travel_request(message):
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
            "suggestions": [],
            "attractions": [],
            "hotels": [],
            "message": "Please describe your travel request.",
        }

    cities = extract_cities(message)

    if not cities:
        return {
            "success": False,
            "intent": intents[0],
            "intents": intents,
            "cities": [],
            "source": None,
            "destination": None,
            "suggestions": [],
            "attractions": [],
            "hotels": [],
            "message": (
                "I couldn't identify a supported city. "
                "Please check the spelling or enter another city."
            ),
        }

    source = cities[0]["name"]
    destination = cities[1]["name"] if len(cities) > 1 else None
    destination_city = destination or source

    attractions = []
    hotels = []
    messages = []

    if "route" in intents:
        if destination:
            messages.append(
                f"You want to travel from {source} to {destination}. "
                "Route information is not connected yet."
            )
        else:
            messages.append(
                f"You want route information for {source}. "
                "Please provide your destination."
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
            f"I recognized {names}. Would you like route information, "
            "hotels, tourist places, or booking assistance?"
        )

    return {
        "success": True,
        "intent": intents[0],
        "intents": intents,
        "cities": cities,
        "source": source,
        "destination": destination,
        "suggestions": [],
        "attractions": attractions,
        "hotels": hotels,
        "message": " ".join(messages),
    }
    