# ADR-006: Object Storage

## Context

Spec §5/§23/§25 call for an S3-compatible object store for artifacts, private by
default, with signed download URLs and no public buckets. Phase 0's local stack uses
MinIO; a hosted deployment would use a real S3-compatible provider.

## Options Considered

1. **MinIO locally, any S3-compatible provider in hosted environments**, accessed via
   `aioboto3` (async boto3) behind a small `ObjectStore` class
   (`services/artifact-service/artifact_service/storage/object_store.py`).
2. Store artifact bytes directly in Postgres (`bytea` column).
3. Local filesystem storage (bind-mounted volume) instead of an object store.

## Decision

Option 1: MinIO/S3-compatible storage via `aioboto3`, private bucket, presigned GET URLs
with a configurable TTL (`OBJECT_STORE_SIGNED_URL_TTL_SECONDS`, default 300s).

## Rationale

- Spec §6 explicitly lists "S3-compatible object storage" as the Phase 0 infrastructure
  choice and §25's compose topology includes `minio` — this ADR mainly records *why*,
  not a deviation.
- Storing artifact bytes in Postgres (option 2) would work for Phase 0's small text
  artifacts but violates the general principle that the relational database should hold
  metadata and state, not blob payloads — and would make "artifact not marked complete /
  task remains retryable" (spec §15, object storage failure) impossible to express
  cleanly, since a failed blob write and a failed metadata write would be the same
  operation.
- Local filesystem storage (option 3) doesn't survive a container being recreated
  without an explicit volume, and doesn't naturally support the "signed URL" requirement
  spec §23 states — MinIO gives that (and the real S3 API) for free.
- `aioboto3` (not `boto3`) was chosen so `ObjectStore.put_object`/`get_object`/
  `generate_presigned_download_url` are `async def`, matching the rest of the async
  stack instead of blocking the event loop on every artifact read/write.

## Consequences

- One more container in the local Docker Compose stack (`minio` + a one-shot `minio-init`
  that creates the bucket and sets it fully private).
- The presigned-URL TTL is a single global setting, not per-artifact or per-role —
  acceptable at Phase 0 scale; a stricter access model (per-download audit logging of who
  fetched what, shorter TTLs for higher `risk_level` missions) is a reasonable Phase 1
  addition once there's a real access-review requirement.

## Rollback Path

Swap `ObjectStoreConfig.endpoint_url`/credentials to point at any other S3-compatible
provider (AWS S3, Cloudflare R2, Backblaze B2) — no code change, since `ObjectStore` only
uses the generic S3 API surface (`put_object`, `get_object`, `generate_presigned_url`).
