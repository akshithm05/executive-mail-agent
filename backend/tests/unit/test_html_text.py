"""Tests for BeautifulSoup-based HTML-to-plain-text extraction."""

from app.infra.google.html_text import html_to_text


def test_strips_script_and_style_content() -> None:
    html = (
        "<html><head><style>.a{color:red}</style></head>"
        "<body><script>track();</script><p>Hello</p></body></html>"
    )
    assert html_to_text(html) == "Hello"


def test_normalizes_whitespace_and_blank_lines() -> None:
    html = "<div>  Hello   </div>\n\n<div></div>\n<p>World</p>"
    assert html_to_text(html) == "Hello World"


def test_empty_input_returns_empty_string() -> None:
    assert html_to_text("") == ""
    assert html_to_text("   \n  ") == ""


def test_preserves_nested_inline_formatting_as_text() -> None:
    html = "<p>Save <b>20%</b> today.</p>"
    assert html_to_text(html) == "Save 20% today."
