"""The native asyncio worker (see docs/adr/ADR-003-event-transport.md for why not
Celery/Dramatiq): BRPOPs task ids off the Redis queue and runs
`mission_engine.engine.task_executor.execute_task` for each one.
"""
