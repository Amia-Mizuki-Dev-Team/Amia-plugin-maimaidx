"""Small OAuth client for Diving-Fish's server-side bot integration.

The OAuth client deliberately keeps no durable user state.  The authorization
server stores the device-code binding; the bot only derives the user's
``ref:`` subject from the same external identifier it used before the
Developer-Token migration and caches a short-lived access token in memory.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import time
from typing import Any, Mapping

import httpx

from .maimaidx_error import (
    MaimaiDataFormatError,
    MaimaiRateLimitError,
    MaimaiTimeoutError,
    OAuthConfigurationError,
    OAuthConsentRequiredError,
    OAuthScopeError,
    ServerError,
)


AUTH_BASE = "https://auth.diving-fish.com"
TOKEN_PATH = "/oauth/token"
DEFAULT_SCOPE = "prober.records.read"
TOKEN_EXPIRY_SKEW = 30.0

# Public type alias kept deliberately small: the server treats the subject as
# an opaque string and the plugin must never persist or reinterpret it.
OAuthSubjectRef = str


def subject_digest(client_id: str, external_id: str) -> str:
    """Return the migration-compatible lowercase SHA-256 digest."""

    return hashlib.sha256(f"{client_id}:{external_id}".encode("utf-8")).hexdigest()


def build_subject_ref(client_id: str, external_id: str) -> str:
    """Return the long-term OAuth subject used by the token endpoint."""

    return f"ref:{subject_digest(client_id, external_id)}"


@dataclass(frozen=True)
class _CachedToken:
    access_token: str
    expires_at: float


class DivingFishOAuth:
    """OAuth device-binding and on-behalf-of token client.

    ``transport`` is intentionally injectable so unit tests can use
    ``httpx.MockTransport`` without contacting the real authorization server.
    It is never persisted or exposed in diagnostics.
    """

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        scope: str = DEFAULT_SCOPE,
        *,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.client_id = str(client_id or "").strip()
        self.client_secret = str(client_secret or "")
        self.scope = str(scope or DEFAULT_SCOPE).strip() or DEFAULT_SCOPE
        self.timeout = timeout
        self.transport = transport
        self._clock = clock
        self._tokens: dict[str, _CachedToken] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    @classmethod
    def from_config(cls, config: Any) -> "DivingFishOAuth":
        return cls(
            getattr(config, "diving_fish_oauth_client_id", ""),
            getattr(config, "diving_fish_oauth_client_secret", ""),
            getattr(config, "diving_fish_oauth_scope", DEFAULT_SCOPE),
        )

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def subject_ref(self, external_id: str) -> str:
        if not self.client_id:
            raise OAuthConfigurationError()
        return build_subject_ref(self.client_id, str(external_id))

    def build_subject_ref(self, external_id: str) -> OAuthSubjectRef:
        """Build the opaque subject using this application's client id.

        Keep the service-shaped method alongside the module helper so command
        code and integrations do not need to know how the client id is mixed
        into the digest.
        """
        return self.subject_ref(external_id)

    def _require_configured(self) -> None:
        if not self.configured:
            raise OAuthConfigurationError()

    async def _lock_for(self, subject: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault(subject, asyncio.Lock())

    @staticmethod
    def _json(response: httpx.Response) -> Mapping[str, Any]:
        try:
            data = response.json()
        except (ValueError, TypeError) as exc:
            raise MaimaiDataFormatError() from exc
        if not isinstance(data, Mapping):
            raise MaimaiDataFormatError()
        return data

    @staticmethod
    def _error_name(data: Mapping[str, Any]) -> str:
        return str(data.get("error", data.get("code", ""))).strip().lower()

    @classmethod
    def _raise_oauth_error(cls, response: httpx.Response, data: Mapping[str, Any]) -> None:
        error = cls._error_name(data)
        if error == "consent_required":
            raise OAuthConsentRequiredError()
        if error in {"invalid_scope", "insufficient_scope"}:
            raise OAuthScopeError()
        if error in {"invalid_client", "unauthorized_client", "invalid_request"}:
            raise OAuthConfigurationError()
        if response.status_code == 429 or error in {"slow_down", "rate_limit"}:
            raise MaimaiRateLimitError()
        if response.status_code >= 500:
            raise ServerError()
        if response.status_code in {401, 403}:
            raise OAuthConfigurationError()
        raise ServerError()

    async def _post_form(self, path: str, data: Mapping[str, Any]) -> httpx.Response:
        self._require_configured()
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.post(f"{AUTH_BASE}{path}", data=dict(data))
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise MaimaiTimeoutError() from exc
        except httpx.HTTPError as exc:
            raise ServerError() from exc
        return response

    async def _exchange(self, subject: str) -> _CachedToken:
        response = await self._post_form(
            TOKEN_PATH,
            {
                "grant_type": "urn:diving-fish:params:oauth:grant-type:on-behalf-of",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "subject": subject,
                "scope": self.scope,
            },
        )
        data = self._json(response)
        if response.status_code >= 400:
            self._raise_oauth_error(response, data)
        try:
            token = str(data["access_token"])
            expires_in = max(1.0, float(data.get("expires_in", 300)))
        except (KeyError, TypeError, ValueError) as exc:
            raise MaimaiDataFormatError() from exc
        if not token:
            raise MaimaiDataFormatError()
        cached = _CachedToken(token, self._clock() + expires_in)
        self._tokens[subject] = cached
        return cached

    async def get_access_token(self, subject: str, *, force: bool = False) -> str:
        self._require_configured()
        subject = str(subject).strip()
        if not subject:
            raise OAuthConsentRequiredError()
        cached = self._tokens.get(subject)
        if not force and cached and cached.expires_at - self._clock() > TOKEN_EXPIRY_SKEW:
            return cached.access_token
        lock = await self._lock_for(subject)
        async with lock:
            cached = self._tokens.get(subject)
            if not force and cached and cached.expires_at - self._clock() > TOKEN_EXPIRY_SKEW:
                return cached.access_token
            return (await self._exchange(subject)).access_token

    def invalidate_access_token(self, subject: str) -> None:
        self._tokens.pop(str(subject).strip(), None)

    async def request_api(
        self,
        method: str,
        path: str,
        subject: str,
        *,
        params: Mapping[str, Any] | list[tuple[str, Any]] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        """Call a Bearer-protected Diving-Fish endpoint.

        A stale 401 causes one cache eviction and one fresh token exchange.
        The request itself is never retried more than once.
        """

        self._require_configured()
        subject = str(subject).strip()
        token = await self.get_access_token(subject)
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    transport=self.transport,
                ) as client:
                    response = await client.request(
                        method,
                        f"https://www.diving-fish.com/api/maimaidxprober{path}",
                        headers={"Authorization": f"Bearer {token}"},
                        params=params,
                        json=json,
                    )
            except (httpx.TimeoutException, TimeoutError) as exc:
                raise MaimaiTimeoutError() from exc
            except httpx.HTTPError as exc:
                raise ServerError() from exc
            if response.status_code != 401:
                if response.status_code == 429:
                    raise MaimaiRateLimitError()
                if response.status_code == 403:
                    try:
                        data = self._json(response)
                    except MaimaiDataFormatError:
                        # A proxy or an upstream error page may not be JSON;
                        # preserve the OAuth permission/consent classification
                        # without exposing or retaining that response body.
                        data = {}
                    error_name = self._error_name(data)
                    message = str(data.get("message", data.get("error_description", ""))).lower()
                    if error_name in {"invalid_scope", "insufficient_scope"}:
                        raise OAuthScopeError()
                    if "scope" in message or "权限" in message:
                        raise OAuthScopeError()
                    if error_name in {"invalid_client", "unauthorized_client"}:
                        raise OAuthConfigurationError()
                    raise OAuthConsentRequiredError()
                if response.status_code >= 500:
                    raise ServerError()
                return response
            if attempt == 0:
                self.invalidate_access_token(subject)
                token = await self.get_access_token(subject, force=True)
        raise OAuthConsentRequiredError()
