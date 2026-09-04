# LedgerOS Reconciliation Evaluation Harness

This harness evaluates the deterministic reconciliation engine against the generated benchmark. It is separate from the engine: `ground_truth.csv` is opened only by `evaluation/runner.py` and is never passed to the reconciliation package.

Run from the repository root:

```text
python evaluation/runner.py
```

The command writes:

- `evaluation/results.json`: machine-readable metrics and integrity checks
- `evaluation/results.md`: human-readable findings, confusion matrix, and scenario breakdown

The false auto-resolution rate is calculated as false `AUTO_RESOLVED` predictions divided by all engine `AUTO_RESOLVED` predictions. Status precision is calculated independently for each allowed engine status. Scenario labels `gateway_fee` and `settlement_timing` are report aliases for the longer labels in `ground_truth.csv`.

The harness also checks that reconciliation source files do not contain ground-truth access markers or hard-coded case IDs, and checks for missing, duplicate, or empty result transaction IDs.