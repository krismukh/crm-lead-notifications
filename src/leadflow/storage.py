"""ADLS Gen2 (blob) access through the managed identity.

Locally, DefaultAzureCredential falls back to the Azure CLI login, so the same code runs
on the workstation after `az login` provided the user holds Storage Blob Data Contributor.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings


class BlobStore(Protocol):
    """Interface used by the handlers; satisfied by AzureBlobStore and by test fakes."""

    def write_json(
        self, container: str, name: str, payload: dict[str, Any], metadata: dict[str, str]
    ) -> str: ...

    def read_json(self, container: str, name: str) -> dict[str, Any] | None: ...

    def exists(self, container: str, name: str) -> bool: ...


class AzureBlobStore:
    def __init__(self, account_url: str, credential: Any | None = None) -> None:
        self._client = BlobServiceClient(
            account_url, credential=credential or DefaultAzureCredential()
        )

    def write_json(
        self, container: str, name: str, payload: dict[str, Any], metadata: dict[str, str]
    ) -> str:
        blob = self._client.get_blob_client(container=container, blob=name)
        data = json.dumps(payload, indent=2).encode("utf-8")
        blob.upload_blob(
            data,
            overwrite=True,
            metadata=metadata,
            content_settings=ContentSettings(content_type="application/json"),
        )
        return f"{container}/{name}"

    def read_json(self, container: str, name: str) -> dict[str, Any] | None:
        blob = self._client.get_blob_client(container=container, blob=name)
        try:
            return json.loads(blob.download_blob().readall())
        except ResourceNotFoundError:
            return None

    def exists(self, container: str, name: str) -> bool:
        return self._client.get_blob_client(container=container, blob=name).exists()


class MemoryBlobStore:
    """In-memory store for unit tests and the --dry-run mode of scripts."""

    def __init__(self) -> None:
        self.blobs: dict[tuple[str, str], dict[str, Any]] = {}
        self.metadata: dict[tuple[str, str], dict[str, str]] = {}

    def write_json(
        self, container: str, name: str, payload: dict[str, Any], metadata: dict[str, str]
    ) -> str:
        self.blobs[(container, name)] = payload
        self.metadata[(container, name)] = metadata
        return f"{container}/{name}"

    def read_json(self, container: str, name: str) -> dict[str, Any] | None:
        return self.blobs.get((container, name))

    def exists(self, container: str, name: str) -> bool:
        return (container, name) in self.blobs
