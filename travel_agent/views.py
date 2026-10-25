
import json

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .services import find_city, process_travel_request


def _process_chat_message(request, message):
    result = process_travel_request(
        message,
        previous_city=request.session.get("travel_agent_city"),
    )

    if result["context_city"]:
        request.session["travel_agent_city"] = result["context_city"]

    conversation = request.session.get("travel_agent_conversation", [])
    conversation.append({
        "message": message,
        "response": result["message"],
        "cities": result["cities"],
        "attractions": result["attractions"],
        "hotels": result["hotels"],
        "route": result["route"],
    })
    request.session["travel_agent_conversation"] = conversation[-20:]
    request.session.modified = True
    return result


def agent_home(request):
    if request.GET.get("new") == "1":
        request.session.pop("travel_agent_city", None)
        request.session.pop("travel_agent_conversation", None)
        return redirect(request.path)

    context = {
        "conversation": request.session.get("travel_agent_conversation", []),
    }

    if request.method == "POST":
        message = request.POST.get("travel_request", "").strip()

        if message:
            _process_chat_message(request, message)
            context["conversation"] = request.session[
                "travel_agent_conversation"
            ]

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

    result = _process_chat_message(request, message.strip())

    return JsonResponse({
        "success": result["success"],
        "intent": result["intent"],
        "source": result["source"],
        "destination": result["destination"],
        "context_city": result["context_city"],
        "cities": result["cities"],
        "hotels": result["hotels"],
        "attractions": result["attractions"],
        "route": result["route"],
        "message": result["message"],
    })
