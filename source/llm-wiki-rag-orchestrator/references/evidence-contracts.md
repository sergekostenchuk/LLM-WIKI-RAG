# Evidence Contracts

Required evidence per accepted apply run:

| ID | Claim | Collection | Artifact | Validator | Required |
|---|---|---|---|---|---|
| E-UPDATE-01 | source scope was known | scan and SHA256 | run report ChangeSet | detector | yes |
| E-UPDATE-02 | only managed zones changed | planned/written paths | run report writes | orchestrator | yes |
| E-UPDATE-03 | Wiki and RAG agree | run `audit` | audit report | validator | yes |
| E-UPDATE-04 | no deletion was applied | deleted list + mode | run report | publisher | yes |

Sanitation: never include environment secret values; truncate source previews; keep reports under the user-selected project.

Evidence status is one of `planned`, `collected`, `validated`, `blocked`, or `waived_with_risk`. Planned evidence cannot support acceptance.
