"""Pure domain logic: tool-permission evaluation and budget evaluation.

Nothing here touches a database or the network — every function takes plain data in
and returns a plain, deterministic decision out. That's what makes spec §27's ">=80%
coverage for core domain logic" target actually cheap to hit honestly.
"""
