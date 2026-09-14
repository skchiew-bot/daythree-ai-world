FROM python:3.12-slim
WORKDIR /repo

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY packages ./packages
COPY services ./services

ENV PYTHONPATH=/repo/packages:/repo/packages/policy-sdk:/repo/packages/tool-sdk:/repo/services:/repo/services/mission-engine:/repo/services/agent-runtime:/repo/services/model-gateway:/repo/services/event-service:/repo/services/artifact-service

CMD ["python", "-m", "worker.main"]
