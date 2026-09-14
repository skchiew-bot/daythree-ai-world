"""Shared, versioned contracts: IDs, enums, the event envelope, and cross-service DTOs.

Nothing in this package talks to a database, a queue, or a network. Every other
package/service in the repo may import from here; this package imports from nothing
in the repo (see spec §4 rule 6/7/8 — runtime/provider/transport are all replaceable,
which only holds if the contracts they satisfy don't depend on them).
"""
