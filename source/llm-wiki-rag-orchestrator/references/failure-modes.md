# Failure Modes And Retry Policy

| failure_mode | Meaning | Action | Retry |
|---|---|---|---|
| `tool_unavailable` | required runtime/parser missing | report fallback or block | verify once |
| `permission_blocked` | path access denied | stop and request exact permission | none |
| `timeout` | operation exceeded limit | narrow scope | max 2 attempts |
| `partial_output` | required artifact missing | one forward fix then block | 1 |
| `hallucinated_source` | knowledge lacks provenance | reject patch | none |
| `stale_data` | source/version may be outdated | flag manual review | none |
| `ambiguous_scope` | multiple incompatible targets | safe dry-run or ask | none |
| `schema_mismatch` | artifact/DB schema invalid | correct or block | max 2 |
| `security_blocked` | unsafe dependency/data boundary | hard block/manual approval | none |
| `regression_detected` | prior contract no longer works | reject acceptance | reopen implementation |

Never hide a specific mode behind a generic failure string.
