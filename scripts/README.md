# scripts

Three reports. They use only the Python standard library and httpx. Set `API_BASE_URL` and `API_KEY` in the shell first. They do not read `.env`.

| Script | Writes |
| --- | --- |
| `latency_report.py` | `data/latency-report.md` |
| `cost_model.py` | `data/cost-model.md` |
| `export_calls.py` | `data/call-exports/<id>.json` and `data/calls-summary.md` |
