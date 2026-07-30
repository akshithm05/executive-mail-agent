"""A real ASGI server standing in for Google's OAuth and Gmail APIs in tests.

This is not a set of ``unittest.mock`` stubs. It is a small FastAPI
application that implements the actual wire contracts our client code talks
to -- form-encoded token requests, base64url-encoded Gmail message payloads,
``pageToken`` pagination, 409-on-duplicate-label, real HTTP status codes and
JSON error shapes. Tests wire it in by pointing the app's shared
``httpx.AsyncClient`` at this app via ``httpx.ASGITransport`` instead of a
real socket, so every byte our OAuth/Gmail clients send and parse is real;
only the network hop is short-circuited.

There is no way to run this suite against Google's actual production servers
in this environment: that requires a browser-driven consent flow with a real
Google account and a registered OAuth client, which cannot happen
non-interactively. This double is the closest thing to "real" that is
possible in an automated test run.
"""
