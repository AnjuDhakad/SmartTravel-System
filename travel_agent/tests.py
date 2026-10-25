import json
from unittest.mock import Mock, patch

from django.test import TestCase

from .api_clients import LanguageModelError, understand_message
from travel.routes import RouteAPIError
from .services import process_travel_request


def fake_understanding(intents, source=None, destination=None, city=None, transport="car"):
    return {
        "intents": intents,
        "source": source,
        "destination": destination,
        "city": city,
        "transport": transport,
    }


SAMPLE_HOTELS = [
    {"name": "Hotel One", "city": "Bhopal", "description": "A hotel.", "booking_url": "https://example.com/1"},
    {"name": "Hotel Two", "city": "Bhopal", "description": "Another hotel.", "booking_url": "https://example.com/2"},
]
SAMPLE_ATTRACTIONS = [
    {"name": "Upper Lake", "city": "Bhopal", "category": "Nature", "description": "A lake.", "website_url": "https://example.com/lake"},
]
SAMPLE_CITY = {"found": True, "city": {"name": "Bhopal", "country": "IN", "lat": 23.25, "lon": 77.4}, "suggestions": []}


class LanguageModelClientTests(TestCase):
    @patch.dict(
        "travel_agent.api_clients.os.environ",
        {"GROQ_API_KEY": "test-key"},
        clear=True,
    )
    @patch("travel_agent.api_clients.requests.post")
    def test_default_model_and_authorization_are_used(self, post):
        post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "choices": [{
                    "message": {
                        "content": (
                            '{"intents":["general"],"source":null,'
                            '"destination":null,"city":null,"transport":"car"}'
                        )
                    }
                }]
            },
        )

        understand_message("What can you help me with?")

        request = post.call_args
        self.assertEqual(request.kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(request.kwargs["json"]["model"], "openai/gpt-oss-120b")

    @patch.dict(
        "travel_agent.api_clients.os.environ",
        {"GROQ_API_KEY": "test-key"},
        clear=True,
    )
    @patch("travel_agent.api_clients.requests.post")
    def test_missing_model_error_identifies_model_configuration(self, post):
        post.return_value = Mock(status_code=404)

        with self.assertRaisesMessage(LanguageModelError, "Check GROQ_MODEL"):
            understand_message("What can you help me with?")

    @patch.dict(
        "travel_agent.api_clients.os.environ",
        {"GROQ_API_KEY": "test-key"},
        clear=True,
    )
    @patch("travel_agent.api_clients.requests.post")
    def test_other_http_errors_include_status(self, post):
        post.return_value = Mock(status_code=500)

        with self.assertRaisesMessage(LanguageModelError, "HTTP 500"):
            understand_message("What can you help me with?")


@patch("travel_agent.services.find_city", return_value=SAMPLE_CITY)
@patch("travel_agent.services.get_attractions", return_value=SAMPLE_ATTRACTIONS)
@patch("travel_agent.services.get_hotels", return_value=SAMPLE_HOTELS)
@patch("travel_agent.services.understand_message")
class TravelAgentServiceTests(TestCase):
    def test_invalid_non_string_input_is_handled_gracefully(self, understand, hotels, attractions, city):
        result = process_travel_request(None)

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Please describe your travel request.")
        understand.assert_not_called()

    def test_greeting_starts_a_conversation(self, understand, hotels, attractions, city):
        understand.return_value = fake_understanding(["greeting"])
        result = process_travel_request("Hello")

        self.assertTrue(result["success"])
        self.assertIn("Where are you going?", result["message"])

    def test_hotel_request_fetches_hotels_from_api(self, understand, hotels, attractions, city):
        understand.return_value = fake_understanding(["hotel"], city="Bhopal")
        result = process_travel_request("Suggest hotels in Bhopal")

        self.assertEqual(len(result["hotels"]), 2)
        self.assertIn("Hotel One", result["message"])
        self.assertEqual(result["context_city"], "Bhopal")

    def test_message_in_another_language_works_through_groq(self, understand, hotels, attractions, city):
        # Groq turns the Hinglish message into clean intents and a city.
        understand.return_value = fake_understanding(["places"], city="Bhopal")
        result = process_travel_request("Bhopal mein ghumne ki jagah batao")

        self.assertEqual(result["attractions"], SAMPLE_ATTRACTIONS)
        self.assertIn("Upper Lake", result["message"])

    def test_follow_up_uses_previous_city(self, understand, hotels, attractions, city):
        understand.return_value = fake_understanding(["hotel"])
        follow_up = process_travel_request("What about hotels?", previous_city="Bhopal")

        self.assertTrue(follow_up["hotels"])
        self.assertEqual(follow_up["context_city"], "Bhopal")
        hotels.assert_called_once_with("Bhopal")

    def test_hotel_request_without_any_city_asks_for_one(self, understand, hotels, attractions, city):
        understand.return_value = fake_understanding(["hotel"])
        result = process_travel_request("Find me a hotel")

        self.assertFalse(result["success"])
        self.assertIn("Which city", result["message"])
        hotels.assert_not_called()

    def test_unknown_city_gives_a_friendly_message(self, understand, hotels, attractions, city):
        city.return_value = {"found": False, "city": None, "suggestions": []}
        understand.return_value = fake_understanding(["places"], city="Xyzabc")
        result = process_travel_request("places in Xyzabc")

        self.assertFalse(result["success"])
        self.assertIn("couldn't find Xyzabc", result["message"])
        attractions.assert_not_called()

    def test_language_service_failure_is_reported_not_raised(self, understand, hotels, attractions, city):
        understand.side_effect = LanguageModelError("The language service is busy right now.")
        result = process_travel_request("hotels in Bhopal")

        self.assertFalse(result["success"])
        self.assertIn("busy", result["message"])

    @patch("travel_agent.services.calculate_google_route")
    def test_follow_up_route_uses_google_routes(self, calculate_route, understand, hotels, attractions, city):
        calculate_route.return_value = {"distanceMeters": 190000, "duration": "10800s"}
        understand.return_value = fake_understanding(["route"], destination="Indore")
        result = process_travel_request("How do I get to Indore?", previous_city="Bhopal")

        self.assertEqual(result["source"], "Bhopal")
        self.assertEqual(result["destination"], "Indore")
        self.assertEqual(
            {
                key: result["route"][key]
                for key in ("distance_km", "duration", "transport")
            },
            {"distance_km": 190.0, "duration": "3 hr 0 min", "transport": "car"},
        )
        self.assertTrue(result["route"]["comparison"]["options"])
        self.assertIn(
            "distance=190.0",
            result["route"]["comparison"]["compare_url"],
        )
        self.assertIn("Google Routes estimate", result["message"])
        calculate_route.assert_called_once_with("Bhopal", "Indore", "car")

    @patch("travel_agent.services.calculate_google_route")
    def test_route_request_uses_two_wheeler_when_requested(self, calculate_route, understand, hotels, attractions, city):
        calculate_route.return_value = {"distanceMeters": 190000, "duration": "12000s"}
        understand.return_value = fake_understanding(
            ["route"], source="Bhopal", destination="Indore", transport="two_wheeler"
        )
        result = process_travel_request("Find a bike route from Bhopal to Indore")

        self.assertEqual(result["route"]["transport"], "two_wheeler")
        calculate_route.assert_called_once_with("Bhopal", "Indore", "two_wheeler")

    @patch("travel_agent.services.calculate_google_route")
    def test_unspecified_route_mode_defaults_to_driving(self, calculate_route, understand, hotels, attractions, city):
        calculate_route.return_value = {"distanceMeters": 190000, "duration": "10800s"}
        understand.return_value = fake_understanding(
            ["route"], source="Bhopal", destination="Indore", transport="other"
        )

        result = process_travel_request("How can I travel from Bhopal to Indore?")

        self.assertEqual(result["route"]["transport"], "car")
        self.assertIn("Google Routes estimate", result["message"])
        calculate_route.assert_called_once_with("Bhopal", "Indore", "car")

    @patch("travel_agent.services.get_route_distance")
    @patch("travel_agent.services.calculate_google_route")
    def test_google_routes_quota_error_falls_back_to_alternate_distance(
        self,
        calculate_route,
        get_distance,
        understand,
        hotels,
        attractions,
        city,
    ):
        calculate_route.side_effect = RouteAPIError(
            "Google Routes quota exceeded (HTTP 429).",
            status_code=429,
        )
        get_distance.return_value = Mock(
            km=195.4,
            source_label="driving distance via OpenStreetMap",
        )
        understand.return_value = fake_understanding(
            ["route"], source="Bhopal", destination="Indore"
        )

        result = process_travel_request("How can I travel from Bhopal to Indore?")

        self.assertEqual(result["route"]["distance_km"], 195.4)
        self.assertEqual(
            result["route"]["comparison"]["distance_source"],
            "driving distance via OpenStreetMap",
        )
        self.assertIn("alternate distance source", result["message"])
        self.assertIn("195.4 km", result["message"])
        get_distance.assert_called_once_with("Bhopal", "Indore")

    @patch("travel_agent.services.get_route_distance")
    @patch("travel_agent.services.calculate_google_route")
    def test_non_quota_google_route_error_does_not_fall_back(
        self,
        calculate_route,
        get_distance,
        understand,
        hotels,
        attractions,
        city,
    ):
        calculate_route.side_effect = RouteAPIError(
            "Google Routes could not calculate this route (HTTP 403).",
            status_code=403,
        )
        understand.return_value = fake_understanding(
            ["route"], source="Bhopal", destination="Indore"
        )

        result = process_travel_request("How can I travel from Bhopal to Indore?")

        self.assertIsNone(result["route"])
        self.assertIn("HTTP 403", result["message"])
        get_distance.assert_not_called()

    @patch("travel_agent.services.get_route_distance")
    @patch("travel_agent.services.calculate_google_route")
    def test_transit_route_uses_comparison_estimates(self, calculate_route, get_distance, understand, hotels, attractions, city):
        get_distance.return_value = Mock(
            km=190.0,
            source_label="driving distance via OpenStreetMap",
        )
        understand.return_value = fake_understanding(
            ["route"], source="Bhopal", destination="Indore", transport="other"
        )
        result = process_travel_request("Find a train route from Bhopal to Indore")

        self.assertEqual(result["route"]["distance_km"], 190.0)
        self.assertTrue(result["route"]["comparison"]["options"])
        self.assertIn("not live fares or schedules", result["message"])
        get_distance.assert_called_once_with("Bhopal", "Indore")
        calculate_route.assert_not_called()


class TravelAgentChatViewTests(TestCase):
    def test_chat_page_renders(self):
        response = self.client.get("/agent/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Start a new conversation")

    @patch("travel_agent.services.find_city", return_value=SAMPLE_CITY)
    @patch("travel_agent.services.get_attractions", return_value=SAMPLE_ATTRACTIONS)
    @patch("travel_agent.services.get_hotels", return_value=SAMPLE_HOTELS)
    @patch("travel_agent.services.understand_message")
    def test_chat_api_keeps_city_context_between_messages(self, understand, hotels, attractions, city):
        understand.side_effect = [
            fake_understanding(["hotel"], city="Bhopal"),
            fake_understanding(["places"]),
        ]
        first_response = self.client.post(
            "/agent/api/chat/",
            data=json.dumps({"message": "Suggest hotels in Bhopal"}),
            content_type="application/json",
        )
        second_response = self.client.post(
            "/agent/api/chat/",
            data=json.dumps({"message": "What about tourist places?"}),
            content_type="application/json",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertTrue(first_response.json()["hotels"])
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(second_response.json()["attractions"])
        self.assertEqual(second_response.json()["context_city"], "Bhopal")

    @patch("travel_agent.services.find_city", return_value=SAMPLE_CITY)
    @patch("travel_agent.services.get_hotels", return_value=SAMPLE_HOTELS)
    @patch("travel_agent.services.understand_message")
    def test_new_conversation_clears_saved_chat(self, understand, hotels, city):
        understand.return_value = fake_understanding(["hotel"], city="Bhopal")
        self.client.post(
            "/agent/api/chat/",
            data=json.dumps({"message": "Hotels in Bhopal"}),
            content_type="application/json",
        )

        response = self.client.get("/agent/?new=1")

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("travel_agent_conversation", self.client.session)
        self.assertNotIn("travel_agent_city", self.client.session)

    @patch("travel_agent.services.calculate_google_route")
    @patch("travel_agent.services.understand_message")
    def test_chat_api_returns_google_route_summary(self, understand, calculate_route):
        calculate_route.return_value = {"distanceMeters": 190000, "duration": "10800s"}
        understand.return_value = fake_understanding(
            ["route"], source="Bhopal", destination="Indore"
        )
        response = self.client.post(
            "/agent/api/chat/",
            data=json.dumps({"message": "How do I travel from Bhopal to Indore?"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        route = response.json()["route"]
        self.assertEqual(route["distance_km"], 190.0)
        self.assertTrue(route["comparison"]["options"])
        self.assertTrue(route["comparison"]["compare_url"].startswith("/compare/?"))
        self.assertIn("3 hr 0 min", response.json()["message"])
        comparison_page = self.client.get(route["comparison"]["compare_url"])
        self.assertEqual(comparison_page.status_code, 200)
        self.assertContains(comparison_page, "Compare Transport Options")
        conversation_page = self.client.get("/agent/")
        self.assertContains(conversation_page, "Transport options")
        self.assertContains(conversation_page, "190.0 km")
        self.assertContains(conversation_page, "Compare all options")
