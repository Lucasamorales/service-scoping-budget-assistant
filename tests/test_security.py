"""HTTP hardening: auth, origins, rate limits, headers."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _client(**overrides: object) -> TestClient:
    base = {
        "environment": "local",
        "gemini_api_key": "",
        "gcp_project_id": "",
        "session_token_secret": "",
        "internal_access_password": "",
        "allowed_origins": "",
        # Never let a developer's real key turn a test into a sent email.
        "mail_api_key": "",
        "mail_from_address": "",
        "rate_limit_requests": 100,
        "rate_limit_window_seconds": 60,
    }
    base.update(overrides)
    return TestClient(create_app(Settings(**base)))


class TestUnauthenticatedLocal:
    def test_chat_works_without_a_secret(self) -> None:
        with _client() as client:
            response = client.post("/api/chat", json={"message": "merch"})
            assert response.status_code == 200

    def test_health_reports_auth_not_required(self) -> None:
        with _client() as client:
            assert client.get("/api/health").json()["authRequired"] is False


class TestSessionAuth:
    def test_chat_requires_a_bearer_token_when_configured(self) -> None:
        with _client(
            session_token_secret="secret",
            internal_access_password="pass",
        ) as client:
            assert client.post("/api/chat", json={"message": "merch"}).status_code == 401

    def test_a_valid_session_is_accepted(self) -> None:
        with _client(
            session_token_secret="secret",
            internal_access_password="pass",
        ) as client:
            minted = client.post(
                "/api/session",
                json={"password": "pass", "subject": "robin", "branch": "Bedford"},
            )
            assert minted.status_code == 200, minted.text
            token = minted.json()["token"]

            response = client.post(
                "/api/chat",
                json={"message": "merch"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            assert response.json()["verdict"]["status"] == "quote_required"

    def test_a_wrong_password_is_rejected(self) -> None:
        with _client(
            session_token_secret="secret",
            internal_access_password="pass",
        ) as client:
            assert (
                client.post(
                    "/api/session", json={"password": "nope", "subject": "robin"}
                ).status_code
                == 401
            )

    def test_session_requires_a_display_name(self) -> None:
        with _client(
            session_token_secret="secret",
            internal_access_password="pass",
        ) as client:
            assert (
                client.post("/api/session", json={"password": "pass"}).status_code == 422
            )
            assert (
                client.post(
                    "/api/session", json={"password": "pass", "subject": "A"}
                ).status_code
                == 422
            )

    def test_session_issuance_is_disabled_without_a_password(self) -> None:
        with _client(session_token_secret="secret") as client:
            assert (
                client.post(
                    "/api/session", json={"password": "x", "subject": "robin"}
                ).status_code
                == 503
            )

    def test_health_still_works_without_a_token(self) -> None:
        with _client(session_token_secret="secret", internal_access_password="pass") as client:
            body = client.get("/api/health").json()
            assert body["status"] == "ok"
            assert body["authRequired"] is True


class TestOriginAllowlist:
    def test_an_unknown_origin_is_blocked(self) -> None:
        with _client(allowed_origins="https://example.org") as client:
            response = client.post(
                "/api/chat",
                json={"message": "merch"},
                headers={"Origin": "https://evil.example"},
            )
            assert response.status_code == 403

    def test_an_allowed_origin_passes(self) -> None:
        with _client(allowed_origins="https://example.org") as client:
            response = client.post(
                "/api/chat",
                json={"message": "merch"},
                headers={"Origin": "https://example.org"},
            )
            assert response.status_code == 200

    def test_a_missing_origin_is_allowed(self) -> None:
        """Same-origin and non-browser clients omit the header."""
        with _client(allowed_origins="https://example.org") as client:
            assert client.post("/api/chat", json={"message": "merch"}).status_code == 200


class TestRateLimit:
    def test_excess_requests_are_rejected(self) -> None:
        with _client(rate_limit_requests=3, rate_limit_window_seconds=60) as client:
            for _ in range(3):
                assert client.post("/api/chat", json={"message": "merch"}).status_code == 200

            limited = client.post("/api/chat", json={"message": "merch"})
            assert limited.status_code == 429
            assert "Retry-After" in limited.headers

    def test_health_is_not_rate_limited(self) -> None:
        with _client(rate_limit_requests=1, rate_limit_window_seconds=60) as client:
            assert client.post("/api/chat", json={"message": "hi"}).status_code == 200
            assert client.get("/api/health").status_code == 200
            assert client.get("/api/health").status_code == 200


class TestSecurityHeaders:
    def test_api_responses_carry_hardening_headers(self) -> None:
        with _client() as client:
            headers = client.get("/api/health").headers
            assert headers["X-Content-Type-Options"] == "nosniff"
            assert "default-src 'none'" in headers["Content-Security-Policy"]

    def test_the_widget_page_may_load_its_own_assets(self) -> None:
        with _client() as client:
            page = client.get("/")
            assert page.status_code == 200
            assert "acme-chat" in page.text
            csp = page.headers.get("Content-Security-Policy", "")
            assert "script-src 'self'" in csp
            assert "style-src" in csp and "'unsafe-inline'" in csp
            assert "default-src 'none'" not in csp

    def test_the_widget_bundle_is_served(self) -> None:
        with _client() as client:
            bundle = client.get("/widget/acme-chat.js")
            assert bundle.status_code == 200
            assert "acme-chat" in bundle.text


class TestCorsPreflight:
    """The browser's question before a cross-origin request.

    These only matter off-origin, which is why the page this service serves
    itself never showed the problem: a preflight to /api/chat reached the
    bearer-token check with no Authorization header — because a preflight never
    carries one — and was refused. Sign-in worked, every message after it did
    not.
    """

    ORIGIN = "https://www.example.com"

    def _client(self) -> TestClient:
        return TestClient(
            create_app(
                Settings(
                    environment="production",
                    allowed_origins=self.ORIGIN,
                    session_token_secret="test-secret-not-real",
                    internal_access_password="pw",
                    budget_spreadsheet_id="",
                )
            )
        )

    def _preflight(self, client: TestClient, path: str, origin: str):
        return client.options(
            path,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    def test_a_preflight_to_chat_is_not_asked_for_a_token(self) -> None:
        response = self._preflight(self._client(), "/api/chat", self.ORIGIN)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == self.ORIGIN

    def test_the_real_request_still_needs_one(self) -> None:
        """Exempting the preflight must not exempt what follows it."""
        response = self._client().post(
            "/api/chat", headers={"Origin": self.ORIGIN}, json={"message": "hi"}
        )
        assert response.status_code == 401

    def test_a_foreign_origin_is_refused_before_anything_else(self) -> None:
        response = self._preflight(self._client(), "/api/chat", "https://evil.example")
        assert response.status_code == 403

    def test_the_allowlist_ignores_capitalisation(self) -> None:
        """Host and scheme are case-insensitive, so a mixed-case entry must
        still match rather than 403 with no hint why."""
        client = TestClient(
            create_app(
                Settings(
                    environment="production",
                    allowed_origins="https://WWW.Example.com",
                    session_token_secret="test-secret-not-real",
                    budget_spreadsheet_id="",
                )
            )
        )
        assert self._preflight(client, "/api/chat", self.ORIGIN).status_code == 200


class TestSameOrigin:
    """The service must never refuse its own page.

    A module script is fetched in CORS mode, so the chat page served at ``/``
    sends its own origin with the request for its own bundle. Once
    ALLOWED_ORIGINS named only the Webflow site, the service answered 403 to
    itself and that page loaded blank — in production, undetected, because the
    embed it was set up for kept working.
    """

    ELSEWHERE = "https://www.example.com"

    def _client(self) -> TestClient:
        return TestClient(
            create_app(
                Settings(
                    environment="production",
                    allowed_origins=self.ELSEWHERE,
                    session_token_secret="test-secret-not-real",
                    budget_spreadsheet_id="",
                )
            )
        )

    def test_the_service_serves_its_own_bundle(self) -> None:
        client = self._client()
        host = client.base_url.host
        response = client.get("/widget/acme-chat.js", headers={"Origin": f"http://{host}"})

        assert response.status_code != 403, "the service refused its own page"

    def test_https_page_on_a_tls_terminating_proxy_is_still_same_origin(self) -> None:
        """Cloud Run terminates TLS, so the page is https while the request
        reaches the app as http. Comparing whole origins would never match.

        Asserts on a static path rather than the API, because what is under
        test is the middleware's verdict; a route would drag the pipeline in
        and fail for reasons that have nothing to do with origins."""
        client = self._client()
        host = client.base_url.host
        response = client.get(
            "/widget/acme-chat.js", headers={"Origin": f"https://{host}"}
        )

        assert response.status_code != 403

    def test_a_foreign_origin_is_still_refused(self) -> None:
        response = self._client().get(
            "/widget/acme-chat.js", headers={"Origin": "https://evil.example"}
        )

        assert response.status_code == 403

    def test_a_lookalike_host_is_not_the_same_origin(self) -> None:
        """Matching on a suffix rather than the whole host would let
        evil-testserver.example through."""
        client = self._client()
        host = client.base_url.host
        response = client.get(
            "/widget/acme-chat.js", headers={"Origin": f"https://evil-{host}.example"}
        )

        assert response.status_code == 403
