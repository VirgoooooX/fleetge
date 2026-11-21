"""Shared Notify Hub receipt handling for Fleetge's durable alerts."""

from typing import Literal

import httpx


NOTIFY_KEYS = ("NOTIFYHUB_URL", "NOTIFYHUB_KEY", "NOTIFYHUB_RECIPIENT")


def matches_destination(config: dict[str, str], url: str, recipient: str) -> bool:
    return bool(
        config.get("NOTIFYHUB_KEY")
        and config.get("NOTIFYHUB_URL") == url
        and config.get("NOTIFYHUB_RECIPIENT") == recipient
    )


async def submit_event(
    client: httpx.AsyncClient, url: str, api_key: str, payload: dict,
) -> tuple[Literal["accepted", "pending", "blocked"], str]:
    """Interpret the receipt; a duplicate confirms the previous durable submission."""
    try:
        response = await client.post(f"{url}/api/v1/events", json=payload, headers={"X-API-Key": api_key})
        if response.status_code in {200, 202, 409}:
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, dict) and data.get("event_id"):
                if data.get("status") == "duplicate" or (
                    response.status_code == 202 and data.get("status") == "accepted"
                ):
                    return "accepted", ""
            if response.status_code == 202:
                return "pending", "Notify Hub returned no confirmed event id."
    except (httpx.HTTPError, ValueError):
        return "pending", "Notify Hub request was not confirmed."
    if response.status_code == 429 or response.status_code >= 500:
        return "pending", f"Notify Hub HTTP {response.status_code}."
    return "blocked", f"Notify Hub HTTP {response.status_code}."
