"""Artifact Service: object storage (MinIO/S3), metadata, hashing, versioning, and the
idempotent-commit reconciliation logic (spec §14) that stops a retried task from ever
producing two committed artifacts for the same output slot.
"""
