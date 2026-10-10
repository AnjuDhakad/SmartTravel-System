"""
Comparison logic for the Smart Recommendation & Comparison module.

Pure Python (no Django imports) so it is easy to unit-test and to reuse from
the AI agent or from teammates' route code.

Pipeline:
    distance -> build_options()  (cost / time / CO2 / comfort per mode)
             -> score_options()  (min-max normalise + weighted score)
             -> recommend()      (best option + human-readable reasons)

All money is in INR, time in minutes, CO2 in kg. Numbers are rough
estimates for India and can be tuned in TRANSPORT_MODES.
"""
import math
from dataclasses import dataclass, field

CITY_THRESHOLD_KM = 30  # below this we use the slower "city" speed

# ---------------------------------------------------------------------------
# Configuration: tweak these numbers to change behaviour
# ---------------------------------------------------------------------------
TRANSPORT_MODES = {
    "walk": {
        "label": "Walking", "icon": "🚶",
        "speed_city": 5, "speed_highway": 5,
        "base_cost": 0, "cost_per_km": 0,
        "overhead_min": 0, "co2_g_per_km": 0, "comfort": 4,
        "min_km": 0, "max_km": 5, "per_vehicle": False,
    },
    "bike": {
        "label": "Bicycle", "icon": "🚴",
        "speed_city": 14, "speed_highway": 14,
        "base_cost": 0, "cost_per_km": 0,
        "overhead_min": 2, "co2_g_per_km": 0, "comfort": 5,
        "min_km": 0, "max_km": 20, "per_vehicle": False,
    },
    "bus": {
        "label": "Bus", "icon": "🚌",
        "speed_city": 20, "speed_highway": 45,
        "base_cost": 10, "cost_per_km": 1.8,
        "overhead_min": 20, "co2_g_per_km": 90, "comfort": 5,
        "min_km": 2, "max_km": 1200, "per_vehicle": False,
    },
    "train": {
        "label": "Train", "icon": "🚆",
        "speed_city": 30, "speed_highway": 60,
        "base_cost": 20, "cost_per_km": 1.5,
        "overhead_min": 45, "co2_g_per_km": 35, "comfort": 7,
        "min_km": 30, "max_km": 4000, "per_vehicle": False,
    },
    "car": {
        "label": "Car / Cab", "icon": "🚗",
        "speed_city": 25, "speed_highway": 60,
        "base_cost": 60, "cost_per_km": 13,
        "overhead_min": 8, "co2_g_per_km": 170, "comfort": 8,
        "min_km": 1, "max_km": 1500, "per_vehicle": True, "seats": 4,
    },
    "flight": {
        "label": "Flight", "icon": "✈️",
        "speed_city": 700, "speed_highway": 700,
        "base_cost": 1800, "cost_per_km": 4.5,
        "overhead_min": 180, "co2_g_per_km": 150, "comfort": 8,
        "min_km": 300, "max_km": 20000, "per_vehicle": False,
    },
}

# How much each criterion matters for each user priority (each row sums to 1)
PRIORITIES = {
    "balanced": {"label": "Balanced", "cost": 0.30, "time": 0.30, "co2": 0.15, "comfort": 0.25},
    "cheapest": {"label": "Cheapest", "cost": 0.70, "time": 0.10, "co2": 0.10, "comfort": 0.10},
    "fastest":  {"label": "Fastest",  "cost": 0.10, "time": 0.70, "co2": 0.05, "comfort": 0.15},
    "eco":      {"label": "Eco-friendly", "cost": 0.10, "time": 0.10, "co2": 0.70, "comfort": 0.10},
    "comfort":  {"label": "Most comfortable", "cost": 0.10, "time": 0.15, "co2": 0.05, "comfort": 0.70},
}

MAX_DISTANCE_KM = 20000
MAX_PASSENGERS = 20


class ComparisonError(ValueError):
    """Raised for invalid user input."""


@dataclass
class TransportOption:
    mode: str
    label: str
    icon: str
    cost: float            # total INR for the whole group
    time_min: int          # door-to-door minutes
    co2_kg: float          # total kg CO2 for the whole group
    comfort: int           # 1-10
    score: float = 0.0     # 0-100, filled by score_options()
    badges: list = field(default_factory=list)

    @property
    def time_display(self):
        h, m = divmod(self.time_min, 60)
        if h and m:
            return f"{h}h {m}m"
        return f"{h}h" if h else f"{m}m"

    def as_dict(self):
        return {
            "mode": self.mode, "label": self.label, "icon": self.icon,
            "cost": round(self.cost), "time_min": self.time_min,
            "time_display": self.time_display, "co2_kg": round(self.co2_kg, 2),
            "comfort": self.comfort, "score": round(self.score, 1),
            "badges": self.badges,
        }


@dataclass
class Recommendation:
    best: TransportOption
    reasons: list
    options: list           # all options, sorted best -> worst
    priority: str
    distance_km: float
    passengers: int

    def as_dict(self):
        return {
            "distance_km": self.distance_km, "passengers": self.passengers,
            "priority": self.priority,
            "recommended": self.best.as_dict(), "reasons": self.reasons,
            "options": [o.as_dict() for o in self.options],
        }


# ---------------------------------------------------------------------------
# Step 0: validation
# ---------------------------------------------------------------------------
def validate_inputs(distance_km, priority="balanced", passengers=1):
    try:
        distance_km = float(distance_km)
    except (TypeError, ValueError):
        raise ComparisonError("Distance must be a number.")
    if math.isnan(distance_km) or math.isinf(distance_km) or distance_km <= 0:
        raise ComparisonError("Distance must be greater than 0 km.")
    if distance_km > MAX_DISTANCE_KM:
        raise ComparisonError(f"Distance cannot exceed {MAX_DISTANCE_KM} km.")
    try:
        passengers = int(passengers)
    except (TypeError, ValueError):
        raise ComparisonError("Passengers must be a whole number.")
    if not 1 <= passengers <= MAX_PASSENGERS:
        raise ComparisonError(f"Passengers must be between 1 and {MAX_PASSENGERS}.")
    if priority not in PRIORITIES:
        raise ComparisonError(f"Unknown priority '{priority}'.")
    return distance_km, priority, passengers


# ---------------------------------------------------------------------------
# Step 1: build the options for a route
# ---------------------------------------------------------------------------
def build_options(distance_km, passengers=1):
    """Return a TransportOption for every mode that is realistic for this distance."""
    options = []
    for mode, c in TRANSPORT_MODES.items():
        if not c["min_km"] <= distance_km <= c["max_km"]:
            continue
        speed = c["speed_city"] if distance_km < CITY_THRESHOLD_KM else c["speed_highway"]
        time_min = round(c["overhead_min"] + distance_km / speed * 60)

        unit_cost = c["base_cost"] + c["cost_per_km"] * distance_km
        unit_co2 = c["co2_g_per_km"] * distance_km / 1000
        # Cars are shared: one vehicle per 4 people. Others are paid per person.
        units = math.ceil(passengers / c.get("seats", 1)) if c["per_vehicle"] else passengers

        options.append(TransportOption(
            mode=mode, label=c["label"], icon=c["icon"],
            cost=unit_cost * units, time_min=time_min,
            co2_kg=unit_co2 * units, comfort=c["comfort"],
        ))
    return options


# ---------------------------------------------------------------------------
# Step 2: score the options
# ---------------------------------------------------------------------------
def _normalise(value, lo, hi, higher_is_better):
    """Map value to 0..1 where 1 is best. If all options tie, everyone gets 1."""
    if hi == lo:
        return 1.0
    ratio = (value - lo) / (hi - lo)
    return ratio if higher_is_better else 1 - ratio


def score_options(options, priority="balanced"):
    """Fill .score (0-100) and .badges on each option; return sorted best-first."""
    if not options:
        return []
    w = PRIORITIES[priority]
    costs = [o.cost for o in options]
    times = [o.time_min for o in options]
    co2s = [o.co2_kg for o in options]
    comforts = [o.comfort for o in options]

    for o in options:
        s = (
            w["cost"] * _normalise(o.cost, min(costs), max(costs), False)
            + w["time"] * _normalise(o.time_min, min(times), max(times), False)
            + w["co2"] * _normalise(o.co2_kg, min(co2s), max(co2s), False)
            + w["comfort"] * _normalise(o.comfort, min(comforts), max(comforts), True)
        )
        o.score = s * 100

    if len(options) > 1:  # badges are meaningless with a single option
        min(options, key=lambda o: o.cost).badges.append("Cheapest")
        min(options, key=lambda o: o.time_min).badges.append("Fastest")
        min(options, key=lambda o: o.co2_kg).badges.append("Greenest")
        max(options, key=lambda o: o.comfort).badges.append("Most comfortable")

    # ties broken by lower cost, then shorter time -> deterministic results
    return sorted(options, key=lambda o: (-o.score, o.cost, o.time_min))


# ---------------------------------------------------------------------------
# Step 3: explain the recommendation
# ---------------------------------------------------------------------------
def build_reasons(best, options, priority, distance_km):
    reasons = []
    others = [o for o in options if o is not best]
    pr_label = PRIORITIES[priority]["label"].lower()
    reasons.append(
        f"Best overall match for your '{pr_label}' priority "
        f"(score {best.score:.0f}/100)."
    )
    if not others:
        reasons.append(f"It is the only realistic option for {distance_km:g} km.")
        return reasons

    if best.cost == min(o.cost for o in options):
        reasons.append("Lowest total cost of all options.")
    else:
        cheapest = min(others, key=lambda o: o.cost)
        diff = best.cost - cheapest.cost
        reasons.append(f"Costs ₹{diff:,.0f} more than {cheapest.label}, but wins on other factors.")

    if best.time_min == min(o.time_min for o in options):
        reasons.append("Fastest door-to-door, including waiting and boarding time.")
    else:
        slowest = max(others, key=lambda o: o.time_min)
        if best.time_min < slowest.time_min:
            saved = slowest.time_min - best.time_min
            h, m = divmod(saved, 60)
            reasons.append(f"Saves {f'{h}h ' if h else ''}{m}m compared with {slowest.label}.")

    if best.co2_kg == 0:
        reasons.append("Zero carbon emissions.")
    elif best.co2_kg == min(o.co2_kg for o in options):
        reasons.append("Lowest carbon footprint of all options.")
    else:
        worst = max(others, key=lambda o: o.co2_kg)
        if best.co2_kg < worst.co2_kg:
            reasons.append(f"Emits {worst.co2_kg - best.co2_kg:.1f} kg less CO₂ than {worst.label}.")

    if best.comfort >= 8:
        reasons.append("High comfort level for this trip.")
    return reasons


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def recommend(distance_km, priority="balanced", passengers=1):
    distance_km, priority, passengers = validate_inputs(distance_km, priority, passengers)
    options = build_options(distance_km, passengers)
    ranked = score_options(options, priority)
    if not ranked:
        raise ComparisonError("No transport options available for this route.")
    best = ranked[0]
    return Recommendation(
        best=best, reasons=build_reasons(best, ranked, priority, distance_km),
        options=ranked, priority=priority,
        distance_km=distance_km, passengers=passengers,
    )
