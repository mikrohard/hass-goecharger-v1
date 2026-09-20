"""Tests for the low level API client."""

from __future__ import annotations

import aiohttp
import pytest

from custom_components.goecharger_v1.api import (
    GoeChargerApi,
    GoeChargerConnectionError,
    normalize_host,
)

from .conftest import FakeCharger


def test_normalize_host() -> None:
    """Scheme and slashes are stripped."""
    assert normalize_host(" http://192.168.1.5/ ") == "192.168.1.5"
    assert normalize_host("HTTPS://charger.local") == "charger.local"
    assert normalize_host("10.0.0.1:8080") == "10.0.0.1:8080"


async def test_payload_is_sent_unencoded(charger: FakeCharger) -> None:
    """The `=` inside the payload must reach the charger verbatim."""
    async with aiohttp.ClientSession() as session:
        api = GoeChargerApi(session, charger.host)
        status = await api.set_value("amx", 10)
    assert status["amp"] == "16"  # amx is not mirrored into amp
    assert charger.effective_amp == 10
    assert charger.requests[-1] == "/mqtt?payload=amx=10"


async def test_retries_then_succeeds(charger: FakeCharger) -> None:
    """Transient failures are retried within one call."""
    charger.fail_next = 2
    async with aiohttp.ClientSession() as session:
        api = GoeChargerApi(session, charger.host, retries=3)
        status = await api.get_status()
    assert status["sse"] == "000123"
    assert len(charger.requests) == 3


async def test_gives_up_after_retries(charger: FakeCharger) -> None:
    """After the configured attempts a connection error is raised."""
    charger.fail_next = 5
    async with aiohttp.ClientSession() as session:
        api = GoeChargerApi(session, charger.host, retries=3)
        with pytest.raises(GoeChargerConnectionError):
            await api.get_status()
    assert len(charger.requests) == 3


async def test_unreachable_host() -> None:
    """A closed port yields a connection error, not an unhandled exception."""
    async with aiohttp.ClientSession() as session:
        api = GoeChargerApi(session, "127.0.0.1:1", retries=2, timeout=2)
        with pytest.raises(GoeChargerConnectionError):
            await api.get_status()
