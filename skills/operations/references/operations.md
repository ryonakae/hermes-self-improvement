# Operations

Use the simplified wrapper CLI from the repository root.

```bash
bin/hermes-self-improve status
bin/hermes-self-improve improve
bin/hermes-self-improve improve --execute
bin/hermes-self-improve calibrate
bin/hermes-self-improve calibrate --execute
bin/hermes-self-improve plan --since-hours 24 --scorer compare
bin/hermes-self-improve apply <plan-id>
bin/hermes-self-improve apply <plan-id> --execute
bin/hermes-self-improve rollback <ledger-id>
bin/hermes-self-improve rollback <ledger-id> --execute
bin/hermes-self-improve report --since-hours 24 --scorer compare
```

Cron / scheduled execution should normally use read-only report or preview-only improve:

```bash
bin/hermes-self-improve report --since-hours 24 --json
bin/hermes-self-improve improve --since-hours 24 --json
```

Do not schedule legacy approval/low-risk/hash-confirmation commands; they are not part of the surface.

Review outcome feedback is append-only evidence for human/apply/rollback outcomes. Record rejected, edited, ignored, failed, or rolled-back items with short non-secret reasons; reasons are redacted and hashed. Review outcomes are summarized in reports and counted as calibration evidence, but they do not grant auto-apply permission.

When debugging scorer behavior, use `report`, `plan`, and `calibrate` rather than old GEPA-specific CLI commands. GEPA/DSPy details are internal to scorer and calibration modules.

Validation after code or docs changes:

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
bin/hermes-self-improve --help
```
