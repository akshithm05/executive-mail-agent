"""Load test for the AEEA backend, using Locust (https://locust.io).

Two user classes model the two real traffic shapes this API sees:

* :class:`AnonymousUser` -- health checks and metrics scraping (what a load
  balancer and Prometheus actually generate), unauthenticated.
* :class:`AuthenticatedDashboardUser` -- the polling behavior of a logged-in
  frontend session: dashboard summary, analytics widgets, inbox/task lists,
  notifications. These are exactly the endpoints Phase 14 put behind Redis
  caching (see ``app/api/cache_utils.py``) and rate limiting, so this load
  test is what actually validates that work under concurrency -- unit tests
  prove the caching/rate-limiting *logic*; this proves it holds up under load.

Authentication is out of scope for Locust itself: this API only supports
Google OAuth login, which needs a real user interacting with a real Google
consent screen and can't be scripted here. Instead, log in once by hand
against the target environment and pass the resulting session + CSRF
cookies in as environment variables -- see the module docstring in
``tests/load/README.md`` for the exact steps.

Usage (see ``tests/load/README.md`` for full detail)::

    pip install -r tests/load/requirements-load.txt
    export AEEA_SESSION_COOKIE=<value of the aeea_session cookie>
    export AEEA_CSRF_TOKEN=<value of the aeea_csrf_token cookie>
    locust -f tests/load/locustfile.py --host=http://localhost:8000
"""

from __future__ import annotations

import os

from locust import HttpUser, between, task

_SESSION_COOKIE_NAME = "aeea_session"
_CSRF_COOKIE_NAME = "aeea_csrf_token"
_CSRF_HEADER_NAME = "X-CSRF-Token"


class AnonymousUser(HttpUser):
    """Unauthenticated traffic: load balancer health checks + metrics scraping."""

    weight = 1
    wait_time = between(1, 3)

    @task(5)
    def liveness(self) -> None:
        """Hit the liveness probe, as a load balancer/orchestrator would."""
        self.client.get("/api/v1/health/live", name="/health/live")

    @task(3)
    def readiness(self) -> None:
        """Hit the readiness probe (checks DB + Redis connectivity)."""
        self.client.get("/api/v1/health/ready", name="/health/ready")

    @task(1)
    def metrics(self) -> None:
        """Scrape Prometheus metrics, as Prometheus itself would every 15s."""
        self.client.get("/api/v1/metrics", name="/metrics")


class AuthenticatedDashboardUser(HttpUser):
    """A logged-in frontend session polling its dashboard and inbox.

    Requires ``AEEA_SESSION_COOKIE`` to be set -- see the module docstring.
    Every task here is read-only and safe to run repeatedly against a real
    environment.
    """

    weight = 4
    wait_time = between(2, 6)

    def on_start(self) -> None:
        """Seed this simulated user's session cookie from the environment."""
        session_cookie = os.environ.get("AEEA_SESSION_COOKIE")
        if not session_cookie:
            raise RuntimeError(
                "AEEA_SESSION_COOKIE is required -- log in once by hand against "
                "the target environment and export the resulting cookie value "
                "(see tests/load/README.md)."
            )
        self.client.cookies.set(_SESSION_COOKIE_NAME, session_cookie)
        csrf_token = os.environ.get("AEEA_CSRF_TOKEN")
        if csrf_token:
            self.client.cookies.set(_CSRF_COOKIE_NAME, csrf_token)
            self.client.headers[_CSRF_HEADER_NAME] = csrf_token

    @task(6)
    def dashboard_summary(self) -> None:
        """Poll the dashboard summary -- the highest-frequency real page load."""
        self.client.get("/api/v1/dashboard/summary", name="/dashboard/summary")

    @task(4)
    def list_inbox(self) -> None:
        """List the first page of the inbox."""
        self.client.get("/api/v1/emails?limit=25", name="/emails")

    @task(3)
    def list_tasks(self) -> None:
        """List the current user's tasks."""
        self.client.get("/api/v1/tasks", name="/tasks")

    @task(3)
    def list_notifications(self) -> None:
        """List the current user's notifications."""
        self.client.get("/api/v1/notifications", name="/notifications")

    @task(2)
    def analytics_category_distribution(self) -> None:
        """Fetch the category-distribution analytics widget."""
        self.client.get(
            "/api/v1/analytics/category-distribution?days=30",
            name="/analytics/category-distribution",
        )

    @task(2)
    def analytics_daily_emails(self) -> None:
        """Fetch the daily-email-volume analytics widget."""
        self.client.get(
            "/api/v1/analytics/daily-emails?days=30", name="/analytics/daily-emails"
        )

    @task(1)
    def analytics_unread_summary(self) -> None:
        """Fetch the unread-mail snapshot widget."""
        self.client.get(
            "/api/v1/analytics/unread-summary", name="/analytics/unread-summary"
        )

    @task(1)
    def whoami(self) -> None:
        """Fetch the current user's own profile (a cheap session-liveness check)."""
        self.client.get("/api/v1/auth/me", name="/auth/me")
