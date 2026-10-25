from django.test import TestCase
from django.contrib.auth import get_user_model


class AssistantRouteTests(TestCase):
    def test_authenticated_dashboard_assistant_redirects_to_travel_agent(self):
        user = get_user_model().objects.create_user(
            username="travel-user",
            password="test-password",
        )
        self.client.force_login(user)

        response = self.client.get("/assistant/")

        self.assertRedirects(response, "/agent/", fetch_redirect_response=True)

    def test_assistant_route_keeps_login_requirement(self):
        response = self.client.get("/assistant/")

        self.assertRedirects(response, "/login/?next=/assistant/")
