"""Minimal error logging for analyses that may include private client data."""

import logging


def log_unexpected_analysis_error(logger: logging.Logger, error: Exception) -> None:
    """Record the failure class without exception text or a traceback.

    Parser and library exceptions can contain uploaded values in their messages.
    The user sees a generic error; operational logs should contain no client input.
    """
    logger.error("Unexpected portfolio analysis error (%s)", type(error).__name__)
