import json
from unittest.mock import Mock, patch

from django.test import TestCase

from .services import process_travel_request


class TravelAgentServiceTests(TestCase):
    def test_greeting_starts_a_conversation(self):
        result = process_travel_request("Hello")

        self.assertTrue(result["success"])
        self.assertIn("Where are you going?", result["message"])

    def test_follow_up_uses_previous_city(self):
        first_result = process_travel_request("Show tourist places in Bhopal")
        follow_up = process_travel_request(
            "What about hotels?",
            previous_city=first_result["context_city"],
        )

        self.assertTrue(follow_up["hotels"])
        self.assertEqual(follow_up["context_city"], "Bhopal")

    def test_varanasi_and_chennai_return_listed_attractions(self):
        expected_attractions = {
            "Varanasi": {"Kashi Vishwanath Temple", "Dashashwamedh Ghat"},
            "Chennai": {"Marina Beach", "Kapaleeshwarar Temple"},
        }

        for city, expected_names in expected_attractions.items():
            with self.subTest(city=city):
                result = process_travel_request(
                    f"tourist places in {city}"
                )

                self.assertEqual(
                    {item["name"] for item in result["attractions"]},
                    expected_names,
                )
                self.assertIn("Here are the tourist attractions listed", result["message"])

    @patch("travel_agent.services.calculate_google_route")
    def test_follow_up_route_uses_google_routes(self, calculate_route):
        calculate_route.return_value = {
            "distanceMeters": 190000,
            "duration": "10800s",
        }
        result = process_travel_request(
            "How do I get to Indore?",
            previous_city="Bhopal",
        )

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
        self.assertIn("distance=190.0", result["route"]["comparison"]["compare_url"])
        self.assertIn("Google Routes estimate", result["message"])
        calculate_route.assert_called_once_with("Bhopal", "Indore", "car")

    @patch("travel_agent.services.calculate_google_route")
    def test_route_request_uses_two_wheeler_when_requested(self, calculate_route):
        calculate_route.return_value = {
            "distanceMeters": 190000,
            "duration": "12000s",
        }
        result = process_travel_request(
            "Find a bike route from Bhopal to Indore"
        )

        self.assertEqual(result["route"]["transport"], "two_wheeler")
        calculate_route.assert_called_once_with(
            "Bhopal",
            "Indore",
            "two_wheeler",
        )

    @patch("travel_agent.services.get_route_distance")
    @patch("travel_agent.services.calculate_google_route")
    def test_transit_route_uses_comparison_estimates(
        self,
        calculate_route,
        get_distance,
    ):
        get_distance.return_value = Mock(
            km=190.0,
            source_label="driving distance via OpenStreetMap",
        )
        result = process_travel_request(
            "Find a train route from Bhopal to Indore"
        )

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

    def test_chat_api_keeps_city_context_between_messages(self):
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

    def test_new_conversation_clears_saved_chat(self):
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
    def test_chat_api_returns_google_route_summary(self, calculate_route):
        calculate_route.return_value = {
            "distanceMeters": 190000,
            "duration": "10800s",
        }
        response = self.client.post(
            "/agent/api/chat/",
            data=json.dumps({
                "message": "How do I travel from Bhopal to Indore?"
            }),
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
        conversation_page = self.client.get("/agent/")
        self.assertContains(conversation_page, "Transport options")
        self.assertContains(conversation_page, "190.0 km")
        self.assertContains(conversation_page, "Compare all options")
