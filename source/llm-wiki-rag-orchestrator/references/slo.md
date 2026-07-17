# Service Levels And Alerts

These are default local-profile objectives; operators may tighten them.

| Signal | Objective | Alert |
|---|---|---|
| Post-mutation audit | 100% of applied runs | any failed audit |
| Provenance coverage | 100% generated source pages | any missing source hash/page |
| Snapshot coverage | 100% mutating runs | mutation without snapshot |
| Retrieval regression | 100% release fixtures | any failed expected top source |
| Update freshness | scheduled interval + 2 intervals | metrics/events stale |
| Lock wait | fail fast | live lock blocks scheduled run |
| Error budget | 0 destructive integrity failures | immediate incident |

Health check exit `0` means healthy. Exit `3` is alertable. External alert delivery is operator-owned and intentionally not hardcoded.
