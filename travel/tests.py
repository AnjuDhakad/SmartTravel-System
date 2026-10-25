import re
from html import unescape
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from .routes import RouteAPIError, calculate_google_route


class GoogleRoutesTests(SimpleTestCase):
    @override_settings(GOOGLE_MAPS_API_KEY="test-key")
    @patch("travel.routes.requests.post")
    def test_calculate_google_route_returns_route_and_sends_mode(
        self,
        post,
    ):
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "routes": [{
                "distanceMeters": 125000,
                "duration": "7200s",
                "polyline": {"encodedPolyline": "encoded-route"},
            }]
        }
        post.return_value = response

        route = calculate_google_route(
            "Bhopal",
            "Indore",
            "two_wheeler",
        )

        self.assertEqual(route["distanceMeters"], 125000)
        self.assertEqual(route["duration"], "7200s")
        self.assertEqual(
            post.call_args.kwargs["json"]["travelMode"],
            "TWO_WHEELER",
        )
        self.assertEqual(
            post.call_args.kwargs["headers"]["X-Goog-Api-Key"],
            "test-key",
        )

    @override_settings(GOOGLE_MAPS_API_KEY="")
    def test_missing_key_is_reported(self):
        with self.assertRaisesMessage(
            RouteAPIError,
            "Google Routes API key is not configured.",
        ):
            calculate_google_route("Bhopal", "Indore")

    @override_settings(GOOGLE_MAPS_API_KEY="test-key")
    @patch("travel.routes.requests.post")
    def test_google_error_is_reported(self, post):
        response = Mock()
        response.ok = False
        response.status_code = 403
        response.json.return_value = {
            "error": {
                "status": "PERMISSION_DENIED",
                "message": "Routes API has not been enabled.",
            }
        }
        post.return_value = response

        with self.assertRaisesMessage(
            RouteAPIError,
            "HTTP 403",
        ) as error:
            calculate_google_route("Bhopal", "Indore")
        self.assertIn("PERMISSION_DENIED", str(error.exception))
        self.assertIn("Routes API has not been enabled", str(error.exception))
        self.assertIn("billing is active", str(error.exception))

    @override_settings(GOOGLE_MAPS_API_KEY="secret-test-key")
    @patch("travel.routes.requests.post")
    def test_google_error_does_not_expose_api_key(self, post):
        response = Mock()
        response.ok = False
        response.status_code = 403
        response.json.return_value = {
            "error": {
                "status": "PERMISSION_DENIED",
                "message": "Invalid key secret-test-key.",
            }
        }
        post.return_value = response

        with self.assertRaises(RouteAPIError) as error:
            calculate_google_route("Bhopal", "Indore")

        self.assertNotIn("secret-test-key", str(error.exception))
        self.assertIn("[redacted]", str(error.exception))

    @override_settings(GOOGLE_MAPS_API_KEY="test-key")
    @patch("travel.routes.requests.post")
    def test_google_error_without_json_body_still_reports_http_status(
        self,
        post,
    ):
        response = Mock()
        response.ok = False
        response.status_code = 429
        response.json.side_effect = ValueError("not JSON")
        post.return_value = response

        with self.assertRaisesMessage(
            RouteAPIError,
            "HTTP 429",
        ) as error:
            calculate_google_route("Bhopal", "Indore")
        self.assertIn("quota may be exhausted", str(error.exception))
        self.assertEqual(error.exception.status_code, 429)


class TravelSearchComparisonIntegrationTests(SimpleTestCase):
    @override_settings(GOOGLE_MAPS_API_KEY="test-key")
    @patch("travel.views.calculate_google_route")
    def test_route_results_link_to_comparison_with_route_details(self, calculate):
        calculate.return_value = {
            "distanceMeters": 125000,
            "duration": "7200s",
            "polyline": {"encodedPolyline": "encoded-route"},
        }

        response = self.client.post(
            reverse("travel:travel_search"),
            {
                "source": "Bhopal Central",
                "destination": "Indore",
                "date": "",
                "time": "",
                "passengers": "2",
                "transport": "car",
            },
        )

        self.assertEqual(response.status_code, 200)
        match = re.search(
            r'href="([^"]*/compare/\?[^"]+)"',
            response.content.decode(),
        )
        self.assertIsNotNone(match)
        query = parse_qs(urlparse(unescape(match.group(1))).query)
        self.assertEqual(query["origin"], ["Bhopal Central"])
        self.assertEqual(query["destination"], ["Indore"])
        self.assertEqual(query["distance"], ["125.0"])
        self.assertEqual(query["passengers"], ["2"])
