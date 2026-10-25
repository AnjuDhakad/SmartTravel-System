import json
from functools import lru_cache
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline


DATA_FOLDER = Path(__file__).parent / "data"

_INTENT_TRAINING_DATA = (
    ("find hotels in Bhopal", "hotel"),
    ("show me accommodation in Jaipur", "hotel"),
    ("where can I stay in Indore", "hotel"),
    ("recommend a resort in Mumbai", "hotel"),
    ("I need a room in Bhopal", "hotel"),
    ("list places to stay in Jaipur", "hotel"),
    ("show tourist attractions in Bhopal", "places"),
    ("what can I see in Jaipur", "places"),
    ("recommend sightseeing in Mumbai", "places"),
    ("what should I explore in Indore", "places"),
    ("list things to do in Bhopal", "places"),
    ("show me places to visit in Jaipur", "places"),
    ("how do I book a hotel in Bhopal", "booking"),
    ("I want to make a reservation in Jaipur", "booking"),
    ("help me book a room in Indore", "booking"),
    ("where can I get tickets for Mumbai", "booking"),
    ("show me booking options in Bhopal", "booking"),
    ("I need to reserve accommodation in Jaipur", "booking"),
    ("how do I get to Bhopal from Indore", "route"),
    ("show the route from Jaipur to Mumbai", "route"),
    ("how far is Indore from Bhopal", "route"),
    ("what is the travel time to Jaipur", "route"),
    ("give me directions to Mumbai", "route"),
    ("help me plan a journey from Bhopal to Indore", "route"),
    ("tell me about Bhopal", "general"),
    ("I am planning a trip to Jaipur", "general"),
    ("what do you know about Indore", "general"),
    ("hello, can you help me plan a trip", "general"),
    ("I want information about Mumbai", "general"),
    ("help me with my travel plans", "general"),
)


def _load_training_data() -> list[tuple[str, str]]:
    training_data = list(_INTENT_TRAINING_DATA)

    with open(DATA_FOLDER / "cities.json", encoding="utf-8") as file:
        cities = json.load(file)
    with open(DATA_FOLDER / "hotels.json", encoding="utf-8") as file:
        hotels = json.load(file)
    with open(DATA_FOLDER / "attractions.json", encoding="utf-8") as file:
        attractions = json.load(file)

    training_data.extend(
        (
            f"travel information for {city['name']} in {city['state']}",
            "general",
        )
        for city in cities
    )
    training_data.extend(
        (
            f"recommend a stay at {hotel['name']} in {hotel['city']}: "
            f"{hotel['description']}",
            "hotel",
        )
        for hotel in hotels
    )
    training_data.extend(
        (
            f"tell me about {attraction['name']} in {attraction['city']}: "
            f"{attraction['category']} {attraction['description']}",
            "places",
        )
        for attraction in attractions
    )

    return training_data


class TravelIntentModel:
    """Small text classifier for the intents supported by the travel agent."""

    def __init__(self) -> None:
        self._pipeline = Pipeline([
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    strip_accents="unicode",
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=0,
                    C=3,
                ),
            ),
        ])
        messages, intents = zip(*_load_training_data())
        self._pipeline.fit(messages, intents)

    def predict(self, message: str) -> str | None:
        probabilities = self._pipeline.predict_proba([message])[0]
        classifier = self._pipeline.named_steps["classifier"]
        best_index = int(probabilities.argmax())

        if probabilities[best_index] < 0.4:
            return None

        return str(classifier.classes_[best_index])


@lru_cache(maxsize=1)
def get_travel_intent_model() -> TravelIntentModel:
    return TravelIntentModel()
