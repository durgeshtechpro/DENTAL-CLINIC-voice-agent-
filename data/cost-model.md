# Cost model

Date: 2026-11-27

Scenario: 1000 calls a day, 3 minutes each, for 30 days.

## Measured usage

Used 8 completed calls, 16.55 minutes. Ignored 0 completed calls shorter than 20 seconds and 0 completed calls with no saved usage or duration.

Averages below are per call minute (usage divided by those minutes).

| measure | per call minute |
| --- | ---: |
| stt audio minutes (sttAudioSeconds / 60) | 0.5485 |
| llm prompt tokens | 2646.00 |
| llm completion tokens | 140.06 |
| tts characters | 192.32 |

## Pricing notes

USD to INR in the file: 94. Used for this report: 94.

- telephony: LiveKit WebRTC minute (browser calls). Phone via SIP: about 0.012
- stt: Deepgram Nova-3 monolingual streaming, pay as you go
- llm: Groq gpt-oss-20b
- tts: Cartesia Sonic, Pro plan effective rate
- server: LiveKit agent session 0.01 plus about 0.00016 API and clinic hosting (assumption)

## Browser (pricing.json telephony)

### Raw cost

| component | quantity per minute | rate | USD per minute | INR per minute |
| --- | --- | --- | ---: | ---: |
| telephony | 1 call minute | $0.000500 per minute | 0.000500 | 0.0470 |
| stt | 0.5485 audio minutes | $0.004800 per audio minute | 0.002633 | 0.2475 |
| llm | 2646.0 prompt tokens, 140.1 completion tokens | $0.075 / $0.3 per million | 0.000240 | 0.0226 |
| tts | 192.3 characters | $50 per million characters | 0.009616 | 0.9039 |
| server | 1 call minute | $0.010160 per minute | 0.010160 | 0.9550 |
| total |  |  | 0.023149 | 2.1760 |

Per minute: Rs 2.1760
Per call (3 min): Rs 6.53
Per day (1000 calls): Rs 6528.13
Per 30-day month: Rs 195844.02

### Realistic cost

| cost | INR per minute | INR per call | INR per day | INR per month |
| --- | ---: | ---: | ---: | ---: |
| Raw vendor total | 2.1760 | 6.53 | 6528.13 | 195844.02 |
| Failed minutes (5% extra) | 0.1088 | 0.33 | 326.41 | 9792.20 |
| Recording and observability | 0.9400 | 2.82 | 2820.00 | 84600.00 |
| Platform fee (USD 50 / month, spread over the minutes) | 0.0522 | 0.16 | 156.67 | 4700.00 |
| Forex markup (2% before GST) | 0.0655 | 0.20 | 196.62 | 5898.72 |
| GST (18%) | 0.6017 | 1.81 | 1805.01 | 54150.29 |
| Realistic total | 3.9443 | 11.83 | 11832.84 | 354985.23 |

## Phone (telephony $0.012000 per minute)

### Raw cost

| component | quantity per minute | rate | USD per minute | INR per minute |
| --- | --- | --- | ---: | ---: |
| telephony | 1 call minute | $0.012000 per minute | 0.012000 | 1.1280 |
| stt | 0.5485 audio minutes | $0.004800 per audio minute | 0.002633 | 0.2475 |
| llm | 2646.0 prompt tokens, 140.1 completion tokens | $0.075 / $0.3 per million | 0.000240 | 0.0226 |
| tts | 192.3 characters | $50 per million characters | 0.009616 | 0.9039 |
| server | 1 call minute | $0.010160 per minute | 0.010160 | 0.9550 |
| total |  |  | 0.034649 | 3.2570 |

Per minute: Rs 3.2570
Per call (3 min): Rs 9.77
Per day (1000 calls): Rs 9771.13
Per 30-day month: Rs 293134.02

### Realistic cost

| cost | INR per minute | INR per call | INR per day | INR per month |
| --- | ---: | ---: | ---: | ---: |
| Raw vendor total | 3.2570 | 9.77 | 9771.13 | 293134.02 |
| Failed minutes (5% extra) | 0.1629 | 0.49 | 488.56 | 14656.70 |
| Recording and observability | 0.9400 | 2.82 | 2820.00 | 84600.00 |
| Platform fee (USD 50 / month, spread over the minutes) | 0.0522 | 0.16 | 156.67 | 4700.00 |
| Forex markup (2% before GST) | 0.0882 | 0.26 | 264.73 | 7941.81 |
| GST (18%) | 0.8101 | 2.43 | 2430.20 | 72905.86 |
| Realistic total | 5.3104 | 15.93 | 15931.28 | 477938.39 |

## Not included

These hidden costs are not in the tables:

- engineering time
- monitoring
- support
- carrier minimum commitments
- concurrency upgrades
- database hosting

## Sensitivity

Each row changes one thing and shows the new raw total per minute.

| change | browser INR per minute | phone INR per minute |
| --- | ---: | ---: |
| Measured rates | 2.1760 | 3.2570 |
| Cartesia Scale, $37.4 per million characters | 1.9483 | 3.0293 |
| Deepgram streaming, $0.0077 per minute | 2.3256 | 3.4066 |
| 600 TTS characters per minute | 4.0921 | 5.1731 |
