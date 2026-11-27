# agent

The voice worker. `main.py` is the LiveKit agent. It uses Deepgram for speech-to-text, Groq for the model, and Cartesia for speech.

```powershell
.\.venv\Scripts\python.exe agent\main.py dev
```

`console` talks on this computer with no phone. `start` is the LiveKit Cloud command. Tools, the FAQ lookup, and the hang-up rules live in this folder. The sample FAQ is `kb/clinic-faq.md`.
