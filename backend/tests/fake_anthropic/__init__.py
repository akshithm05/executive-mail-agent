"""A real ASGI server standing in for the Anthropic Messages API in tests.

Verified against the installed ``anthropic`` SDK's actual source
(``AsyncMessages.parse`` and ``anthropic.lib._parse._response.parse_response``)
rather than guessed: ``messages.parse(output_format=Model)`` POSTs to
``/v1/messages`` with ``output_config.format = {"type": "json_schema",
"schema": <schema>}``, and the SDK client-side-parses the *first text
content block's* ``text`` as JSON against that schema. This double returns
real ``Message``-shaped JSON over real HTTP (via ``httpx.ASGITransport``) --
the SDK does not know it isn't talking to production.
"""
