"""Country → Account Manager / Country Manager contact matrix (read-only)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.keys import normalize_term

__all__ = ["Contact", "ContactDirectory", "load_contacts"]

ROLE_ACCOUNT_MANAGER = "account_manager"
ROLE_COUNTRY_MANAGER = "country_manager"


@dataclass(frozen=True, slots=True)
class Contact:
    name: str
    email: str
    role: str
    countries: tuple[str, ...]


# Aliases we show as buttons / accept in chat → canonical label for the matrix.
_CANONICAL_COUNTRIES = (
    "United Kingdom",
    "France",
    "Canada",
    "Australia",
)


class ContactDirectory:
    """Resolve a recipient by country (and optionally role). International / unknown → None."""

    def __init__(self, contacts: tuple[Contact, ...]) -> None:
        self._by_country_role: dict[str, dict[str, Contact]] = {}
        self._alias_to_canonical: dict[str, str] = {}
        for contact in contacts:
            role_key = normalize_term(contact.role) or ROLE_ACCOUNT_MANAGER
            for country in contact.countries:
                key = normalize_term(country)
                self._by_country_role.setdefault(key, {})[role_key] = contact
                canonical = country if country in _CANONICAL_COUNTRIES else None
                if canonical is None:
                    for candidate in _CANONICAL_COUNTRIES:
                        if normalize_term(candidate) == key:
                            canonical = candidate
                            break
                if canonical is None:
                    canonical = country
                self._alias_to_canonical.setdefault(key, canonical)
        self.contacts = contacts

    def for_country(
        self,
        country: str | None,
        *,
        role: str | None = None,
    ) -> Contact | None:
        if not country:
            return None
        by_role = self._by_country_role.get(normalize_term(country))
        if not by_role:
            return None
        if role:
            wanted = normalize_term(role)
            if wanted in by_role:
                return by_role[wanted]
            # Common aliases.
            if wanted in {"am", "account manager"} and ROLE_ACCOUNT_MANAGER in by_role:
                return by_role[ROLE_ACCOUNT_MANAGER]
            if wanted in {"cm", "country manager"} and ROLE_COUNTRY_MANAGER in by_role:
                return by_role[ROLE_COUNTRY_MANAGER]
            return None
        # Default: AM, else any contact for that country.
        return by_role.get(ROLE_ACCOUNT_MANAGER) or next(iter(by_role.values()), None)

    def selectable_countries(self) -> tuple[str, ...]:
        """Countries to offer when we need to ask (matrix coverage only)."""
        return tuple(
            name
            for name in _CANONICAL_COUNTRIES
            if normalize_term(name) in self._by_country_role
        )

    def match_country(self, message: str) -> str | None:
        """Pull a known country/alias out of a free-text reply."""
        normalized = normalize_term(message)
        if not normalized:
            return None
        aliases = sorted(self._alias_to_canonical, key=len, reverse=True)
        for alias in aliases:
            if alias == normalized or f" {alias} " in f" {normalized} ":
                return self._alias_to_canonical[alias]
        return None


def load_contacts(path: Path) -> ContactDirectory:
    if not path.is_file():
        return ContactDirectory(())
    raw = json.loads(path.read_text(encoding="utf-8"))
    contacts: list[Contact] = []
    for row in raw.get("contacts", []):
        countries = tuple(str(c) for c in row.get("countries", ()) if c)
        name = str(row.get("name", "")).strip()
        email = str(row.get("email", "")).strip()
        role = str(row.get("role", ROLE_ACCOUNT_MANAGER)).strip()
        if countries and name and email:
            contacts.append(Contact(name=name, email=email, role=role, countries=countries))
    return ContactDirectory(tuple(contacts))
