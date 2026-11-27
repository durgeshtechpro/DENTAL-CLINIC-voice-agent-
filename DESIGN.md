# Design note

## 1. Where the time goes, and the three changes that would make a reply faster

A reply is a queue. After the caller stops, the agent waits until it believes the turn is over (`endOfTurnDelayMs`). On the 20-turn browser pilot that median was 867 ms and the 95th percentile was 3003 ms, under the old 3 second maximum. Speech-to-text then adds a median 372 ms. The model adds about 440 ms to the first token. The voice adds about 70 ms to the first audio. A tool adds its own clock. Most tools were fast. One cold clinic call took about 4 seconds. The phone hop is not in these numbers. The pilot was a browser call.

Three changes, in order:

1. Keep the shorter end-of-turn maximum and measure it. It is already 1.5 seconds, down from 3.0. If callers are not cut off, this is the largest cut. A streaming turn detector is next if that fixed wait is still the slow tail.
2. Keep the clinic warm. The slow tool is a cold HTTP call, not the model. The agent already pokes the clinic at the start of a call. An always-on instance removes the first-booking stall.
3. Stay at one short sentence. The model and the voice are the small pieces. A second sentence costs another voice stream.

I would not self-host a new model to chase this. The measured model and voice are not the bottleneck.

## 2. Paid API or an open model, for each part

**Telephony.** Paid. Hosting our own SIP server does not remove the carrier minute, and it adds a night-time system. LiveKit's third-party SIP is $0.004 per minute on Ship. Our $0.012 phone column is a higher assumption until a real trunk is connected.

**Speech-to-text.** Paid streaming. Nova-3 is $0.0048 per audio minute on the current promo, and $0.0077 at the regular rate. A self-hosted Whisper is cheaper at large volume and slower to the first partial unless a GPU is already warm. At this size the speech-to-text bill is small next to the session and the voice. Latency wins.

**Model.** Paid. Groq's `gpt-oss-20b` is $0.075 / $0.30 per million tokens, and the first token is about 440 ms. Hosting the same open weights needs a warm GPU. A cold GPU makes the first reply slower. At the measured token rate the model is a few paise per minute, so cost is not the reason to self-host.

**Text-to-speech.** Paid until a side-by-side test says otherwise. Cartesia's first audio was about 70 ms. I would not risk that. Pro included credits are about $50 per million characters. Scale is about $37. A self-hosted voice cuts that line and can add hundreds of milliseconds plus a GPU.

**Turn detection.** Already local. The multilingual detector runs in the agent process. It is not a paid API. This is where tuning time belongs: it is the largest measured wait, and it does not add a vendor bill.

## 3. When a provider dies in the middle of a call

The caller should hear one short line, the agent should stop taking new work, and the record of what did happen should still be saved.

The clinic path already works this way. A timeout, a connection error, or a taken slot comes back as a tool result, and the agent says so. A guard that blocks a booking before any request does not pretend the clinic was called.

The other providers are weaker. If Deepgram, Groq, Cartesia, or LiveKit drops, the session fails. There is no second vendor. I would add one fixed spoken line that does not need the model, then hang up, then the same result post the recorder already retries. If only the model is down, that line can still play. If the voice is down, the call is over and the transcript so far is what gets stored. If LiveKit is down, there is no media left. The useful work is an alert, not a retry inside a dead room.

A result post already retries while our API wakes up. A missed webhook is retried, and the attempts are stored. The caller is not held on the line for that.

## 4. What I would keep from LiveKit, and what I would build

I would keep the room, the worker, the interruption machinery, the turn detector, and the per-message metrics. Those metrics are why the latency table exists. I would keep their cloud deploy for the worker. Rebuilding a media server is not the product.

I would keep building the clinic parts in our own code: the create-call API, the booking guards, the phone read-back, the FAQ search, the cost breakdown, and the signed webhook. LiveKit does not know that the same slot must fail the second time, or that a price must come from the FAQ rather than the model's memory. The filler line during a tool is ours on purpose. Silence during a lookup is a product bug, not a framework default I want.

## 5. The first 30 days

Days 1 to 7: one real phone path. Use LiveKit's included US number or a paid SIP trunk. Make one inbound and one outbound call. Run the 30-turn set and the 10 interruptions. Replace the pilot numbers. Add `recordingUrl` to `GET /calls/{id}`.

Days 8 to 16: move calls and slots from SQLite to Postgres. Add one login on the web console. Keep the API key between the web server and the API. Alert when a result post fails after its retries, and when the end-of-turn p95 goes back above 1.5 seconds.

Days 17 to 24: remove the cold tool call. Keep the clinic warm, and make a timeout offer another time in a spoken line. Cut prompt text the model does not need, then measure the first token again.

Days 25 to 30: only then try Hindi or Tamil on a copy of the agent, with code-mixed lines. Do not put that on the review number until the English phone numbers are the ones in the report.
