"""Blob storage, spoken as S3.

The provider targets the S3 API rather than any one implementation, so the
store behind `IDEN_S3_ENDPOINT_URL` can be SeaweedFS (what the dev compose
runs), MinIO, Garage, or AWS S3 itself without a line of this changing.

Profile photos are the first user; the biometric module's enrollment images are
the reason the abstraction is worth having at all.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Protocol

import aioboto3
from botocore.exceptions import ClientError
from fastapi import Depends

from provider.core.config import settings
from provider.core.errors import UnavailableError
from provider.core.logging import logger

if TYPE_CHECKING:
    # Type stubs, and so a dev dependency. The runtime image is built with
    # `uv sync --no-dev`, and importing this at module scope meant the provider
    # container died on start with ModuleNotFoundError. Only ever an
    # annotation, and annotations are not evaluated at runtime.
    from types_aiobotocore_s3.client import S3Client


class StorageUnavailable(UnavailableError):
    """No blob store is attached to this deployment."""

    code = "storage_unavailable"
    message = "This deployment has no file storage configured."


class Storage(Protocol):
    """What the rest of the provider needs from a blob store.

    Narrow on purpose: it is the seam the test suite substitutes, which is why
    it exists rather than the routes holding an S3 client directly.
    """

    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes | None: ...

    async def delete(self, key: str) -> None: ...


class S3Storage:
    def __init__(self) -> None:
        self._session = aioboto3.Session(
            aws_access_key_id=settings.iden_s3_access_key,
            aws_secret_access_key=settings.iden_s3_secret_key,
            region_name=settings.iden_s3_region,
        )
        self._bucket = settings.iden_s3_bucket

    # A client per call rather than one held open for the process lifetime.
    # botocore caches its service model after the first build, and these calls
    # are rare — an avatar is written once and read from the browser cache
    # thereafter — so the connection reuse is not worth the lifespan wiring.
    @asynccontextmanager
    async def _client(self) -> AsyncIterator[S3Client]:
        async with self._session.client(
            "s3", endpoint_url=settings.iden_s3_endpoint_url
        ) as client:
            yield client

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        async with self._client() as client:
            await client.put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )

    async def get(self, key: str) -> bytes | None:
        async with self._client() as client:
            try:
                response = await client.get_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if _is_missing(exc):
                    return None
                raise
            return await response["Body"].read()

    async def delete(self, key: str) -> None:
        async with self._client() as client:
            await client.delete_object(Bucket=self._bucket, Key=key)

    async def ensure_bucket(self) -> None:
        """Create the bucket when it is not there yet.

        Saves every operator the one manual step that would otherwise stand
        between `docker compose up` and a working deployment.
        """
        async with self._client() as client:
            try:
                await client.head_bucket(Bucket=self._bucket)
                return
            except ClientError as exc:
                if not _is_missing(exc):
                    raise
            await client.create_bucket(Bucket=self._bucket)
            logger.info("Created blob storage bucket", bucket=self._bucket)


def _is_missing(exc: ClientError) -> bool:
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return status == 404


_storage = S3Storage() if settings.blob_storage_configured else None


def get_storage() -> Storage:
    if _storage is None:
        raise StorageUnavailable
    return _storage


StorageDep = Depends(get_storage)


def get_optional_storage() -> Storage | None:
    """For a route that only sometimes touches the store — deleting a client
    whose logo may not exist — and must not fail where there is no store."""
    return _storage


OptionalStorageDep = Depends(get_optional_storage)


async def ensure_ready() -> None:
    """Create the bucket at startup, when there is a store to create it in.

    Failure is logged, not raised. A photo store that is unreachable must not
    stop an identity provider from signing tokens; the photo endpoints report
    it when someone actually asks for one.
    """
    if _storage is None:
        return
    try:
        await _storage.ensure_bucket()
    except (ClientError, OSError) as exc:
        logger.warning("Blob storage unreachable at startup", error=str(exc))
