"""Structured logging: one JSON object per line, searchable by lead_id in Application Insights."""

from __future__ import annotations

import json
import logging
from typing import Any


def log_event(logger: logging.Logger, level: int, stage: str, **fields: Any) -> None:
    record = {"stage": stage, **fields}
    logger.log(level, json.dumps(record, default=str, separators=(",", ":")))


def info(logger: logging.Logger, stage: str, **fields: Any) -> None:
    log_event(logger, logging.INFO, stage, **fields)


def warning(logger: logging.Logger, stage: str, **fields: Any) -> None:
    log_event(logger, logging.WARNING, stage, **fields)


def error(logger: logging.Logger, stage: str, **fields: Any) -> None:
    log_event(logger, logging.ERROR, stage, **fields)
