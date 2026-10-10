from django.shortcuts import render


def recommendations_home(request):
    recommendations = [
        {
            "title": "Bus Travel",
            "icon": "🚌",
            "description": "Explore bus travel options for your journey.",
            "features": [
                "Budget Friendly",
                "Multiple Routes",
                "Easy Travel",
            ],
        },
        {
            "title": "Train Travel",
            "icon": "🚆",
            "description": "Discover train travel options for comfortable journeys.",
            "features": [
                "Comfortable",
                "Long Distance",
                "Scenic Routes",
            ],
        },
        {
            "title": "Flight Travel",
            "icon": "✈️",
            "description": "Explore flight options to reach your destination faster.",
            "features": [
                "Time Saving",
                "Long Distance",
                "Fast Travel",
            ],
        },
        {
            "title": "Cab Travel",
            "icon": "🚕",
            "description": "Find convenient cab options for local and city travel.",
            "features": [
                "Flexible",
                "Door to Door",
                "Private Travel",
            ],
        },
    ]

    return render(
        request,
        "recommendations.html",
        {"recommendations": recommendations},
    )