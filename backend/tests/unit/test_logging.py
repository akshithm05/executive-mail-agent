"""Tests for logging configuration and redaction."""

from app.config.logging import _redact_sensitive, configure_logging, get_logger


def test_configure_logging_returns_usable_logger() -> None:
    configure_logging(level="INFO", fmt="console")
    logger = get_logger("test")
    # Should not raise when emitting a log line.
    logger.info("hello", key="value")


def test_redact_sensitive_masks_known_keys() -> None:
    event = {"password": "secret", "refresh_token": "t", "safe": "ok"}
    redacted = _redact_sensitive(None, "info", event)
    assert redacted["password"] == "***redacted***"
    assert redacted["refresh_token"] == "***redacted***"
    assert redacted["safe"] == "ok"
