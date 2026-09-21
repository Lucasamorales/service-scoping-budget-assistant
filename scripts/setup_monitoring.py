"""Create the uptime checks, log metrics and alert policies for the service.

    python -m scripts.setup_monitoring
    python -m scripts.setup_monitoring --email ops@example.com
    python -m scripts.setup_monitoring --dry-run

Idempotent: every object is looked up by display name first, so re-running
reconciles rather than duplicating. Written as a script rather than clicked
into the console because an alert nobody can review, reproduce or move to
another project is barely better than no alert.

What it watches, and why each one is here:

``status``
    The service is up *and* answering. A content match on the health body,
    not just a 200, so a process that starts but cannot serve is still a
    failure.

``budget``
    ``/api/health`` reports ``budget: true`` only while the Google Sheet is
    readable. Unshare the sheet and the service stays up, returns 200, and
    quietly stops being able to answer any budget question. Nothing else in
    the system would notice.

``embeddings``
    Reports ``embeddings: true`` only when the shipped index carries vectors.
    A deploy built without them looks entirely healthy and silently reverts
    retrieval to the narrower keyword-only mode — which is exactly what was
    live, undetected, until 27 Aug.

``guard violations``
    The model contradicting the facts it was given. Every occurrence already
    logs ``wording.guard_violation``; this turns that into a metric somebody
    is told about.

``turn cost``
    Tokens per turn, from ``pipeline.answered``. Recorded as a metric now so
    there is a baseline to alert against later; a threshold picked before any
    data exists would be a guess.

Uses the REST API through a gcloud access token: the ``beta`` component that
owns ``gcloud monitoring channels`` is not installed everywhere, and needs
admin rights to add.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_PROJECT = "your-gcp-project"
DEFAULT_SERVICE_URL = "https://your-service-url.a.run.app"
DEFAULT_EMAILS = ("robin@example.com", "charlie@example.com")
"""Who is paged. More than one on purpose: an alert with a single recipient
goes quiet whenever that person is on leave, and nothing else is watching
this service."""

MONITORING = "https://monitoring.googleapis.com/v3"
LOGGING = "https://logging.googleapis.com/v2"

# Four regions, so one flaky vantage point cannot page anybody on its own.
REGIONS = ["USA_OREGON", "USA_IOWA", "EUROPE", "SOUTH_AMERICA"]

CHANNEL_NAME = "Acme scoping — email"
"""A prefix now, not the whole name: one channel per address, each suffixed
with that address, so adding a recipient never rewrites an existing one."""

# Each health flag worth watching, with the substring that proves it.
HEALTH_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "Acme scoping — service answering",
        '"status":"ok"',
        "The service is down, or up but unable to answer.",
    ),
    (
        "Acme scoping — budget sheet readable",
        '"budget":true',
        "The Google Sheet is no longer readable. Every budget question is broken, "
        "and the service looks healthy from outside.",
    ),
    (
        "Acme scoping — embeddings present",
        '"embeddings":true',
        "The deployed index carries no vectors. Retrieval has silently dropped to "
        "keyword-only; scope answers get worse without anything failing.",
    ),
)


def token() -> str:
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        shell=sys.platform == "win32",
    )
    if result.returncode != 0:
        raise SystemExit(
            "Could not get a gcloud access token. Run `gcloud auth login` first.\n"
            + result.stderr.strip()
        )
    return result.stdout.strip()


class Api:
    """Thin REST client that reports what it did rather than what it sent."""

    def __init__(self, project: str, *, dry_run: bool) -> None:
        self.project = project
        self.dry_run = dry_run
        self.deferred: list[str] = []
        self._headers = {
            "Authorization": f"Bearer {token()}",
            "Content-Type": "application/json",
        }

    def get(self, url: str) -> dict[str, Any]:
        response = httpx.get(url, headers=self._headers, timeout=30.0)
        response.raise_for_status()
        return dict(response.json())

    def patch(
        self, url: str, body: dict[str, Any], *, mask: str, what: str
    ) -> dict[str, Any] | None:
        if self.dry_run:
            print(f"  would update  {what}")
            return None
        response = httpx.patch(
            url,
            headers=self._headers,
            params={"updateMask": mask},
            json=body,
            timeout=60.0,
        )
        if response.status_code >= 400:
            raise SystemExit(f"Updating {what} failed ({response.status_code}):\n{response.text}")
        print(f"  updated       {what}")
        return dict(response.json())

    def post(self, url: str, body: dict[str, Any], *, what: str) -> dict[str, Any] | None:
        if self.dry_run:
            print(f"  would create  {what}")
            return None
        response = httpx.post(url, headers=self._headers, json=body, timeout=60.0)
        if response.status_code >= 400:
            raise SystemExit(f"Creating {what} failed ({response.status_code}):\n{response.text}")
        print(f"  created       {what}")
        return dict(response.json())


def ensure_channels(api: Api, emails: Sequence[str]) -> list[str]:
    """The addresses alerts go to. Every policy references all of them.

    Matched on the address rather than the display name, so the single channel
    created when there was one recipient is adopted instead of duplicated.
    """
    existing = api.get(f"{MONITORING}/projects/{api.project}/notificationChannels")
    by_email = {
        channel.get("labels", {}).get("email_address"): str(channel["name"])
        for channel in existing.get("notificationChannels", [])
        if channel.get("type") == "email"
    }
    names: list[str] = []
    for email in emails:
        found = by_email.get(email)
        if found:
            print(f"  exists        notification channel -> {email}")
            names.append(found)
            continue
        created = api.post(
            f"{MONITORING}/projects/{api.project}/notificationChannels",
            {
                "type": "email",
                "displayName": f"{CHANNEL_NAME} ({email})",
                "description": "Alerts for the Acme scoping assistant.",
                "labels": {"email_address": email},
                "enabled": True,
            },
            what=f"notification channel -> {email}",
        )
        if created:
            names.append(str(created["name"]))
    return names


def ensure_uptime_check(api: Api, host: str, display: str, content: str) -> str | None:
    """One check per health flag. A content matcher is what makes a 200 mean
    something: the body says which parts of the system are still working."""
    existing = api.get(f"{MONITORING}/projects/{api.project}/uptimeCheckConfigs")
    for config in existing.get("uptimeCheckConfigs", []):
        if config.get("displayName") == display:
            print(f"  exists        uptime check '{display}'")
            return str(config["name"])
    created = api.post(
        f"{MONITORING}/projects/{api.project}/uptimeCheckConfigs",
        {
            "displayName": display,
            "monitoredResource": {
                "type": "uptime_url",
                "labels": {"host": host, "project_id": api.project},
            },
            "httpCheck": {
                "path": "/api/health",
                "port": 443,
                "useSsl": True,
                "validateSsl": True,
                "requestMethod": "GET",
            },
            "period": "300s",
            "timeout": "10s",
            "contentMatchers": [{"content": content, "matcher": "CONTAINS_STRING"}],
            "selectedRegions": REGIONS,
        },
        what=f"uptime check '{display}' matching {content}",
    )
    return str(created["name"]) if created else None


def ensure_log_metric(api: Api, name: str, description: str, filter_: str, **extra: Any) -> None:
    try:
        api.get(f"{LOGGING}/projects/{api.project}/metrics/{name}")
        print(f"  exists        log metric '{name}'")
        return
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
    api.post(
        f"{LOGGING}/projects/{api.project}/metrics",
        {"name": name, "description": description, "filter": filter_, **extra},
        what=f"log metric '{name}'",
    )


def ensure_policy(api: Api, display: str, body: dict[str, Any]) -> None:
    """Create the policy, or bring an existing one's recipients up to date.

    Only the recipient list is reconciled, not the condition: a threshold someone
    tuned by hand in the console is theirs to keep. Recipients are different —
    adding an address to this script and finding the alerts still go to one
    person is how an on-call list quietly stops being true.
    """
    existing = api.get(f"{MONITORING}/projects/{api.project}/alertPolicies")
    wanted = list(body.get("notificationChannels", []))
    for policy in existing.get("alertPolicies", []):
        if policy.get("displayName") == display:
            if sorted(policy.get("notificationChannels", [])) != sorted(wanted):
                api.patch(
                    f"{MONITORING}/{policy['name']}",
                    {"notificationChannels": wanted},
                    mask="notificationChannels",
                    what=f"alert policy '{display}' recipients",
                )
            else:
                print(f"  exists        alert policy '{display}'")
            return
    api.post(
        f"{MONITORING}/projects/{api.project}/alertPolicies",
        {"displayName": display, **body},
        what=f"alert policy '{display}'",
    )


def uptime_policy(
    check_id: str, display: str, why: str, channels: Sequence[str]
) -> dict[str, Any]:
    """Page when a check fails from several places at once.

    Two consecutive failures rather than one: a single missed probe from one
    region is normal internet weather, and an alert that cries wolf is an
    alert people mute.
    """
    return {
        "documentation": {"content": why, "mimeType": "text/markdown"},
        "combiner": "OR",
        "conditions": [
            {
                "displayName": f"{display} failing",
                "conditionThreshold": {
                    "filter": (
                        'metric.type="monitoring.googleapis.com/uptime_check/check_passed" '
                        'AND resource.type="uptime_url" '
                        f'AND metric.label.check_id="{check_id}"'
                    ),
                    "aggregations": [
                        {
                            "alignmentPeriod": "300s",
                            "perSeriesAligner": "ALIGN_NEXT_OLDER",
                            "crossSeriesReducer": "REDUCE_COUNT_FALSE",
                            "groupByFields": ["resource.label.host"],
                        }
                    ],
                    "comparison": "COMPARISON_GT",
                    "thresholdValue": 1,
                    "duration": "300s",
                    "trigger": {"count": 1},
                },
            }
        ],
        "notificationChannels": list(channels),
        "alertStrategy": {"autoClose": "1800s"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--service-url", default=DEFAULT_SERVICE_URL)
    parser.add_argument(
        "--email",
        action="append",
        help="Where alerts are sent. Repeatable; defaults to the team addresses.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would be created and stop."
    )
    args = parser.parse_args()

    host = urlparse(args.service_url).netloc
    if not host:
        raise SystemExit(f"--service-url must be absolute, got {args.service_url!r}")

    emails = tuple(args.email) if args.email else DEFAULT_EMAILS
    api = Api(args.project, dry_run=args.dry_run)
    print(f"Project: {args.project}\nService: {host}\nAlerts:  {', '.join(emails)}\n")

    channels = ensure_channels(api, emails)

    for display, content, why in HEALTH_CHECKS:
        name = ensure_uptime_check(api, host, display, content)
        if name:
            check_id = name.rsplit("/", 1)[-1]
            ensure_policy(
                api,
                f"{display} — alert",
                uptime_policy(check_id, display, why, channels),
            )

    ensure_log_metric(
        api,
        "acme_guard_violations",
        "Replies discarded because they contradicted the facts they were given.",
        'resource.type="cloud_run_revision" AND jsonPayload.event="wording.guard_violation"',
    )
    ensure_policy(
        api,
        "Acme scoping — model contradicting the facts",
        {
            "documentation": {
                "content": (
                    "The composer produced a reply that disagreed with the looked-up "
                    "verdict or invented a figure, and it was discarded. Users saw the "
                    "deterministic wording instead, so nothing wrong was shown — but a "
                    "run of these means the model or the briefing has drifted."
                ),
                "mimeType": "text/markdown",
            },
            "combiner": "OR",
            "conditions": [
                {
                    "displayName": "guard violations in an hour",
                    "conditionThreshold": {
                        "filter": (
                            'metric.type="logging.googleapis.com/user/acme_guard_violations" '
                            'AND resource.type="cloud_run_revision"'
                        ),
                        "aggregations": [
                            {"alignmentPeriod": "3600s", "perSeriesAligner": "ALIGN_SUM"}
                        ],
                        "comparison": "COMPARISON_GT",
                        "thresholdValue": 5,
                        "duration": "0s",
                        "trigger": {"count": 1},
                    },
                }
            ],
            "notificationChannels": list(channels),
            "alertStrategy": {"autoClose": "3600s"},
        },
    )

    # The gap this closes: `budget: true` in the health body is decided once at
    # startup and never changes, so the uptime check above cannot see a sheet
    # that becomes unreadable later. The service stays up, keeps answering, and
    # serves figures that get quietly older — which for a spend balance is the
    # worst of the failure modes, because the answer still looks like an answer.
    ensure_log_metric(
        api,
        "acme_sheet_refresh_failures",
        "Budget or rate-card refreshes that could not re-read the spreadsheet.",
        'resource.type="cloud_run_revision" AND '
        '(jsonPayload.event="budget.refresh_failed" OR '
        'jsonPayload.event="quote.refresh_failed")',
    )
    ensure_policy(
        api,
        "Acme scoping — spreadsheet refresh failing",
        {
            "documentation": {
                "content": (
                    "The service can no longer re-read the spreadsheet, and is "
                    "serving the last figures it managed to load. Budget balances "
                    "and quoted prices are both stale and getting staler; the "
                    "health endpoint still reports ok, because the stores were "
                    "built successfully at startup. "
                    "Check `budgetAgeSeconds` and `quoteAgeSeconds` on /api/health "
                    "to see how far behind they are. The usual cause is the Sheet "
                    "being unshared from the runtime service account."
                ),
                "mimeType": "text/markdown",
            },
            "combiner": "OR",
            "conditions": [
                {
                    "displayName": "refresh failures in half an hour",
                    "conditionThreshold": {
                        "filter": (
                            "metric.type="
                            '"logging.googleapis.com/user/acme_sheet_refresh_failures" '
                            'AND resource.type="cloud_run_revision"'
                        ),
                        "aggregations": [
                            {"alignmentPeriod": "1800s", "perSeriesAligner": "ALIGN_SUM"}
                        ],
                        # Two, not one: a single failed read is a blip the next
                        # refresh fixes by itself, and paging on it teaches
                        # people to ignore the alert.
                        "comparison": "COMPARISON_GT",
                        "thresholdValue": 1,
                        "duration": "0s",
                        "trigger": {"count": 1},
                    },
                }
            ],
            "notificationChannels": list(channels),
            "alertStrategy": {"autoClose": "3600s"},
        },
    )

    # Recorded, not alerted on. A threshold chosen before any data exists is a
    # guess, and a guessed threshold is how alerting gets switched off.
    ensure_log_metric(
        api,
        "acme_turn_tokens",
        "Gemini tokens per turn, planning and wording together.",
        'resource.type="cloud_run_revision" AND jsonPayload.event="pipeline.answered"',
        valueExtractor="EXTRACT(jsonPayload.tokens)",
        metricDescriptor={
            "metricKind": "DELTA",
            "valueType": "DISTRIBUTION",
            "unit": "1",
            "displayName": "Acme turn tokens",
        },
        bucketOptions={
            "exponentialBuckets": {
                "numFiniteBuckets": 16,
                "growthFactor": 2,
                "scale": 100,
            }
        },
    )

    print("\nDone. Review at:")
    print(f"  https://console.cloud.google.com/monitoring/alerting?project={args.project}")
    print(f"  https://console.cloud.google.com/monitoring/uptime?project={args.project}")
    if args.dry_run:
        print("\n(dry run — nothing was created)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
