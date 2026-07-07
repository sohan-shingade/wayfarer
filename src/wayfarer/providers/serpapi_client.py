"""Thin async SerpApi client shared by the google_hotels and google_flights
adapters. One key powers both engines. Keep vendor specifics in the adapters;
this only does the HTTP + error envelope.
"""
from __future__ import annotations

import httpx

SERPAPI_URL = "https://serpapi.com/search.json"


async def serpapi_get(params: dict, *, timeout_s: float = 60.0) -> dict:
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.get(SERPAPI_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"serpapi error: {data['error']}")
    return data
