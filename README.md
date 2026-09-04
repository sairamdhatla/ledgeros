# LedgerOS

## AI-Assisted Finance Controller

LedgerOS is an AI-assisted finance controller that reconciles invoice, payment-gateway, and bank-settlement records, then investigates exceptions using evidence-grounded AI while keeping financial truth deterministic and uncertain cases under human review.

**Ingest -> Normalize -> Reconcile -> Detect Exceptions -> Investigate -> Verify -> Resolve or Escalate -> Audit**

> Deterministic financial logic establishes financial truth. The LLM explains ambiguous exceptions; it does not decide the authoritative reconciliation result.

## Why LedgerOS

Financial operations need more than a match or mismatch label. LedgerOS brings invoice, payment-gateway, and bank-settlement records together, applies explicit reconciliation rules, exposes the evidence behind exceptions, and provides a structured investigation workflow for human operators.

The LLM never performs authoritative financial arithmetic, overrides deterministic results, invents records or evidence, or modifies financial records. AI output is validated with Pydantic, and returned evidence IDs must belong to the selected case.

## Product Features

- Reproducible synthetic finance data generation
- Invoice, gateway, and bank-settlement reconciliation
- Deterministic exception classification
- Finance-operations dashboard with summary counts
- Exception search and status filtering
- Case detail view with source evidence
- OpenRouter-backed AI exception investigation
- Structured confidence, evidence IDs, and recommended action
- Human-review indication for uncertain or unresolved cases
- Read-only audit-oriented case and investigation view
- Deterministic fallback when the provider is unavailable, rate-limited, or returns invalid output

## Architecture

```text
Data Sources
	|
	v
Normalize
	|
	v
Deterministic Reconciliation
	|
	v
Match / Auto-resolve / Needs Review / Unresolved
	|
	v
Exception Evidence
	|
	v
AI Investigation
	|
	v
Validated Structured Result
	|
	v
Human Review / Resolution / Escalation
	|
	v
Audit Trail
```

The reconciliation engine remains authoritative for financial truth. The AI investigator receives only the selected case and its supplied evidence. Its response must satisfy the existing structured model, use valid case evidence IDs and recommended actions, and preserve human-review requirements. No AI workflow performs a financial mutation.

## Validated Deterministic Results

The independent evaluation harness was run against 500 synthetic cases. These are deterministic reconciliation and evaluation results, not LLM accuracy results.

| Metric | Result |
| --- | ---: |
| Total cases | 500 |
| Exact status accuracy | 100.00% |
| False auto-resolution rate | 0.00% |
| Unresolved cases | 71 |
| Scenario accuracy | 100% for every evaluated scenario |

Evaluated scenarios:

`exact_match`, `gateway_fee`, `settlement_timing`, `partial_payment`, `duplicate_transaction`, `missing_bank_settlement`, and `unexplained_discrepancy`.

## Real AI Validation

The OpenRouter integration was tested with real requests using:

```text
google/gemma-4-26b-a4b-it
```

A validated real investigation returned:

- AI-generated response: `true`
- Case: `TXN-000006`
- Deterministic status: `NEEDS_REVIEW`
- Recommended action: `VERIFY_SETTLEMENT`
- Evidence IDs validated against the case
- Human review remained required

No AI accuracy percentage is claimed. External model availability and rate limits can affect investigation requests; invalid or unavailable responses use the deterministic fallback.

## Tech Stack

| Area | Technologies |
| --- | --- |
| Backend | Python, FastAPI, Pydantic, Pandas, OpenPyXL, Pytest, SQLite |
| Frontend | React, TypeScript, Vite |
| AI | OpenRouter, `google/gemma-4-26b-a4b-it` |
| Development | Git, GitHub |

## Repository Structure

```text
backend/     FastAPI application, reconciliation services, AI investigator, and tests
data/        Synthetic source data and generated datasets
docs/        Project documentation
evaluation/  Deterministic evaluation runner, metrics, and reports
frontend/    React and TypeScript operations dashboard
tests/       Repository-level test area
.github/     Repository and Copilot project instructions
```

## Local Setup

### Backend

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env` locally:

```env
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_MODEL=google/gemma-4-26b-a4b-it
```

Never commit a real key. `backend/.env` is Git-ignored, and the key must remain server-side; it is never placed in frontend code.

### Frontend

The frontend dependencies are installed from `frontend/package.json`:

```bash
cd frontend
npm install
```

## Running the Application

Start the backend:

```bash
cd ~/Desktop/Ledgeros/backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

Backend: `http://127.0.0.1:8000`

Start the frontend in another terminal:

```bash
cd ~/Desktop/Ledgeros/frontend
npm run dev
```

Frontend: `http://localhost:5173`

## Data Generation

The project uses synthetic, reproducible operational data:

```bash
cd backend
python -m app.utils.generate_data
```

## Evaluation

Run the deterministic evaluation from the repository root:

```bash
python evaluation/runner.py
```

The evaluation harness compares reconciliation results with `data/generated/ground_truth.csv`. The ground truth is kept separate from the reconciliation engine and is used only by the evaluation harness. The reported metrics are status accuracy, false auto-resolution rate, scenario accuracy, and unresolved count.

## Testing

Run backend tests:

```bash
cd backend
python -m pytest -q
```

Build the frontend for production:

```bash
cd frontend
npm run build
```

## Demo Flow

1. Open the dashboard and show the 500-case summary.
2. Open **Exceptions**.
3. Select an exception case.
4. Inspect invoice, gateway, and bank evidence.
5. Show the deterministic reconciliation reason.
6. Click **Investigate with AI**.
7. Show the structured conclusion and confidence.
8. Show validated evidence IDs and recommended action.
9. Show that human review remains required.
10. Open an unresolved case and show that LedgerOS does not guess when evidence is insufficient.

## Safety and Trust

- Deterministic reconciliation establishes financial truth.
- AI investigation is grounded only in supplied case evidence.
- Pydantic validates structured AI output.
- Evidence IDs are checked against the selected case.
- Recommended actions are restricted to the existing allowed actions.
- `NEEDS_REVIEW` and `UNRESOLVED` cases remain subject to human review.
- Provider failures, rate limits, malformed output, and unsafe output use the deterministic fallback.
- The LLM cannot approve, settle, refund, alter, or otherwise modify financial records.
- The system does not fabricate evidence or allow the LLM to override reconciliation truth.

## Limitations

- The dataset is synthetic.
- AI investigation depends on external model availability and configuration.
- Free model endpoints can be rate limited; the configured demo model is `google/gemma-4-26b-a4b-it`.
- LedgerOS is a prototype/demo, not a production financial system.
- It does not claim real-money recovery, real settlement execution, or real merchant-data integration.

LedgerOS does not claim production readiness, real Razorpay transaction integration, an AI accuracy percentage, autonomous financial settlement, or autonomous financial-record modification.
