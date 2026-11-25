Use the repo root as the service root. Set PYTHON_VERSION to 3.12.9 on both services. Render sets PORT. Do not put secret values in this file.

Call API
Build Command: pip install -r requirements-api.txt
Start Command: uvicorn api.main:app --host 0.0.0.0 --port $PORT
Health check path: /health
Environment variable names: PYTHON_VERSION, API_KEY, WEBHOOK_SECRET, LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, CORS_ORIGINS, DATA_DIR

Clinic
Build Command: pip install -r requirements-clinic.txt
Start Command: uvicorn clinic.main:app --host 0.0.0.0 --port $PORT
Health check path: /health
Environment variable names: PYTHON_VERSION, DATA_DIR
