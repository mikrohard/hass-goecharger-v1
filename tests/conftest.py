"""Shared fixtures: a fake go-eCharger HTTP server and helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
import copy
import json
import pathlib
from unittest.mock import patch

from aiohttp import web
import pytest
import pytest_socket
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant

from custom_components.goecharger_v1.const import DOMAIN

SERIAL = "000123"

BASE_STATUS = {
    "version": "B",
    "rbc": "251",
    "rbt": "7200000",
    "car": "2",
    "amp": "16",
    "amx": "16",
    "err": "0",
    "ast": "0",
    "alw": "1",
    "stp": "0",
    "cbl": "20",
    "pha": "56",  # 0b00111000: L1-L3 before the contactor, none after
    "tmp": "30",
    "dws": "360000",  # 1 kWh
    "dwo": "0",
    "adi": "1",
    "uby": "0",
    "eto": "1234",  # 123.4 kWh
    "wst": "3",
    "nrg": [230, 231, 232, 1, 100, 101, 102, 23, 23, 23, 0, 690, 99, 98, 97, 0],
    "fwv": "042.0",
    "sse": SERIAL,
    "wss": "goe",
    "wke": "secret",
    "ama": "16",
    "ust": "0",
    "loa": "0",
}


class FakeCharger:
    """A fake go-eCharger local HTTP API with fault injection."""

    def __init__(self) -> None:
        self.status = copy.deepcopy(BASE_STATUS)
        self.requests: list[str] = []
        # Number of upcoming requests that should fail with HTTP 500.
        self.fail_next = 0
        # Fail every request until set back to False.
        self.offline = False
        # Simulate the FW 0.42.0 bug: amx is clamped to 6 A until amp is
        # set to 6 and then to something higher again.
        self.amx_bug = False
        self._amp_was_six = False
        # Effective (RAM) current; amx is NOT mirrored into amp by the charger.
        self.effective_amp = int(self.status["amp"])
        # Firmware 0.42.0 reports amx in the status object, but only a few
        # seconds after the write: the command response still shows the old
        # value and the next /status request the new one.
        self.report_amx = True
        self._amx_to_report: str | None = None
        # How rst=1 is answered: "drop" the connection like the real charger,
        # "reply" with the status object, or "error" with HTTP 503.
        self.reboot_mode = "drop"
        self.reboot_calls = 0
        self.host = ""

    def _maybe_fail(self) -> web.Response | None:
        if self.offline:
            return web.Response(status=500, text="offline")
        if self.fail_next > 0:
            self.fail_next -= 1
            return web.Response(status=500, text="flaky")
        return None

    async def handle_status(self, request: web.Request) -> web.Response:
        self.requests.append(request.rel_url.raw_path_qs)
        if (fail := self._maybe_fail()) is not None:
            return fail
        if self._amx_to_report is not None:
            self.status["amx"] = self._amx_to_report
            self._amx_to_report = None
        return web.Response(text=json.dumps(self.status), content_type="text/html")

    async def handle_mqtt(self, request: web.Request) -> web.Response:
        self.requests.append(request.rel_url.raw_path_qs)
        if (fail := self._maybe_fail()) is not None:
            return fail
        raw = request.rel_url.raw_query_string
        assert raw.startswith("payload="), raw
        payload = raw[len("payload=") :]
        key, _, value = payload.partition("=")
        if key == "rst":
            self.reboot_calls += 1
            self.reboot()
            if self.reboot_mode == "error":
                raise web.HTTPServiceUnavailable()
            if self.reboot_mode == "drop":
                # The real charger restarts without answering: drop the
                # connection (aiohttp may then transparently retry once).
                assert request.transport is not None
                request.transport.close()
                return web.Response()
        self.apply(key, value)
        return web.Response(text=json.dumps(self.status), content_type="text/html")

    def apply(self, key: str, value: str) -> None:
        """Apply a command the way the charger would."""
        if key == "amp":
            amps = int(value)
            if amps == 6:
                self._amp_was_six = True
            elif self._amp_was_six:
                self.amx_bug = False
            self.status["amp"] = str(amps)
            self.effective_amp = amps
        elif key == "amx":
            amps = int(value)
            if self.amx_bug:
                amps = min(amps, 6)
            self.effective_amp = amps
            if self.report_amx:
                self._amx_to_report = str(amps)  # visible on the next /status
            else:
                self.status.pop("amx", None)
        elif key == "alw":
            self.status["alw"] = str(int(value))
        else:
            self.status[key] = value

    def reboot(self) -> None:
        """Simulate a charger reboot: rbc increments, amx falls back to amp."""
        self.status["rbc"] = str(int(self.status["rbc"]) + 1)
        self.status["rbt"] = "1000"
        self.effective_amp = int(self.status["amp"])
        self._amx_to_report = None
        if self.report_amx:
            self.status["amx"] = self.status["amp"]
        else:
            self.status.pop("amx", None)
        self.amx_bug = True
        self._amp_was_six = False

    def commands(self) -> list[str]:
        """Return the payloads of all /mqtt commands seen so far."""
        return [
            r.split("payload=", 1)[1] for r in self.requests if r.startswith("/mqtt?")
        ]


@pytest.fixture(autouse=True)
def allow_localhost_sockets() -> None:
    """Allow TCP connections to the fake charger on localhost.

    The Home Assistant test harness disables socket creation entirely; this
    runs after it and re-enables sockets while still blocking any host other
    than 127.0.0.1.
    """
    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts(["127.0.0.1"], allow_unix_socket=True)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations in all tests."""


@pytest.fixture(autouse=True)
def fast_retries() -> AsyncIterator[None]:
    """Do not sleep between retries during tests."""
    with patch("custom_components.goecharger_v1.api.RETRY_BACKOFF", 0):
        yield


@pytest.fixture
async def charger(hass: HomeAssistant) -> AsyncIterator[FakeCharger]:
    """Run the fake charger on a random localhost port."""
    fake = FakeCharger()
    app = web.Application()
    app.router.add_get("/status", fake.handle_status)
    app.router.add_get("/mqtt", fake.handle_mqtt)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    fake.host = f"127.0.0.1:{port}"
    try:
        yield fake
    finally:
        await runner.cleanup()


@pytest.fixture
def real_status() -> dict:
    """Status object captured from a real go-eCharger on firmware 042.0."""
    path = pathlib.Path(__file__).parent / "fixtures" / "status_fw042.json"
    return json.loads(path.read_text())


@pytest.fixture
def mock_entry(charger: FakeCharger) -> MockConfigEntry:
    """Return a config entry pointing at the fake charger."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"go-eCharger {SERIAL}",
        unique_id=SERIAL,
        data={CONF_HOST: charger.host, CONF_SCAN_INTERVAL: 5},
    )


@pytest.fixture
async def setup_entry(hass: HomeAssistant, mock_entry: MockConfigEntry) -> MockConfigEntry:
    """Set up the integration against the fake charger."""
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    return mock_entry
