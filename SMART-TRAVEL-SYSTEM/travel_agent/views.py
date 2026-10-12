
import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .services import find_city, process_travel_request


def agent_home(request):
    context = {
        "travel_request": "",
        "response": None,
        "cities": [],
        "intent": None,
        "attractions": [],
        "hotels": [],
    }

    if request.method == "POST":
        message = request.POST.get("travel_request", "").strip()

        if message:
            result = process_travel_request(message)
            context.update({
                "travel_request": message,
                "response": result["message"],
                "cities": result["cities"],
                "hotels": result.get("hotels", []),
                "intent": result["intent"],
                "attractions": result["attractions"],
            })

    return render(request, "travel_agent/agent.html", context)


@require_GET
def city_api(request):
    name = request.GET.get("name", "").strip()

    if not name:
        return JsonResponse(
            {"error": "Please provide a city name."},
            status=400,
        )

    if len(name) > 100:
        return JsonResponse(
            {"error": "City name is too long."},
            status=400,
        )

    result = find_city(name)

    if result["found"]:
        return JsonResponse({
            "found": True,
            "city": result["city"],
        })

    return JsonResponse({
        "found": False,
        "message": "City not found.",
        "suggestions": result["suggestions"],
    }, status=404)


@csrf_exempt
@require_POST
def chat_api(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({
            "success": False,
            "error": "Invalid JSON.",
        }, status=400)

    if not isinstance(data, dict):
        return JsonResponse({
            "success": False,
            "error": "JSON must be an object.",
        }, status=400)

    message = data.get("message", "")

    if not isinstance(message, str) or not message.strip():
        return JsonResponse({
            "success": False,
            "error": "Please provide a message.",
        }, status=400)

    if len(message) > 1000:
        return JsonResponse({
            "success": False,
            "error": "Message must be under 1000 characters.",
        }, status=400)

    result = process_travel_request(message.strip())

    
    return JsonResponse({
    "success": result["success"],
    "intent": result["intent"],
    "source": result["source"],
    "destination": result["destination"],
    "hotels": result.get("hotels", []),
    "attractions": result.get("attractions", []),
    "message": result["message"],
})

