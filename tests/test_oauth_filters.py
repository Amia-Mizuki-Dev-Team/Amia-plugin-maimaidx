from __future__ import annotations

import asyncio
import hashlib
import sys
import unittest
from pathlib import Path

import httpx

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from libraries.diving_fish_filters import (  # noqa: E402
    FilterParseError,
    extract_response_records,
    parse_filters,
    record_matches,
)
from libraries.diving_fish_oauth import (  # noqa: E402
    DivingFishOAuth,
    build_subject_ref,
)
from libraries.maimaidx_error import (  # noqa: E402
    OAuthConsentRequiredError,
    OAuthScopeError,
)


class _Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class OAuthAndFilterTests(unittest.TestCase):
    def test_subject_digest_matches_document(self):
        expected = hashlib.sha256(b"client:external").hexdigest()
        self.assertEqual(build_subject_ref("client", "external"), f"ref:{expected}")

    def test_filter_parser_ranges_aliases_and_empty_fc(self):
        parsed = parse_filters(
            'difficulty=3 ds=13.5.. fc=fc,fcp fc=ap title="A Song" page=2'
        )
        self.assertEqual(parsed.page, 2)
        self.assertEqual(parsed.values["level_index"], ["3"])
        self.assertEqual(parsed.values["fc"], ["fc", "fcp", "ap"])
        self.assertEqual(parsed.query_params()[-1], ("title", "A Song"))
        self.assertTrue(record_matches({"level_index": 3, "ds": 14, "fc": "ap", "title": "A Song"}, parsed.values))
        self.assertTrue(record_matches({"is_new": "false"}, {"is_new": False}))

        empty = parse_filters("fc=")
        self.assertEqual(empty.values["fc"], [""])

    def test_filter_parser_rejects_unknown_and_bad_range(self):
        with self.assertRaises(FilterParseError):
            parse_filters("not_a_field=x")
        with self.assertRaises(FilterParseError):
            parse_filters("ds=14..13")

    def test_oauth_cache_and_single_401_refresh(self):
        clock = _Clock()
        calls: list[tuple[str, str]] = []
        token_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal token_count
            if request.url.host == "auth.diving-fish.com":
                token_count += 1
                body = request.content.decode()
                self.assertIn("grant_type=urn%3Adiving-fish%3Aparams%3Aoauth%3Agrant-type%3Aon-behalf-of", body)
                return httpx.Response(
                    200,
                    json={"access_token": f"token-{token_count}", "expires_in": 300},
                )
            calls.append((request.url.path, request.headers.get("Authorization", "")))
            if len(calls) == 1:
                return httpx.Response(401, json={"message": "expired"})
            return httpx.Response(
                200,
                json={"records": [], "filters": {"ds": "13.5.."}},
            )

        async def run():
            oauth = DivingFishOAuth(
                "client",
                "secret",
                transport=httpx.MockTransport(handler),
                clock=clock,
            )
            subject = oauth.subject_ref("external")
            response = await oauth.request_api(
                "GET", "/player/records", subject, params=[("ds", "13.5..")]
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(token_count, 2)
            self.assertEqual(calls[0][0], "/api/maimaidxprober/player/records")
            self.assertEqual(calls[1][1], "Bearer token-2")
            await oauth.get_access_token(subject)
            self.assertEqual(token_count, 2)

        asyncio.run(run())

    def test_oauth_consent_is_user_expected(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "auth.diving-fish.com":
                return httpx.Response(
                    400,
                    json={"error": "consent_required"},
                )
            return httpx.Response(500)

        async def run():
            oauth = DivingFishOAuth(
                "client", "secret", transport=httpx.MockTransport(handler)
            )
            with self.assertRaises(OAuthConsentRequiredError):
                await oauth.get_access_token(oauth.subject_ref("external"))

        asyncio.run(run())

    def test_oauth_403_scope_error_is_not_mistaken_for_consent(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "auth.diving-fish.com":
                return httpx.Response(
                    200,
                    json={"access_token": "temporary", "expires_in": 300},
                )
            return httpx.Response(403, json={"error": "insufficient_scope"})

        async def run():
            oauth = DivingFishOAuth(
                "client", "secret", transport=httpx.MockTransport(handler)
            )
            with self.assertRaises(OAuthScopeError):
                await oauth.request_api(
                    "GET", "/player/records", oauth.subject_ref("external")
                )

        asyncio.run(run())

    def test_filter_response_echo_is_extractable(self):
        records, echo = extract_response_records(
            {"records": [{"id": 1}], "filters": {"level_index": 3}}
        )
        self.assertEqual(records, [{"id": 1}])
        self.assertEqual(echo, {"level_index": 3})


if __name__ == "__main__":
    unittest.main()
