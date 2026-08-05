"""Session tokens: issue, verify, reject the forgeries."""

from __future__ import annotations

import pytest

from app.api.session import Role, SessionError, issue_token, verify_token

SECRET = "test-secret-not-for-production"


class TestIssueAndVerify:
    def test_a_fresh_token_round_trips(self) -> None:
        token, claims = issue_token(
            secret=SECRET,
            subject="robin",
            role=Role.ACCOUNT_MANAGER,
            country="UK",
            branch="Basingstoke",
            ttl_seconds=60,
        )
        verified = verify_token(token, SECRET)
        assert verified.subject == "robin"
        assert verified.role is Role.ACCOUNT_MANAGER
        assert verified.country == "UK"
        assert verified.branch == "Basingstoke"
        assert verified.expires_at == claims.expires_at

    def test_a_tampered_payload_is_rejected(self) -> None:
        token, _ = issue_token(secret=SECRET, subject="robin", role=Role.ADMIN)
        body, signature = token.split(".")
        # Flip a character in the body without updating the MAC.
        tampered = ("A" if body[0] != "A" else "B") + body[1:]
        with pytest.raises(SessionError):
            verify_token(f"{tampered}.{signature}", SECRET)

    def test_a_wrong_secret_is_rejected(self) -> None:
        token, _ = issue_token(secret=SECRET, subject="robin", role=Role.ADMIN)
        with pytest.raises(SessionError):
            verify_token(token, "other-secret")

    def test_an_expired_token_is_rejected(self) -> None:
        token, _ = issue_token(
            secret=SECRET,
            subject="robin",
            role=Role.ADMIN,
            ttl_seconds=60,
            now=1_000,
        )
        with pytest.raises(SessionError, match="expired"):
            verify_token(token, SECRET, now=1_000 + 120)

    def test_garbage_is_rejected(self) -> None:
        with pytest.raises(SessionError):
            verify_token("not-a-token", SECRET)

    def test_issue_without_a_secret_is_loud(self) -> None:
        with pytest.raises(SessionError):
            issue_token(secret="", subject="x", role=Role.ADMIN)
