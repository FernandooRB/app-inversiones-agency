"""Unexpected analysis failures must not disclose uploaded values in logs."""

import logging

from safe_logging import log_unexpected_analysis_error


def test_unexpected_error_log_omits_private_exception_text_and_traceback(caplog):
    logger = logging.getLogger("portfolio.audit.test")
    with caplog.at_level(logging.ERROR, logger=logger.name):
        try:
            raise ValueError("PRIVATE_CANARY_ACCOUNT_12345678")
        except ValueError as exc:
            log_unexpected_analysis_error(logger, exc)

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert "ValueError" in record.getMessage()
    assert "PRIVATE_CANARY" not in record.getMessage()
    assert record.exc_info is None
