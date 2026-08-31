import math
import os
from datetime import datetime, timedelta
from decimal import Decimal

import pyodbc
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv(dotenv_path=".env")
app = Flask(__name__)

def connection():
    return pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.getenv('SQL_SERVER', 'localhost,1433')};"
        f"DATABASE={os.getenv('SQL_DATABASE', 'cruise_learning')};"
        f"UID={os.getenv('SQL_USER', 'sa')};"
        f"PWD={os.environ['SQL_PASSWORD']};"
        "Encrypt=yes;TrustServerCertificate=yes"
    )

def clean(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value

def rows(sql, params=()):
    with connection() as cn:
        cursor = cn.cursor()
        cursor.execute(sql, params)
        names = [column[0] for column in cursor.description]
        return [
            {key: clean(value) for key, value in zip(names, row)}
            for row in cursor.fetchall()
        ]

def haversine_nm(point_a, point_b):
    lat1 = math.radians(point_a["latitude"])
    lon1 = math.radians(point_a["longitude"])
    lat2 = math.radians(point_b["latitude"])
    lon2 = math.radians(point_b["longitude"])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = (math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 3440.065 * 2 * math.asin(math.sqrt(h))

def load_seasonality():
    seasonality_rows = rows(
        """
        SELECT month_number, month_label, season_label, spend_multiplier
        FROM dbo.seasonality
        """
    )
    return {item["month_number"]: item for item in seasonality_rows}

def apply_port_economics(day, ship, seasonality_index):
    """Attach modeled port-fee and seasonality-adjusted guest-spend figures
    to a port-call day. Home ports / one-way endpoints carry $0 for both
    (embark/disembark days, not a shore-excursion day)."""
    call_date = datetime.strptime(day["date"], "%Y-%m-%d").date()
    season = seasonality_index.get(call_date.month, {
        "month_label": call_date.strftime("%b"),
        "season_label": "Unmodeled month",
        "spend_multiplier": 1.0
    })
    base_spend = float(day.get("model_avg_guest_spend_usd") or 0)
    port_fee = float(day.get("model_port_fee_usd") or 0)
    multiplier = float(season["spend_multiplier"])
    adjusted_spend_per_guest = round(base_spend * multiplier, 2)
    guests = ship["double_occupancy_guests"]
    day["season_month_label"] = season["month_label"]
    day["season_label"] = season["season_label"]
    day["seasonality_multiplier"] = multiplier
    day["model_port_fee_usd"] = round(port_fee, 2)
    day["adjusted_guest_spend_per_guest"] = adjusted_spend_per_guest
    day["total_modeled_guest_spend"] = round(adjusted_spend_per_guest * guests)
    day["total_modeled_port_fee"] = round(port_fee * guests)
    return day

def load_schedule_index():
    scheduled = rows(
        """
        SELECT
            x.port_id,
            CONVERT(varchar(10), x.call_date, 23) AS call_date,
            COUNT(*) AS calls,
            COALESCE(SUM(s.double_occupancy_guests), 0) AS guests
        FROM dbo.sample_schedule x
        JOIN dbo.ships s ON s.ship_id = x.ship_id
        GROUP BY x.port_id, x.call_date
        """
    )
    return {
        (item["port_id"], item["call_date"]): item
        for item in scheduled
    }

def load_route_days(route_id, start_date, ship, schedule_index, seasonality_index):
    route_rows = rows(
        """
        SELECT
            rs.day_number,
            rs.arrival_time,
            rs.departure_time,
            p.port_id,
            p.port_name,
            p.country,
            p.latitude,
            p.longitude,
            p.homeport_flag,
            p.private_destination_flag,
            p.model_daily_ship_limit,
            p.model_daily_guest_limit,
            p.max_draft_m,
            p.draft_status,
            p.model_port_cost_index,
            p.model_guest_rating,
            p.model_experience_score,
            p.model_port_fee_usd,
            p.model_avg_guest_spend_usd,
            spe.evidence_status AS port_evidence_status,
            spe.evidence_note
        FROM dbo.route_stops rs
        LEFT JOIN dbo.ports p ON p.port_id = rs.port_id
        LEFT JOIN dbo.ship_port_evidence spe
            ON spe.ship_id = ?
           AND spe.port_id = p.port_id
        WHERE rs.route_id = ?
        ORDER BY rs.day_number
        """,
        (ship["ship_id"], route_id)
    )
    days= []
    conflicts= []
    for item in route_rows:
        day_number = item["day_number"]
        item["date"] = (start_date + timedelta(days=day_number)).isoformat()
        if not item.get("port_id"):
            item.update(
                port_name="Day at Sea",
                status="sea",
                reason="Sailing time and onboard guest-experience day"
            )
            days.append(item)
            continue
        apply_port_economics(item, ship, seasonality_index)
        existing = schedule_index.get(
            (item["port_id"], item["date"]),
            {"calls": 0, "guests": 0}
        )
        projected_calls = existing["calls"] + 1
        projected_guests = (existing["guests"] + ship["double_occupancy_guests"])
        reasons= []
        if item["port_evidence_status"] not in {"VERIFIED", "SAMPLE"}:
            reasons.append("no ship-port evidence")
        if ship["draft_m"] > item["max_draft_m"]:
            reasons.append("modeled draft clearance")
        if projected_calls > item["model_daily_ship_limit"]:
            reasons.append("modeled ship-slot limit")
        if projected_guests > item["model_daily_guest_limit"]:
            reasons.append("modeled guest-volume limit")
        if reasons:
            item["status"] = "conflict"
            item["reason"] = "Fails: " + ", ".join(reasons)
            conflicts.append(f"{item['port_name']} on {item['date']}")
        else:
            item["status"] = "feasible"
            if item["port_evidence_status"] == "VERIFIED":
                item["reason"] = (
                    "Observed on a published Royal Caribbean itinerary; "
                    "modeled capacity passed"
                )
            else:
                item["reason"] = ("Sample ship-port case; modeled draft and capacity screen passed")
        item["projected_calls"] = projected_calls
        item["projected_guests"] = projected_guests
        days.append(item)
    return days, conflicts

def schedule_sample_route(home, ordered_ports, nights, start_date):
    modeled_nm_per_day = 390
    available_sea_days = nights - 1 - len(ordered_ports)
    if available_sea_days < 0:
        return None
    points = [home] + ordered_ports + [home]
    legs = list(zip(points[:-1], points[1:]))
    leg_distances = [haversine_nm(a, b) for a, b in legs]
    required_sea_days = [
        max(0, math.ceil(distance / modeled_nm_per_day) - 1)
        for distance in leg_distances
    ]
    if sum(required_sea_days) > available_sea_days:
        return None
    extra_sea_days = [0] * len(legs)
    longest_first = sorted(
        range(len(legs)),
        key=lambda index: leg_distances[index],
        reverse=True
    )
    extras = available_sea_days - sum(required_sea_days)
    for index in range(extras):
        extra_sea_days[longest_first[index % len(longest_first)]] += 1
    days = [{
        "day_number": 0,
        "date": start_date.isoformat(),
        **home
    }]
    day_number = 0
    for index, port in enumerate(ordered_ports):
        transit_days = required_sea_days[index] + extra_sea_days[index]
        for _ in range(transit_days):
            day_number += 1
            days.append({
                "day_number": day_number,
                "date": (start_date + timedelta(days=day_number)).isoformat(),
                "port_id": None,
                "port_name": "Day at Sea",
                "latitude": None,
                "longitude": None
            })
        day_number += 1
        days.append({
            "day_number": day_number,
            "date": (start_date + timedelta(days=day_number)).isoformat(),
            **port
        })
    final_transit_days = required_sea_days[-1] + extra_sea_days[-1]
    for _ in range(final_transit_days):
        day_number += 1
        days.append({
            "day_number": day_number,
            "date": (start_date + timedelta(days=day_number)).isoformat(),
            "port_id": None,
            "port_name": "Day at Sea",
            "latitude": None,
            "longitude": None
        })
    day_number += 1
    days.append({
        "day_number": day_number,
        "date": (start_date + timedelta(days=day_number)).isoformat(),
        **home
    })
    return days if day_number == nights else None

def screen_sample_days(days, ship, schedule_index, evidence_map, seasonality_index):
    conflicts = []
    for day in days:
        if not day.get("port_id"):
            day.update(
                status="sea",
                reason="Modeled sailing time between ports"
            )
            continue
        evidence = evidence_map.get(day["port_id"])
        day["port_evidence_status"] = (
            evidence["evidence_status"] if evidence else "SAMPLE"
        )
        day["evidence_note"] = (
            evidence["evidence_note"]
            if evidence
            else "Sample ship-port pairing for interview analysis"
        )
        apply_port_economics(day, ship, seasonality_index)
        existing = schedule_index.get(
            (day["port_id"], day["date"]),
            {"calls": 0, "guests": 0}
        )
        projected_calls = existing["calls"] + 1
        projected_guests = (
            existing["guests"] + ship["double_occupancy_guests"]
        )
        reasons = []
        if ship["draft_m"] > day["max_draft_m"]:
            reasons.append("modeled draft clearance")
        if projected_calls > day["model_daily_ship_limit"]:
            reasons.append("modeled ship-slot limit")
        if projected_guests > day["model_daily_guest_limit"]:
            reasons.append("modeled guest-volume limit")
        if reasons:
            day["status"] = "conflict"
            day["reason"] = "Fails: " + ", ".join(reasons)
            conflicts.append(f"{day['port_name']} on {day['date']}")
        else:
            day["status"] = "feasible"
            day["reason"] = (
                "Published ship-port pairing; modeled capacity screen passed"
                if day["port_evidence_status"] == "VERIFIED"
                else "Sample pairing; modeled draft and capacity screen passed"
            )
        day["projected_calls"] = projected_calls
        day["projected_guests"] = projected_guests
    return conflicts

def build_sample_candidates(
    ship, nights, start_date, objective, schedule_index, seasonality_index
):
    blueprints = {
        3: [
            ["PCC", "NAS"],
            ["NAS", "PCC"]
        ],
        5: [
            ["PCC", "GDT"],
            ["NAS", "CZM"],
            ["PCC", "NAS"]
        ],
        7: [
            ["PCC", "SJU", "STT"],
            ["CMM", "RTB", "CZM", "PCC"],
            ["NAS", "GCM", "FMT"]
        ],
        9: [
            ["PCC", "CBJ", "CUR", "AUA"],
            ["BIM", "CBJ", "AUA", "CUR"],
            ["ANU", "BGI", "SKB", "SXM"]
        ],
        12: [
            ["PCC", "SJU", "STT", "SKB", "SXM"],
            ["CMM", "RTB", "CZM", "AUA", "CUR"],
            ["NAS", "GDT", "POP", "SJU", "PCC"]
        ]
    }
    port_rows = rows("SELECT * FROM dbo.ports")
    port_map = {port["port_id"]: port for port in port_rows}
    home = port_map["MIA"]
    evidence_rows = rows(
        """
        SELECT port_id, evidence_status, evidence_note
        FROM dbo.ship_port_evidence
        WHERE ship_id = ?
        """,
        (ship["ship_id"],)
    )
    evidence_map = {item["port_id"]: item for item in evidence_rows}
    candidates = []
    for index, port_ids in enumerate(blueprints[nights], 1):
        ordered_ports = [
            port_map[port_id]
            for port_id in port_ids
            if (
                port_id in port_map
                and ship["draft_m"] <= port_map[port_id]["max_draft_m"]
            )
        ]
        if len(ordered_ports) != len(port_ids):
            continue
        days = schedule_sample_route(home, ordered_ports, nights, start_date)
        if not days:
            continue
        conflicts = screen_sample_days(days, ship, schedule_index, evidence_map, seasonality_index)

        port_sequence = " · ".join(port["port_name"].split(",")[0] for port in ordered_ports)
        candidates.append({
            "route_id": f"SAMPLE-{ship['ship_id']}-{nights}-{index}",
            "route_name": (
                f"{ship['ship_name']}: {nights}-night sample — {port_sequence}"
            ),
            "cruise_type": f"{nights} NIGHT",
            "nights": nights,
            "region": "Modeled Miami scenario",
            "evidence_status": "SAMPLE",
            "source_id": "SRC_MODEL",
            "sailing_type": "ROUNDTRIP",
            "destination": "Miami, Florida",
            "days": days,
            "metrics": score_route(days, objective, conflicts, ship)
        })
    return candidates

def score_route(days, objective, conflicts, ship):
    port_days = [
        day for day in days
        if day.get("port_id") and not day.get("homeport_flag")
    ]
    route_points = [day for day in days if day.get("port_id")]
    leg_distances = [
        haversine_nm(route_points[index], route_points[index + 1])
        for index in range(len(route_points) - 1)
    ]
    distance = sum(leg_distances)
    rating = sum(day["model_guest_rating"] for day in port_days) / len(port_days)
    port_experience = (sum(day["model_experience_score"] for day in port_days) / len(port_days))
    cost = sum(day["model_port_cost_index"] for day in port_days) / len(port_days)
    distance_efficiency = max(0, 100 - distance / 35)
    ship_size_score = float(ship["model_size_experience_score"])
    blended_experience = round(port_experience * 0.65 + (ship_size_score * 20) * 0.35, 1)
    total_fee_per_guest = sum(float(day.get("model_port_fee_usd") or 0) for day in port_days)
    average_spend_per_day = (
        sum(float(day.get("adjusted_guest_spend_per_guest") or 0) for day in port_days) / len(port_days))
    total_guest_spend = sum(
        day.get("total_modeled_guest_spend") or 0 for day in port_days)
    total_port_fees = sum(day.get("total_modeled_port_fee") or 0 for day in port_days)
    fee_efficiency = max(0, 100 - total_fee_per_guest)
    cost_efficiency = round((100 - cost) * 0.5 + fee_efficiency * 0.5, 1)
    spend_efficiency = round(min(100, average_spend_per_day / 2.3), 1)
    weights = {
        "balanced": (0.25, 0.20, 0.20, 0.15, 0.20),
        "guest":    (0.35, 0.30, 0.05, 0.10, 0.20),
        "cost":     (0.15, 0.10, 0.40, 0.15, 0.20),
        "distance": (0.15, 0.10, 0.10, 0.50, 0.15)
    }[objective]
    score = (
        rating * 20 * weights[0]
        + blended_experience * weights[1]
        + cost_efficiency * weights[2]
        + distance_efficiency * weights[3]
        + spend_efficiency * weights[4]
        - len(conflicts) * 35
    )
    return {
        "score": round(score, 1),
        "distance_nm": round(distance),
        "max_leg_nm": round(max(leg_distances) if leg_distances else 0),
        "modeled_sailing_hours": round(distance / 18),
        "average_guest_rating": round(rating, 2),
        "average_experience_score": round(port_experience, 1),
        "ship_size_experience_score": ship_size_score,
        "blended_experience_score": blended_experience,
        "average_port_cost_index": round(cost, 1),
        "cost_efficiency": cost_efficiency,
        "average_guest_spend_per_day": round(average_spend_per_day, 2),
        "total_modeled_guest_spend": round(total_guest_spend),
        "total_modeled_port_fees": round(total_port_fees),
        "spend_efficiency": spend_efficiency,
        "sea_days": sum(1 for day in days if not day.get("port_id")),
        "port_calls": len(port_days),
        "conflicts": conflicts
    }

def deterministic_recommendation(candidates, objective):
    best = candidates[0]
    best_metrics = best["metrics"]
    lines = [
        (
            f"Best match: {best['route_name']} scores "
            f"{best_metrics['score']}/100 for the {objective} objective."
        ),
        (
            "Sailing pattern: Miami roundtrip."
            if best["sailing_type"] == "ROUNDTRIP"
            else f"Sailing pattern: one-way from Miami to {best['destination']}."
        ),
        (
            f"It includes {best_metrics['port_calls']} port calls and "
            f"{best_metrics['sea_days']} sea days across approximately "
            f"{best_metrics['distance_nm']:,} nautical miles."
        ),
        (
            f"Modeled averages: guest rating "
            f"{best_metrics['average_guest_rating']}/5, blended experience "
            f"{best_metrics['blended_experience_score']}/100 (ship-size score "
            f"{best_metrics['ship_size_experience_score']}/5) and port-cost "
            f"index {best_metrics['average_port_cost_index']}/100."
        ),
        (
            f"Modeled economics: about ${best_metrics['average_guest_spend_per_day']:,.0f} "
            f"seasonally adjusted guest spend per person per port day, "
            f"~${best_metrics['total_modeled_guest_spend']:,} total guest spend "
            f"and ~${best_metrics['total_modeled_port_fees']:,} in port fees "
            f"across the sailing."
        )
    ]
    if len(candidates) > 1:
        alternative = candidates[1]
        lines.append(
            f"Alternative: {alternative['route_name']} scores "
            f"{alternative['metrics']['score']}/100."
        )
    if best["evidence_status"] == "SAMPLE":
        lines.append("This option is a sample planning case, not a published operating schedule.")
    else:
        lines.append("The route pattern is supported by a published Royal Caribbean itinerary.")
    return "\n".join(lines)

def explain_with_gemini(ship, nights, candidates, objective):
    fallback = deterministic_recommendation(candidates, objective)
    if not os.getenv("GEMINI_API_KEY"):
        return fallback, False
    client = None
    try:
        from google import genai
        comparison = [
            {
                "option": index + 1,
                "route": candidate["route_name"],
                "evidence": candidate["evidence_status"],
                "sailing_type": candidate["sailing_type"],
                "destination": candidate["destination"],
                "metrics": candidate["metrics"],
                "ports": [
                    day["port_name"]
                    for day in candidate["days"]
                    if day.get("port_id") and not day.get("homeport_flag")
                ]
            }
            for index, candidate in enumerate(candidates)
        ]
        prompt = f"""
        You are explaining a small cruise deployment-planning portfolio prototype.
        Compare these already-screened, already-ranked {nights}-night Miami options
        for {ship['ship_name']}. The objective is {objective}. Option 1 is the
        top-ranked candidate; treat it as the recommendation unless its conflict
        count is clearly worse than another option's.
        Each candidate's "metrics" include: score (0-100, higher is better),
        average_guest_rating (0-5), average_experience_score and
        blended_experience_score (0-100, the latter folds in this ship's
        model_size_experience_score for onboard variety), average_port_cost_index
        (0-100, higher = pricier to operate), average_guest_spend_per_day (modeled
        USD per guest, already adjusted for that call's seasonality month),
        total_modeled_guest_spend and total_modeled_port_fees (modeled USD totals
        for the whole sailing), distance_nm, sea_days, and conflicts (a list of
        screening failures - any non-empty list is disqualifying).
        Use only the supplied data. Guest ratings, cost index, port fees, guest
        spend, seasonality multipliers, daily capacity and non-Miami clearance
        figures are MODELED interview assumptions, not real Royal Caribbean pricing
        or revenue. VERIFIED means the route pattern appears on a public Royal
        Caribbean itinerary. SAMPLE means it is only a demonstration case. Do not
        invent prices, revenue, berth approval or live availability, and do not
        recommend an option that has conflicts if a conflict-free option exists.
        Write four short labeled lines:
        Recommendation:
        Why:
        Alternative:
        Important limitation:
        Candidate data: {comparison}
        """
        client = genai.Client()
        result = client.models.generate_content( model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"), contents=prompt)
        text = (result.text or "").strip()
        if not text:
            raise ValueError("Empty response from Gemini")
        return text, True
    except Exception as exc:
        app.logger.warning("Gemini call failed: %r", exc)
        return (
            fallback
            + "\n Showing the deterministic comparison instead of AI-generated explanation",
            False
        )
    finally:
        if client is not None:
            client.close()

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/setup")
def setup():
    ships = rows(
        """
        SELECT ship_id, ship_name, ship_class, service_year, gross_tonnage,
               double_occupancy_guests, crew, passenger_decks, draft_m,
               draft_status, model_size_experience_score
        FROM dbo.ships
        WHERE miami_scope_flag = 1
        ORDER BY
            CASE ship_id
                WHEN 'WONDER' THEN 1
                WHEN 'ALLURE' THEN 2
                WHEN 'FREEDOM' THEN 3
                WHEN 'INDEP' THEN 4
                WHEN 'ICON' THEN 5
                WHEN 'HERO' THEN 6
                ELSE 7
            END
        """
    )
    cruise_types = {
        3: "WEEKEND",
        5: "4-5 NIGHT",
        7: "7 NIGHT",
        9: "9 NIGHT",
        12: "12 NIGHT"
    }
    programs = [
        {
            "ship_id": ship["ship_id"],
            "cruise_type": cruise_types[nights],
            "nights": nights
        }
        for ship in ships
        for nights in (3, 5, 7, 9, 12)
    ]
    return jsonify(
        {
            "ships": ships,
            "programs": programs,
            "sources": rows(
                """
                SELECT source_id, source_title, publisher, source_url,
                       fact_type, accessed_date
                FROM dbo.sources
                ORDER BY fact_type, source_id
                """
            ),
            "seasonality": rows(
                """
                SELECT month_number, month_label, season_label, spend_multiplier
                FROM dbo.seasonality
                ORDER BY month_number
                """
            )
        }
    )

@app.get("/api/generate-plan")
def generate_plan():
    ship_id = request.args.get("ship_id", "WONDER")
    objective = request.args.get("objective", "balanced")
    if objective not in {"balanced", "guest", "cost", "distance"}:
        objective = "balanced"
    try:
        nights = int(request.args.get("nights", 3))
        start_date = datetime.strptime(
            request.args.get("start", datetime.now().date().isoformat()),
            "%Y-%m-%d"
        ).date()
    except ValueError:
        return jsonify({"error": "Use a valid departure date and cruise length."}), 400
    if nights not in {3, 5, 7, 9, 12}:
        return jsonify({"error": "Choose 3, 5, 7, 9 or 12 nights."}), 400
    ship_matches = rows(
        "SELECT TOP 1 * FROM dbo.ships WHERE ship_id = ? AND miami_scope_flag = 1",
        (ship_id,)
    )
    if not ship_matches:
        return jsonify({"error": "Choose a ship in the Miami prototype."}), 404
    ship = ship_matches[0]
    templates = rows(
        """
        SELECT route_id, route_name, cruise_type, nights, region,
               evidence_status, source_id
        FROM dbo.route_templates
        WHERE ship_id = ? AND nights = ?
        ORDER BY
            CASE evidence_status WHEN 'VERIFIED' THEN 0 ELSE 1 END,
            route_name
        """,
        (ship_id, nights)
    )
    schedule_index = load_schedule_index()
    seasonality_index = load_seasonality()
    candidates = []
    for template in templates:
        days, conflicts = load_route_days(
            template["route_id"], start_date, ship, schedule_index, seasonality_index
        )
        destination = days[-1]["port_name"]
        sailing_type = (
            "ROUNDTRIP"
            if days[-1].get("port_id") == "MIA"
            else "ONE-WAY"
        )
        candidates.append(
            {
                **template,
                "sailing_type": sailing_type,
                "destination": destination,
                "days": days,
                "metrics": score_route(days, objective, conflicts, ship)
            }
        )
    if not candidates:
        candidates = build_sample_candidates(
            ship, nights, start_date, objective, schedule_index, seasonality_index
        )
    if not candidates:
        return jsonify({
            "error": (
                "No route passes the modeled travel-time and port-fit "
                "constraints for this combination."
            )
        }), 422
    candidates.sort(
        key=lambda candidate: (
            len(candidate["metrics"]["conflicts"]),
            0 if candidate["evidence_status"] == "VERIFIED" else 1,
            -candidate["metrics"]["score"]
        )
    )
    top = candidates[:3]
    recommendation, ai_used = explain_with_gemini(
        ship, nights, top, objective
    )
    return jsonify(
        {
            "ship": ship,
            "ship": ship,
            "nights": nights,
            "cruise_type": top[0]["cruise_type"],
            "objective": objective,
            "candidates": top,
            "recommendation": recommendation,
            "ai_used": ai_used,
            "assumption_note": (
                "Routes are based on Royal Caribbean’s public itineraries. "
                "Port costs, guest ratings, daily capacity, and port clearance "
                "outside Miami are estimates created for this prototype."
            )
        }
    )
if __name__ == "__main__":
    app.run(host="127.0.0.1", debug=True, port=5050)