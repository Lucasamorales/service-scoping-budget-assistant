"""Who the live emails reach.

The addresses are configuration, but the routing is a decision: Sammy takes the
UK, France and anything outside the four countries; Gabby takes Canada and
Australia. A wrong entry here is invisible until a real request lands in the
wrong inbox, so the matrix is asserted rather than eyeballed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.store.contacts import (
    ROLE_ACCOUNT_MANAGER,
    ROLE_COUNTRY_MANAGER,
    load_contacts,
)

PRODUCTION = Path("fixtures/contacts/production.json")

SAMMY = "samantha@example.com"
LENNY = "gabriel.robinson@example.com"


@pytest.fixture(scope="module")
def directory():
    return load_contacts(PRODUCTION)


@pytest.mark.parametrize(
    ("country", "email"),
    [
        ("United Kingdom", SAMMY),
        ("UK", SAMMY),
        ("England", SAMMY),
        ("Scotland", SAMMY),
        ("Wales", SAMMY),
        ("France", SAMMY),
        ("International", SAMMY),
        ("Canada", LENNY),
        ("Australia", LENNY),
    ],
)
@pytest.mark.parametrize("role", [ROLE_ACCOUNT_MANAGER, ROLE_COUNTRY_MANAGER])
def test_each_country_reaches_the_right_person_in_both_roles(
    directory, country, email, role
) -> None:
    """Both roles, because the scope offers email the Account Manager and the
    purchase-order offer the Country Manager. A gap in either leaves a CTA that
    resolves to nobody and cannot send."""
    contact = directory.for_country(country, role=role)
    assert contact is not None, f"{country} has no {role}"
    assert contact.email == email


def test_every_country_the_assistant_offers_can_be_emailed(directory) -> None:
    """The buttons on the country question come from this matrix, so an offered
    country with no recipient would be a dead end the user picked themselves."""
    offered = directory.selectable_countries()
    assert set(offered) == {
        "United Kingdom",
        "France",
        "Canada",
        "Australia",
        "International",
    }
    for country in offered:
        assert directory.for_country(country) is not None


def test_a_country_outside_the_matrix_still_has_somewhere_to_go(directory) -> None:
    """Unknown countries resolve to nobody by design — the assistant asks. What
    matters is that the answer it offers, International, reaches a person."""
    assert directory.for_country("Germany") is None
    assert directory.match_country("we're international") == "International"
    assert directory.for_country("International") is not None


def test_the_default_matrix_is_not_the_live_one() -> None:
    """Production is reached by CONTACTS_PATH at deploy time. If the default ever
    became the live file, every local run and test could email real people."""
    from app.core.config import Settings

    assert Settings().contacts_path != PRODUCTION
