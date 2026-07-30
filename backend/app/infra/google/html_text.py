"""HTML-to-plain-text extraction.

Some senders (marketing platforms, some corporate mail clients) send
``text/html`` only, with no ``text/plain`` alternative. The ingestion
pipeline still needs a plain-text version for search, AI prompts, and
notification previews, so this module derives one with BeautifulSoup rather
than leaving it null.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

# Elements whose text content is not part of the readable message body.
_STRIP_TAGS = ("script", "style", "head", "title")


def html_to_text(html: str) -> str:
    """Extract readable plain text from an HTML email body.

    Args:
        html: Raw HTML body content.

    Returns:
        Whitespace-normalized plain text with script/style content removed.
        A single space separates each source text node -- ``get_text()``
        with a literal newline separator would insert a line break between
        every tag, including inline ones (``<b>``, ``<a>``, ...), fragmenting
        ordinary sentences; collapsing everything to single-space-joined
        words is simpler and avoids that. Returns an empty string for empty
        or whitespace-only input.
    """
    if not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    text = soup.get_text(separator=" ")
    return " ".join(text.split())
