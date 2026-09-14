"""Publishes every `EventEnvelope` to two places: the `audit_events` table (durable
source of truth) and a Redis Stream (best-effort broadcast for anything that wants to
react live). See `publisher.EventPublisher` for the exact durability contract.
"""
