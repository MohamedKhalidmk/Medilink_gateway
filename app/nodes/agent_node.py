"""
Agent node for Vezeeta booking automation.

Why this module exists
----------------------
After AutoRec recommends doctors, this node calls the Agent service to handle
the actual booking automation on Vezeeta. The Agent service uses Playwright
to interact with vezeeta.com.

Pipeline trace
--------------
  1. autorec_node.py writes autorec_result with doctor recommendations.

  2. graph.py sends the shared MediLinkState to this node.

  3. this node builds a booking payload from autorec_result and user context.

  4. this node calls the Agent service through clients.call_agent().

  5. this node writes:
       agent_result  = raw booking result from the Agent service
       final_answer  = formatted response combining recommendations + booking status

Important boundary
------------------
This node does not run browser automation directly. It delegates to the
standalone Agent service which handles Playwright interactions.
"""

from __future__ import annotations

import logging
from typing import Any

from app import clients
from app.state import MediLinkState

logger = logging.getLogger("medilink.gateway")


def _format_booking_result(
    autorec_result: dict[str, Any] | None,
    agent_result: dict[str, Any] | None,
) -> str:
    """Combine AutoRec recommendations and booking result into a user response."""
    parts = []

    # Include recommendations
    if autorec_result and autorec_result.get("formatted"):
        parts.append(autorec_result["formatted"])

    # Include booking status
    if agent_result:
        status = agent_result.get("status", "unknown")
        message = agent_result.get("message", "")

        if status == "recommendations_only":
            parts.append(
                "\n📋 These are our best matches from the database. "
                "To book an appointment, please select a doctor and provide "
                "your name and phone number."
            )
        elif status in {"dry_run_stopped_before_final_confirmation", "booking_initiated"}:
            parts.append(f"\n🏥 Booking status: {message or status}")
        elif status == "error":
            parts.append(f"\n⚠️ Booking could not be completed: {message or 'Unknown error'}")
        elif message:
            parts.append(f"\n📌 {message}")
    elif autorec_result and autorec_result.get("recommendations"):
        parts.append(
            "\n📋 To book an appointment with any of these doctors, "
            "please provide your name and phone number."
        )

    return "\n".join(parts) if parts else (
        "I couldn't find doctors or complete a booking. "
        "Please try describing your needs differently."
    )


def agent_node(state: MediLinkState) -> dict:
    """
    LangGraph node entry point.

    Reads:
      autorec_result, user_message, user_id

    Writes:
      agent_result, final_answer, and error on recoverable failures
    """
    autorec_result = state.get("autorec_result")
    user_message = (state.get("user_message") or "").strip()
    user_id = state.get("user_id")

    # Build booking payload for the agent service
    booking_payload: dict[str, Any] = {
        "user_message": user_message,
    }
    if user_id:
        booking_payload["user_id"] = user_id
    if autorec_result:
        booking_payload["recommendations"] = autorec_result.get("recommendations", [])

    try:
        result = clients.call_agent(booking_payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent service call failed")
        # Still return recommendations even if booking fails
        return {
            "error": f"Agent service error: {exc}",
            "agent_result": None,
            "final_answer": _format_booking_result(autorec_result, None),
        }

    return {
        "agent_result": result,
        "final_answer": _format_booking_result(autorec_result, result),
    }
