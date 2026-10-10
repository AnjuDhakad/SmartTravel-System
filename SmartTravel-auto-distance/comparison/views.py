from django.http import JsonResponse
from django.shortcuts import render

from .distance import DistanceError, get_route_distance
from .services import PRIORITIES, ComparisonError, recommend


def _read_params(request):
    return {
        "origin": request.GET.get("origin", "").strip(),
        "destination": request.GET.get("destination", "").strip(),
        "distance": request.GET.get("distance", "").strip(),  # optional manual override
        "passengers": request.GET.get("passengers", "1").strip() or "1",
        "priority": request.GET.get("priority", "balanced").strip() or "balanced",
    }


def _resolve_distance(params):
    """
    Returns (distance_km, info). A manually typed distance wins; otherwise the
    distance is looked up automatically from the origin and destination.
    info is a RouteDistance for automatic lookups, or None for manual input.
    """
    if params["distance"]:
        return params["distance"], None
    info = get_route_distance(params["origin"], params["destination"])
    return info.km, info


def compare_transport(request):
    """Compare Transport Options page. Results show once a route is submitted."""
    params = _read_params(request)
    context = {"params": params, "priorities": PRIORITIES,
               "result": None, "error": None, "distance_info": None}

    if params["origin"] or params["destination"] or params["distance"]:
        try:
            distance, info = _resolve_distance(params)
            context["distance_info"] = info
            context["result"] = recommend(distance, params["priority"], params["passengers"])
        except (ComparisonError, DistanceError) as exc:
            context["error"] = str(exc)
    return render(request, "comparison/compare.html", context)


def compare_api(request):
    """JSON version: /compare/api/?origin=Indore&destination=Bhopal  (or ?distance=195)"""
    params = _read_params(request)
    try:
        distance, info = _resolve_distance(params)
        result = recommend(distance, params["priority"], params["passengers"])
    except (ComparisonError, DistanceError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    data = result.as_dict()
    data.update(origin=params["origin"], destination=params["destination"],
                distance_source=info.source if info else "manual")
    return JsonResponse(data)
