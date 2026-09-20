"""Async HTTP client for the go-eCharger local API v1."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
from yarl import URL

from .const import DEFAULT_RETRIES, DEFAULT_TIMEOUT, LOGGER, RETRY_BACKOFF
from .util import StatusData


class GoeChargerError(Exception):
    """Base error for the go-eCharger client."""


class GoeChargerConnectionError(GoeChargerError):
    """The charger could not be reached (timeout, refused, DNS, ...)."""


class GoeChargerInvalidResponseError(GoeChargerError):
    """The charger answered, but not with a status JSON object."""


def normalize_host(raw: str) -> str:
    """Strip scheme and trailing slashes from a user supplied host."""
    host = raw.strip()
    for prefix in ("http://", "https://"):
        if host.lower().startswith(prefix):
            host = host[len(prefix) :]
    return host.strip().rstrip("/")


class GoeChargerApi:
    """Minimal client for the local HTTP API (API v1).

    Both the status request and every command return the complete status
    object, so a command's result can be used as a fresh status update.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        *,
        timeout: float | None = None,
        retries: int | None = None,
        backoff: float | None = None,
    ) -> None:
        """Initialise the client. Unset values fall back to the module defaults."""
        self._session = session
        self.host = normalize_host(host)
        self._timeout = aiohttp.ClientTimeout(
            total=DEFAULT_TIMEOUT if timeout is None else timeout
        )
        self._retries = max(1, DEFAULT_RETRIES if retries is None else retries)
        self._backoff = RETRY_BACKOFF if backoff is None else backoff
        # The charger's HTTP server is single threaded; serialise our requests.
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """Return the base URL of the charger."""
        return f"http://{self.host}"

    async def get_status(self) -> StatusData:
        """Fetch the status object."""
        return await self._request(URL(f"{self.base_url}/status"))

    async def set_value(self, key: str, value: Any) -> StatusData:
        """Send a `key=value` command and return the resulting status."""
        # Build the URL by hand: the charger expects the literal payload
        # `key=value` and does not URL-decode it, so the `=` must not be
        # percent-encoded. `encoded=True` stops yarl from touching it.
        url = URL(f"{self.base_url}/mqtt?payload={key}={value}", encoded=True)
        return await self._request(url)

    async def _request(self, url: URL) -> StatusData:
        """Perform a GET with retries and return the parsed status object."""
        last_err: Exception | None = None
        async with self._lock:
            for attempt in range(1, self._retries + 1):
                try:
                    async with self._session.get(url, timeout=self._timeout) as resp:
                        resp.raise_for_status()
                        # The charger does not always send a JSON content type.
                        data = await resp.json(content_type=None)
                    if not isinstance(data, dict) or not data:
                        raise GoeChargerInvalidResponseError(
                            f"Unexpected response from {self.host}: {data!r}"
                        )
                except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
                    last_err = err
                    LOGGER.debug(
                        "Request %s failed (attempt %d/%d): %s",
                        url,
                        attempt,
                        self._retries,
                        _describe(err),
                    )
                except (ValueError, GoeChargerInvalidResponseError) as err:
                    last_err = err
                    LOGGER.debug(
                        "Invalid response from %s (attempt %d/%d): %s",
                        url,
                        attempt,
                        self._retries,
                        _describe(err),
                    )
                else:
                    return data

                if attempt < self._retries:
                    await asyncio.sleep(self._backoff * attempt)

        if isinstance(last_err, GoeChargerInvalidResponseError):
            raise last_err
        if isinstance(last_err, ValueError):
            raise GoeChargerInvalidResponseError(
                f"Charger at {self.host} did not return valid JSON: {_describe(last_err)}"
            ) from last_err
        raise GoeChargerConnectionError(
            f"Could not reach charger at {self.host} after {self._retries} attempts: "
            f"{_describe(last_err)}"
        ) from last_err


def _describe(err: Exception | None) -> str:
    """Return a human readable description of an exception."""
    if err is None:
        return "unknown error"
    return str(err) or type(err).__name__
