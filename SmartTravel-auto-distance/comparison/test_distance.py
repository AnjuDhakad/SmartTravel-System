import urllib.error
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse

from comparison import distance
from comparison.distance import DistanceError, get_route_distance, haversine_km

PLACES = {
    "Indore": [{"lat": "22.7196", "lon": "75.8577", "display_name": "Indore, Madhya Pradesh, India"}],
    "Bhopal": [{"lat": "23.2599", "lon": "77.4126", "display_name": "Bhopal, Madhya Pradesh, India"}],
    "Nowhereville": [],
}


def fake_http(url):
    """Pretend to be Nominatim + OSRM."""
    if "nominatim" in url:
        for name, result in PLACES.items():
            if f"q={name}" in url:
                return result
        return []
    if "osrm" in url:
        return {"code": "Ok", "routes": [{"distance": 195400.0}]}
    raise AssertionError(url)


def offline_routing(url):
    """Geocoding works but the routing service is down."""
    if "osrm" in url:
        raise urllib.error.URLError("down")
    return fake_http(url)


class DistanceBase(SimpleTestCase):
    def setUp(self):
        distance.geocode.cache_clear()
        p1 = mock.patch("comparison.distance._throttle")
        p1.start()
        self.addCleanup(p1.stop)


class HaversineTests(SimpleTestCase):
    def test_indore_bhopal_straight_line(self):
        km = haversine_km(22.7196, 75.8577, 23.2599, 77.4126)
        self.assertTrue(160 < km < 190, km)

    def test_same_point_is_zero(self):
        self.assertAlmostEqual(haversine_km(10, 10, 10, 10), 0)


class GetRouteDistanceTests(DistanceBase):
    @mock.patch("comparison.distance._http_get_json", side_effect=fake_http)
    def test_road_distance(self, _):
        r = get_route_distance("Indore", "Bhopal")
        self.assertEqual(r.km, 195.4)
        self.assertEqual(r.source, "road")
        self.assertIn("Indore", r.from_name)

    @mock.patch("comparison.distance._http_get_json", side_effect=offline_routing)
    def test_falls_back_to_estimate_when_routing_down(self, _):
        r = get_route_distance("Indore", "Bhopal")
        self.assertEqual(r.source, "estimate")
        self.assertTrue(200 < r.km < 250, r.km)

    @mock.patch("comparison.distance._http_get_json", side_effect=fake_http)
    def test_unknown_place(self, _):
        with self.assertRaisesRegex(DistanceError, "Nowhereville"):
            get_route_distance("Indore", "Nowhereville")

    @mock.patch("comparison.distance._http_get_json", side_effect=fake_http)
    def test_same_place(self, _):
        with self.assertRaisesRegex(DistanceError, "same place"):
            get_route_distance("Indore", "Indore")

    def test_empty_inputs(self):
        with self.assertRaises(DistanceError):
            get_route_distance("", "Bhopal")

    @mock.patch("comparison.distance._http_get_json", side_effect=urllib.error.URLError("no net"))
    def test_no_internet_message(self, _):
        with self.assertRaisesRegex(DistanceError, "internet"):
            get_route_distance("Indore", "Bhopal")

    @mock.patch("comparison.distance._http_get_json", side_effect=fake_http)
    def test_geocode_results_are_cached(self, m):
        get_route_distance("Indore", "Bhopal")
        calls = m.call_count
        get_route_distance("Indore", "Bhopal")
        self.assertEqual(m.call_count, calls + 1)  # only the routing call repeats


class AutoDistanceViewTests(DistanceBase):
    @mock.patch("comparison.distance._http_get_json", side_effect=fake_http)
    def test_page_calculates_distance_automatically(self, _):
        resp = self.client.get(reverse("comparison:compare"),
                               {"origin": "Indore", "destination": "Bhopal"})
        self.assertContains(resp, "RECOMMENDED")
        self.assertContains(resp, "195.4 km")
        self.assertContains(resp, "OpenStreetMap")
        self.assertEqual(resp.context["result"].distance_km, 195.4)

    @mock.patch("comparison.distance._http_get_json", side_effect=fake_http)
    def test_manual_distance_overrides_lookup(self, m):
        resp = self.client.get(reverse("comparison:compare"),
                               {"origin": "Indore", "destination": "Bhopal", "distance": "100"})
        self.assertEqual(resp.context["result"].distance_km, 100)
        self.assertContains(resp, "entered manually")
        m.assert_not_called()

    @mock.patch("comparison.distance._http_get_json", side_effect=fake_http)
    def test_unknown_place_shows_error(self, _):
        resp = self.client.get(reverse("comparison:compare"),
                               {"origin": "Indore", "destination": "Nowhereville"})
        self.assertContains(resp, "Could not find the place")
        self.assertNotContains(resp, "RECOMMENDED")

    def test_missing_destination_shows_error(self):
        resp = self.client.get(reverse("comparison:compare"), {"origin": "Indore"})
        self.assertContains(resp, "both a starting point and a destination")

    @mock.patch("comparison.distance._http_get_json", side_effect=fake_http)
    def test_api_auto_distance(self, _):
        resp = self.client.get(reverse("comparison:api"),
                               {"origin": "Indore", "destination": "Bhopal", "priority": "cheapest"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["distance_km"], 195.4)
        self.assertEqual(data["distance_source"], "road")

    @mock.patch("comparison.distance._http_get_json", side_effect=fake_http)
    def test_api_bad_place_is_400(self, _):
        resp = self.client.get(reverse("comparison:api"),
                               {"origin": "Indore", "destination": "Nowhereville"})
        self.assertEqual(resp.status_code, 400)
