"""Azure Functions entry point (Python v2 programming model).

Phase 2: fn_webhook_receiver, HTTP trigger at POST /api/crm.
Phase 3 adds fn_lead_enricher, the Service Bus trigger on sbq-lead-delay.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

import azure.functions as func

from leadflow import logs
from leadflow.config import Settings
from leadflow.delay_queue import ServiceBusScheduler
from leadflow.receiver import handle_webhook
from leadflow.storage import AzureBlobStore

app = func.FunctionApp()
logger = logging.getLogger("leadflow.function_app")


@lru_cache(maxsize=1)
def _settings() -> Settings:
    return Settings.from_env()


@lru_cache(maxsize=1)
def _store() -> AzureBlobStore:
    return AzureBlobStore(_settings().storage_account_url)


@lru_cache(maxsize=1)
def _scheduler() -> ServiceBusScheduler:
    s = _settings()
    return ServiceBusScheduler(s.servicebus_fqdn, s.servicebus_queue)


def _json_response(status_code: int, body: dict) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(body), status_code=status_code, mimetype="application/json")


@app.function_name("fn_webhook_receiver")
@app.route(route="crm", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def fn_webhook_receiver(req: func.HttpRequest) -> func.HttpResponse:
    """Receive a Close webhook, store it in the source container, schedule enrichment."""
    body = req.get_body()
    headers = {k: v for k, v in req.headers.items()}
    try:
        result = handle_webhook(body, headers, _settings(), _store(), _scheduler())
    except Exception as exc:  # noqa: BLE001 - any failure must surface as 500 so Close retries
        logs.error(logger, "receiver_failure", error=repr(exc))
        return _json_response(500, {"status": "error", "reason": "internal error"})
    return _json_response(result.status_code, result.body)


@app.function_name("fn_health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def fn_health(req: func.HttpRequest) -> func.HttpResponse:
    """Liveness check with no side effects; reports configuration presence only."""
    s = _settings()
    return _json_response(
        200,
        {
            "status": "ok",
            "storage_configured": bool(s.storage_account_url),
            "servicebus_configured": bool(s.servicebus_fqdn),
            "verify_signature": s.verify_signature,
            "delay_minutes": s.delay_minutes,
        },
    )
