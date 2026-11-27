# Report

Every number below says how it was measured. Where a required number does not exist yet, the gap is written in the open. No missing phone or knowledge-base number has been filled in.

## 1. Latency

### How this was measured

The agent stores one row per spoken reply in `turnMetrics`. The times come from the LiveKit Agents 1.8.13 metrics on each chat message, converted from seconds to milliseconds. Nothing here is a hand-timed stopwatch, and no missing field was invented.

| Stored field | LiveKit field | What it is |
| --- | --- | --- |
| transcriptionDelayMs | `transcription_delay` on the caller message | Speech-to-text delay |
| endOfTurnDelayMs | `end_of_turn_delay` on the caller message | Waiting to decide the caller has finished |
| llmTtftMs | `llm_node_ttft` on the agent reply | Model time to first token |
| ttsTtfbMs | `tts_node_ttfb` on the agent reply | Text-to-speech time to first audio |
| e2eLatencyMs | `e2e_latency` on the agent reply | The SDK's own end-to-end time, only when it computed one |
| toolDurationMs | our tool log | Time spent in tools on that turn |

`scripts/latency_report.py` reads `GET /calls`, then `GET /calls/{id}`, ignores nulls, and reports the median and the nearest-rank 95th percentile. The saved file is `data/latency-report.md`.

### What the pilot actually is

One browser call. 20 agent turns. The all-turns group has n=20, which is below the required 30, so these numbers can move. The same file is copied at `data/latency-pilot-before-tuning.md`.

This is not a phone call. There is no telephony round trip in the table. The knowledge-base rows are empty, so this call did not measure `lookup_faq`.

The endpointing maximum was later lowered from the library default of 3.0 seconds to 1.5 seconds. That change is not in these numbers. The 3003 ms end-of-turn p95 matches the old 3 second wait. A new session is required before claiming the 1.5 second setting is faster.

### Median and p95, milliseconds

n is how many non-null values that cell used.

| group | component | n | median | p95 |
| --- | --- | ---: | ---: | ---: |
| all | speech-to-text | 13 | 372 | 1353 |
| all | end of turn | 13 | 867 | 3003 |
| all | model, first token | 12 | 440 | 516 |
| all | text-to-speech, first audio | 20 | 71 | 95 |
| all | SDK end-to-end, when present | 11 | 1237 | 13581 |
| all | tools | 8 | 49 | 4233 |
| plain | speech-to-text | 9 | 421 | 1353 |
| plain | end of turn | 9 | 934 | 3003 |
| plain | model, first token | 6 | 392 | 516 |
| plain | text-to-speech, first audio | 12 | 71 | 95 |
| plain | SDK end-to-end | 5 | 1051 | 3094 |
| tool | speech-to-text | 4 | 372 | 372 |
| tool | end of turn | 4 | 818 | 867 |
| tool | model, first token | 6 | 452 | 496 |
| tool | text-to-speech, first audio | 8 | 73 | 132 |
| tool | SDK end-to-end | 6 | 1678 | 13581 |
| tool | tool time | 8 | 49 | 4233 |
| kb | every component | 0 |  |  |

The model and the voice are already fast. The wait after the caller pauses is the large piece. One tool turn took about 4.2 seconds, which is a cold clinic call, not the model. The end-to-end p95 of 13581 ms is one slow turn, not the typical reply. The median end-to-end, when the SDK reported it, is 1.2 seconds.

Telephony round trip: not measured.

### Still required before this section is finished

Run four browser sessions if a phone number is still blocked, then replace them with phone sessions as soon as a number works. After each batch:

```powershell
$env:API_BASE_URL = "<the call API>"
$env:API_KEY = "<the API key>"
.\.venv\Scripts\python.exe scripts\latency_report.py
```

Say these, and do not talk over the agent except in the interruption session:

1. Plain, about 15 short questions with no tools. "What is your name?" is wrong for this. Ask things that do not need a lookup, then also do session 3 for prices.
2. Tools. Ask for tomorrow's free slots, book one, then try to book that same slot again.
3. Knowledge base. Ask hours, address, parking, and the price of a cleaning. Each of those must call `lookup_faq`.
4. Stop at 30 or more agent turns in total. The script prints a warning until the all-turns row reaches 30.

## 2. Cost per minute

### How this was measured

`api/pricing.json` holds the list rates. `scripts/cost_model.py` reads completed calls, ignores any call shorter than 20 seconds, and divides saved usage by the saved duration. On 27 Nov 2026 that was 8 completed calls and 16.55 minutes. No short calls were dropped. No call was missing usage.

Per call minute, from those 16.55 minutes:

| measure | per minute |
| --- | ---: |
| speech-to-text audio | 0.5485 minutes |
| model prompt tokens | 2646 |
| model completion tokens | 140 |
| spoken characters | 192 |

The scenario is 1,000 calls a day, 3 minutes each, for 30 days. That is 90,000 minutes. The exchange rate is the assumption in `pricing.json`: 94 rupees per dollar. It is not a live bank rate.

### Price pages checked on 27 Nov 2026

| part | rate used | page |
| --- | --- | --- |
| Browser connection | $0.0005 per WebRTC minute | https://livekit.com/pricing |
| Agent session, inside the server line | $0.01 per minute, plus about $0.00016 assumed for the API and clinic | https://livekit.com/pricing |
| Speech-to-text | $0.0048 per audio minute, Nova-3 monolingual streaming, current promo. The regular rate on the same page is $0.0077 | https://deepgram.com/pricing |
| Model | $0.075 per million prompt tokens, $0.30 per million completion tokens, `openai/gpt-oss-20b` | https://console.groq.com/docs/model/openai/gpt-oss-20b |
| Voice | $50 per million characters. That is the Pro plan's included credits: $5 for 100,000 credits, about one credit per character. Scale included credits are about $37.38 per million. Pro overage is $65 | https://www.cartesia.ai/pricing |
| Phone, in the second table | $0.012 per minute, a combined assumption | LiveKit's own third-party SIP line is $0.004 per minute on Ship, not $0.012. Twilio's own minute was never reached because the trial blocked SIP |

### Raw cost, from those list prices

Browser, using the WebRTC rate:

| | INR |
| --- | ---: |
| Per minute | 2.18 |
| Per 3-minute call | 6.53 |
| Per day, 1,000 calls | 6,528 |
| Per 30-day month | 195,844 |

Phone, using the $0.012 assumption:

| | INR |
| --- | ---: |
| Per minute | 3.26 |
| Per 3-minute call | 9.77 |
| Per day, 1,000 calls | 9,771 |
| Per 30-day month | 293,134 |

Swapping only the phone assumption from $0.012 to LiveKit's published $0.004 SIP rate lowers the raw phone total by about Rs 0.75 per minute. Twilio's own carrier minute is extra and is not in that $0.004.

### Realistic cost

Added on top of the raw total, from the assumptions at the top of `scripts/cost_model.py`:

| hidden cost | assumption |
| --- | --- |
| Failed minutes | 5% extra minutes |
| Recording and observability | $0.01 per minute |
| Platform fee | $50 per month, spread over the 90,000 minutes |
| Forex markup | 2% before tax |
| GST | 18% |

Browser realistic total: **Rs 3.94 per minute**, Rs 11.83 per call, Rs 11,833 per day, **Rs 354,985 per month**.

Phone realistic total at $0.012: **Rs 5.31 per minute**, Rs 15.93 per call, Rs 15,931 per day, **Rs 477,938 per month**.

Not included: engineering time, a monitoring product, support, a carrier minimum, buying more concurrent sessions, and database hosting.

The full tables, including the three sensitivity rows, are in `data/cost-model.md`.

## 3. Interruption test

Not done. The assignment asks for 10 interruptions on a phone call, how many were clean, and how long the agent took to go quiet.

The code is ready to record them. Each row stores `kind` (`real` or `false_resumed`) and `timeToQuietMs`, the time from the caller starting to the agent leaving the speaking state. There is no completed set of 10 phone interruptions, so this report does not give a fraction or a median.

How to finish it: on one call, talk over the agent 10 times with a real sentence, and also say "mm-hmm" twice. Those two should not count as clean interruptions. Then open the call detail and read `interruptions`. Clean means `kind` is `real` and `timeToQuietMs` is well under a second. A cough or "mm-hmm" that resumes the same sentence should be `false_resumed`.

The current settings, in `agent/main.py`, are a minimum of 0.4 seconds and 2 words before the agent treats overlap as an interruption, and a 2 second window to resume a false interruption.

## 4. What I would change first

**Latency.** The first change is already started: the maximum end-of-turn wait is 1.5 seconds instead of 3.0. I would not claim a gain until a new 30-turn run shows a lower `endOfTurnDelayMs` p95 without the agent cutting people off. If that p95 is still near 1.5 seconds, the next change is a streaming turn detector, which can decide earlier than the fixed wait. Expected effect: several hundred milliseconds off the typical reply, which is larger than anything left to squeeze from the model or the voice. The model first token is already about 440 ms and the voice first audio is about 70 ms.

**Cost.** The voice is the expensive speech line at the measured 192 characters per minute, and it jumps if the agent talks more. The first cost change is to keep answers to one short sentence, which the prompt already asks for, and to move Cartesia from the Pro included rate ($50 per million) to Scale ($37.38 per million) only after the volume is real. Expected effect at today's character rate: the sensitivity row drops the raw browser minute from Rs 2.18 to about Rs 1.95. A bigger saving appears only if the agent starts speaking closer to 600 characters a minute. In that case the same table shows the raw browser minute rising to about Rs 4.09, so short answers matter more than the plan change.

## Honest gaps

| gap | why | what I would do |
| --- | --- | --- |
| Real inbound and outbound phone calls | No free India number. A call from an Indian SIM to a US trial number is cut. The Twilio trial locked SIP and TwiML. The review cannot call a browser page | Rent LiveKit's included US local number, or move the SIP trunk to a paid Twilio account, and point inbound at the same agent. `POST /calls` already accepts `direction` and `to` |
| Recording link on `GET /calls/{id}` | No recorder was wired. LiveKit Cloud can still show the session audio under the agent session | Add room egress, store the file URL on the call, and return it as `recordingUrl` |
| 30 turns, knowledge-base rows, 10 interruptions | Only the 20-turn browser pilot exists, and it has no FAQ turns | The four sessions in section 1 |
| Hindi or Tamil | Left for later | A second Deepgram language and a prompt rule for code-mixed speech, after the English numbers are stable |
| Postgres and login | SQLite and one API key | Postgres for the calls and slots, then one login in front of the web console. The API key stays between services |

The browser demo is real: the agent hears, uses the clinic tools, blocks a second booking, looks up the FAQ when that tool is on, and hangs up. It does not replace the phone requirement.
