"""
Tests for foundation/logger.py.
Verifies market tagging, file creation, and that different markets produce distinct loggers.
"""

import time
from pathlib import Path

import pytest


class TestGetLogger:
    def test_returns_usable_logger(self):
        from foundation.logger import get_logger

        log = get_logger("us", "test_module")
        assert log is not None
        # Should not raise
        log.debug("debug message")
        log.info("info message")
        log.warning("warning message")

    def test_us_and_india_loggers_are_distinct(self):
        from foundation.logger import get_logger

        us_log = get_logger("us", "fetcher")
        india_log = get_logger("india", "fetcher")
        # Bound loggers with different extras — not the same object
        assert us_log is not india_log

    def test_same_market_module_returns_consistent_logger(self):
        from foundation.logger import get_logger

        log1 = get_logger("us", "validator")
        log2 = get_logger("us", "validator")
        # Both should work without errors
        log1.info("first call")
        log2.info("second call")

    def test_log_file_created_for_market(self):
        from foundation.logger import get_logger

        log = get_logger("us", "ci_test_module")
        log.info("creating log file")

        # Give loguru's async enqueue a moment to flush
        time.sleep(0.2)

        log_file = Path("logs/us/ci_test_module.log")
        assert log_file.exists(), f"Expected log file at {log_file}"

    def test_log_file_created_for_india(self):
        from foundation.logger import get_logger

        log = get_logger("india", "ci_test_fetcher")
        log.info("India log test")

        time.sleep(0.2)

        log_file = Path("logs/india/ci_test_fetcher.log")
        assert log_file.exists(), f"Expected log file at {log_file}"

    def test_multiple_markets_get_separate_directories(self):
        from foundation.logger import get_logger

        get_logger("us", "dir_test").info("us log")
        get_logger("india", "dir_test").info("india log")

        time.sleep(0.2)

        assert Path("logs/us").is_dir()
        assert Path("logs/india").is_dir()
