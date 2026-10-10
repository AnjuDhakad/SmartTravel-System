from django.test import SimpleTestCase
from django.urls import reverse

from .services import (
    ComparisonError, build_options, recommend, score_options, validate_inputs,
)


def modes(result):
    return [o.mode for o in result.options]


class RouteScenarioTests(SimpleTestCase):
    """Testing different route options: short, city, intercity, long-haul."""

    def test_very_short_route_excludes_train_and_flight(self):
        r = recommend(2)
        self.assertNotIn("train", modes(r))
        self.assertNotIn("flight", modes(r))
        self.assertIn(r.best.mode, {"walk", "bike"})

    def test_walking_not_offered_beyond_5km(self):
        self.assertNotIn("walk", modes(recommend(12)))

    def test_city_route_balanced_is_car_or_bike(self):
        self.assertIn(recommend(12).best.mode, {"car", "bike"})

    def test_intercity_200km_prefers_train_when_balanced(self):
        r = recommend(200)
        self.assertEqual(r.best.mode, "train")
        self.assertNotIn("flight", modes(r))

    def test_long_route_800km_balanced_is_flight(self):
        self.assertEqual(recommend(800).best.mode, "flight")

    def test_flight_not_offered_under_300km(self):
        self.assertNotIn("flight", modes(recommend(250)))


class PriorityTests(SimpleTestCase):
    def test_cheapest_priority_picks_lowest_cost(self):
        r = recommend(200, "cheapest")
        self.assertEqual(r.best.cost, min(o.cost for o in r.options))

    def test_fastest_priority_picks_shortest_time(self):
        r = recommend(800, "fastest")
        self.assertEqual(r.best.time_min, min(o.time_min for o in r.options))

    def test_eco_priority_picks_lowest_co2(self):
        r = recommend(800, "eco")
        self.assertEqual(r.best.co2_kg, min(o.co2_kg for o in r.options))

    def test_priority_changes_the_winner(self):
        self.assertNotEqual(recommend(800, "fastest").best.mode,
                            recommend(800, "cheapest").best.mode)


class ScoringTests(SimpleTestCase):
    def test_options_sorted_best_first(self):
        scores = [o.score for o in recommend(200).options]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_scores_within_0_100(self):
        for km in (1, 5, 50, 500, 3000):
            for o in recommend(km).options:
                self.assertTrue(0 <= o.score <= 100, (km, o.mode, o.score))

    def test_single_option_has_no_badges_and_one_reason_about_it(self):
        r = recommend(4000)  # only flight and train remain realistic; check 1-option edge below
        single = score_options(build_options(15000))  # flight only
        self.assertEqual(len(single), 1)
        self.assertEqual(single[0].badges, [])
        self.assertTrue(r.reasons)

    def test_deterministic(self):
        self.assertEqual(recommend(123).best.mode, recommend(123).best.mode)


class PassengerTests(SimpleTestCase):
    def test_cost_scales_with_travellers(self):
        solo = {o.mode: o.cost for o in build_options(200, 1)}
        group = {o.mode: o.cost for o in build_options(200, 3)}
        self.assertAlmostEqual(group["train"], solo["train"] * 3)

    def test_car_is_shared_up_to_4_people(self):
        one = {o.mode: o.cost for o in build_options(200, 1)}["car"]
        four = {o.mode: o.cost for o in build_options(200, 4)}["car"]
        five = {o.mode: o.cost for o in build_options(200, 5)}["car"]
        self.assertEqual(one, four)
        self.assertEqual(five, one * 2)

    def test_car_becomes_cost_competitive_for_group(self):
        r = recommend(200, "cheapest", passengers=4)
        costs = {o.mode: o.cost for o in r.options}
        self.assertLess(costs["car"], costs["bus"] * 4)


class ReasonTests(SimpleTestCase):
    def test_reasons_present_and_mention_priority(self):
        r = recommend(200, "eco")
        self.assertGreaterEqual(len(r.reasons), 2)
        self.assertIn("eco-friendly", r.reasons[0])

    def test_zero_emission_reason_for_walk_or_bike(self):
        r = recommend(2, "eco")
        self.assertIn("Zero carbon emissions.", r.reasons)


class ValidationTests(SimpleTestCase):
    def test_bad_inputs_raise(self):
        bad = [("abc", "balanced", 1), (0, "balanced", 1), (-5, "balanced", 1),
               (float("nan"), "balanced", 1), (float("inf"), "balanced", 1),
               (99999, "balanced", 1), (10, "nope", 1), (10, "balanced", 0),
               (10, "balanced", 99), (10, "balanced", "x"), (None, "balanced", 1)]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ComparisonError):
                validate_inputs(*args)

    def test_string_numbers_accepted(self):
        self.assertEqual(validate_inputs("12.5", "fastest", "2"), (12.5, "fastest", 2))


class ViewTests(SimpleTestCase):
    def test_page_loads_without_params(self):
        resp = self.client.get(reverse("comparison:compare"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Compare Transport Options")
        self.assertNotContains(resp, "RECOMMENDED")

    def test_page_shows_recommendation(self):
        resp = self.client.get(reverse("comparison:compare"),
                               {"origin": "Indore", "destination": "Bhopal", "distance": 195})
        self.assertContains(resp, "RECOMMENDED")
        self.assertContains(resp, "Why this option?")
        self.assertContains(resp, "Indore")

    def test_page_shows_error_for_bad_distance(self):
        resp = self.client.get(reverse("comparison:compare"), {"distance": "-4"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "greater than 0")

    def test_api_ok(self):
        resp = self.client.get(reverse("comparison:api"), {"distance": 800, "priority": "fastest"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["recommended"]["mode"], "flight")
        self.assertTrue(data["reasons"])

    def test_api_error_is_400(self):
        resp = self.client.get(reverse("comparison:api"), {"distance": "abc"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_html_is_escaped(self):
        resp = self.client.get(reverse("comparison:compare"),
                               {"origin": "<script>x</script>", "distance": 10})
        self.assertNotContains(resp, "<script>x</script>")
