# Bright Smile desk

This folder is the Bright Smile browser desk. It has the landing page, Start call, and the call dashboard.

## Run it locally

From this folder:

```powershell
copy .env.example .env.local
npm install
npm run dev
```

Open http://localhost:3000. Put `API_BASE_URL` and `API_KEY` in `.env.local`. The browser never sees the key.

The live site is https://dental-clinic-voice-agent-six.vercel.app.
