# API Reference

Spec §16 requires the OpenAPI schema to be generated automatically rather than
hand-written — it is. Once the API is running:

- Interactive docs (Swagger UI): http://localhost:8000/docs
- Raw OpenAPI schema: http://localhost:8000/openapi.json
- ReDoc: http://localhost:8000/redoc

There is no separate hand-maintained API reference in this repository to avoid it
drifting out of sync with `services/api/routes/` — the running app is the source of
truth.
