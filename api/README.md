# api

The call API. It creates the LiveKit room, stores each call in SQLite, prices the call from `pricing.json`, and sends the signed webhook.

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Health check: `GET /health`. Every other route needs the `X-API-Key` header.
