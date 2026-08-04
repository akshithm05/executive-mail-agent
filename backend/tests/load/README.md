# Load testing

Load tests live outside the pytest suite (`tests/unit`, `tests/integration`)
because they exercise the API concurrently against a *running* deployment
(local docker-compose or staging), not an in-process fixture -- they answer
"how does this behave under concurrent load", not "is this logic correct".

## What's covered

- `locustfile.py` -- two [Locust](https://locust.io) user classes:
  - `AnonymousUser` -- health-check + metrics-scrape traffic (what a load
    balancer and Prometheus actually generate).
  - `AuthenticatedDashboardUser` -- the polling behavior of a logged-in
    frontend session: dashboard summary, analytics widgets, inbox/task/
    notification lists. These are exactly the endpoints Phase 14 put behind
    Redis caching (`app/api/cache_utils.py`) and the rate-limiting
    middleware, so this is what actually proves that work holds up under
    concurrency -- the automated test suite (`tests/integration/
    test_response_caching.py`, `test_rate_limit.py`) already proves the
    *logic* is correct; this proves the *behavior under load* is acceptable.

## Prerequisites

1. A running stack to point at -- either the local docker-compose stack
   (`make up` from `backend/`, or `docker compose -f infra/docker-compose.yml
   up --build`) or a real staging/production URL.
2. A logged-in session. This API only supports Google OAuth login, which
   needs a real consent screen and can't be scripted by Locust -- log in
   once by hand and reuse the resulting cookies:
   1. Open `http://localhost:8000/api/v1/auth/google/login` in a browser
      (or the deployment's equivalent URL) and complete the Google consent
      flow.
   2. Open your browser's dev tools -> Application/Storage -> Cookies, and
      copy the values of the `aeea_session` and `aeea_csrf_token` cookies.
3. Install the load-testing dependencies (kept separate from
   `requirements-dev.txt` -- Locust pulls in gevent/Flask, which the app
   and its test suite don't need):

   ```bash
   pip install -r tests/load/requirements-load.txt
   ```

## Running

Interactive (opens a web UI at `http://localhost:8089` to set user count,
spawn rate, and watch live charts):

```bash
export AEEA_SESSION_COOKIE="<value of the aeea_session cookie>"
export AEEA_CSRF_TOKEN="<value of the aeea_csrf_token cookie>"
locust -f tests/load/locustfile.py --host=http://localhost:8000
```

Headless, e.g. 50 users ramping up at 5/second for 2 minutes, with an HTML
report:

```bash
locust -f tests/load/locustfile.py --host=http://localhost:8000 \
  --headless --users 50 --spawn-rate 5 --run-time 2m \
  --html tests/load/report.html
```

`AnonymousUser` needs no cookies and runs even if the two environment
variables above are unset -- `AuthenticatedDashboardUser` raises immediately
on start if `AEEA_SESSION_COOKIE` is missing, so an accidental
credential-less run fails fast and loud rather than silently only measuring
health-check latency.

## Interpreting results

- **Cache effectiveness**: repeated identical requests to
  `/dashboard/summary` and `/analytics/*` should show a latency cliff after
  the first request per unique parameter set (see
  `RedisSettings.default_ttl_seconds`) -- watch the `aeea_cache_requests_total`
  Prometheus counter's `hit`/`miss` split (via the Grafana dashboard, or
  directly at `/api/v1/metrics`) climb toward mostly-hits as a run
  progresses.
- **Rate limiting**: pushing a single simulated user well past
  `RATE_LIMIT_REQUESTS_PER_WINDOW` (120/60s by default) should surface 429s
  in Locust's failure stats -- that's the middleware working as designed,
  not a bug. Raise `--users`/lower `wait_time` per user, or point at a
  higher `RATE_LIMIT_REQUESTS_PER_WINDOW`, to load-test throughput rather
  than the limiter itself.
- **P95/P99 latency** under your target concurrency is the number that
  actually matters for capacity planning -- Locust's own summary table
  reports it per endpoint; correlate spikes against the Grafana dashboard's
  HTTP request-duration panel (`aeea_http_request_duration_seconds`) for a
  server-side view of the same numbers.
