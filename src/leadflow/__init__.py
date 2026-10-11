"""leadflow: application modules for the CRM lead processing pipeline.

Modules
    config      Settings read from environment variables (Function App settings locally
                mirrored by local.settings.json or .env)
    models      Typed view of a Close webhook event and the scheduled message
    verify      Close webhook signature verification
    storage     ADLS Gen2 (blob) read and write helpers
    delay_queue Service Bus scheduling helper
    receiver    Pure request-handling logic for the webhook receiver (unit tested)
    lookup      Lead-owner lookup over HTTPS (403/404 = not available)
    enrich      Enriched record schema (Section 4.2) and target naming
    notify      Slack New Lead Alert (Block Kit)
    enricher    Pure logic for the enrichment step (unit tested)
    logs        Structured logging helper
"""

__version__ = "0.4.0"
