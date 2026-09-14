FROM python:3.12-slim
WORKDIR /repo

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY packages ./packages
COPY services ./services
COPY infrastructure/migrations ./infrastructure/migrations
COPY alembic.ini .

ENV PYTHONPATH=/repo/packages:/repo/packages/policy-sdk:/repo/packages/tool-sdk:/repo/services:/repo/services/mission-engine:/repo/services/agent-runtime:/repo/services/model-gateway:/repo/services/event-service:/repo/services/artifact-service

EXPOSE 8000
CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
