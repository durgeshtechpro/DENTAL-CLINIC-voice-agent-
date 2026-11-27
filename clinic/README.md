# clinic

The mock clinic. `check_slots` and `book_slot` read and write a real SQLite table. Booking a slot that is already taken returns a conflict, and the agent says so.

```powershell
.\.venv\Scripts\python.exe -m uvicorn clinic.main:app --host 127.0.0.1 --port 8001
```

Health check: `GET /health`.
