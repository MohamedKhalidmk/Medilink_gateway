"""
AutoRec node for doctor recommendation.

Why this module exists
----------------------
AutoRec is the gateway's booking recommendation branch. When the user's intent
is classified as ``booking``, this node calls the AutoRec service to retrieve
personalized doctor recommendations based on the user's query, location, budget,
and historical interactions.

Pipeline trace
--------------
  1. intent_router.py chooses route ``booking`` and writes booking_query.

  2. graph.py sends the shared MediLinkState to this node.

  3. this node calls the AutoRec service through clients.call_autorec().

  4. this node writes:
       autorec_result = recommendation results from AutoRec
       final_answer   = formatted recommendation text (if agent_node is skipped)

  5. graph.py sends state to agent_node for booking automation.

Important boundary
------------------
This node does not book appointments. It only retrieves doctor recommendations
that agent_node.py can then act on.
"""

from __future__ import annotations

import logging
from typing import Any

from app import clients
from app.state import MediLinkState

logger = logging.getLogger("medilink.gateway")


def _format_recommendations(results: list[dict[str, Any]]) -> str:
    """Render AutoRec recommendations into readable text for the user."""
    if not results:
        return "No doctor recommendations were found matching your criteria."

    lines = ["Here are the top doctor recommendations:\n"]
    for i, doc in enumerate(results, 1):
        name = doc.get("doctor_name", doc.get("name", "Unknown Doctor"))
        specialty = doc.get("specialty", "")
        area = doc.get("area", "")
        fee = doc.get("fee_egp", doc.get("fee", ""))
        rating = doc.get("overall_rating", doc.get("rating", ""))
        wait = doc.get("wait_time_minutes", doc.get("wait_time", ""))
        url = doc.get("vezeeta_url", doc.get("url", ""))

        line = f"{i}. **{name}**"
        if specialty:
            line += f" — {specialty}"
        details = []
        if area:
            details.append(f"📍 {area}")
        if fee:
            details.append(f"💰 {fee} EGP")
        if rating:
            details.append(f"⭐ {rating}")
        if wait:
            details.append(f"⏱️ ~{wait} min wait")
        if details:
            line += f"\n   {' | '.join(details)}"
        if url:
            line += f"\n   🔗 {url}"
        lines.append(line)

    return "\n".join(lines)


def autorec_node(state: MediLinkState) -> dict:
    """
    LangGraph node entry point.

    Reads:
      user_message, booking_query, user_id

    Writes:
      autorec_result, and error on recoverable failures
    """
    query = (state.get("booking_query") or state.get("user_message") or "").strip()
    user_id = state.get("user_id")

    if not query:
        return {
            "error": "autorec_node: no booking query available.",
            "autorec_result": None,
        }

    try:
        result = clients.call_autorec(
            query,
            user_id=user_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("AutoRec service call failed")
        return {
            "error": f"AutoRec service error: {exc}",
            "autorec_result": None,
        }

    recommendations = result.get("results", [])

    return {
        "autorec_result": {
            "query": query,
            "recommendations": recommendations,
            "count": len(recommendations),
            "formatted": _format_recommendations(recommendations),
        },
    }
