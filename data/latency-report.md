# Latency report

Calls: 1. Turns: 20.

n is the number of non-null values used for that row. Nulls are ignored.

WARNING: the all-turns group has n=20, which is below 30. These numbers can move a lot until there are more turns.

| group | component | n | median ms | p95 ms |
| --- | --- | ---: | ---: | ---: |
| all | transcriptionDelayMs | 13 | 372 | 1353 |
| all | endOfTurnDelayMs | 13 | 867 | 3003 |
| all | llmTtftMs | 12 | 439.5 | 516 |
| all | ttsTtfbMs | 20 | 71 | 95 |
| all | e2eLatencyMs | 11 | 1237 | 13581 |
| all | toolDurationMs | 8 | 49 | 4233 |
| all | derivedTotalMs | 9 | 1045 | 4300 |
| plain | transcriptionDelayMs | 9 | 421 | 1353 |
| plain | endOfTurnDelayMs | 9 | 934 | 3003 |
| plain | llmTtftMs | 6 | 392 | 516 |
| plain | ttsTtfbMs | 12 | 70.5 | 95 |
| plain | e2eLatencyMs | 5 | 1051 | 3094 |
| plain | toolDurationMs | 0 |  |  |
| plain | derivedTotalMs | 7 | 1045 | 3090 |
| tool | transcriptionDelayMs | 4 | 371.5 | 372 |
| tool | endOfTurnDelayMs | 4 | 817.5 | 867 |
| tool | llmTtftMs | 6 | 451.5 | 496 |
| tool | ttsTtfbMs | 8 | 72.5 | 132 |
| tool | e2eLatencyMs | 6 | 1678 | 13581 |
| tool | toolDurationMs | 8 | 49 | 4233 |
| tool | derivedTotalMs | 2 | 2357.5 | 4300 |
| kb | transcriptionDelayMs | 0 |  |  |
| kb | endOfTurnDelayMs | 0 |  |  |
| kb | llmTtftMs | 0 |  |  |
| kb | ttsTtfbMs | 0 |  |  |
| kb | e2eLatencyMs | 0 |  |  |
| kb | toolDurationMs | 0 |  |  |
| kb | derivedTotalMs | 0 |  |  |
