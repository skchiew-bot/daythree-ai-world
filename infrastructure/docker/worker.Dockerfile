FROM python:3.12-slim
WORKDIR /repo

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY packages ./packages
COPY services ./services

ENV PYTHONPATH=/repo/packages:/repo/packages/policy-sdk:/repo/packages/tool-sdk:/repo/services:/repo/services/mission-engine:/repo/services/agent-runtime:/repo/services/model-gateway:/repo/services/event-service:/repo/services/artifact-service
# Without this, Python block-buffers stdout when it isn't a tty (true for any
# piped Docker log), so structlog output — including exception tracebacks —
# can sit unflushed and simply never appear in `docker compose logs`. Found by
# CI: a worker task failure produced zero diagnostic output because the only
# thing ever flushed was the startup log line.
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "worker.main"]
