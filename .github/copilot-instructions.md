# LedgerOS — Copilot Instructions

## Project Mission

LedgerOS is an AI-assisted finance control system for reconciling messy financial records.

Core workflow:

Ingest → Normalize → Reconcile → Detect Exceptions → Investigate → Verify → Resolve or Escalate → Audit

## Core Principle

Use deterministic code whenever financial truth can be calculated or verified deterministically.

Use the LLM only for:
- interpreting ambiguous financial evidence
- investigating exceptions
- generating explanations
- deciding whether an exception requires human review

Never use the LLM for arithmetic that Python can perform.

## Safety

The LLM must never directly modify financial records.

All AI outputs must be validated with Pydantic.

Every AI decision must contain:
- decision
- confidence
- explanation
- evidence IDs
- whether human review is required

Low-confidence or conflicting cases must be escalated.

Never fabricate financial data, evaluation metrics, user numbers, or business outcomes.

## Evaluation

The project must support a synthetic dataset containing at least 50 records.

Prefer 500 records for the benchmark.

Evaluation must measure:
- match rate
- auto-resolution precision
- unresolved exceptions
- false auto-resolution rate
- processing time

## Engineering

Prefer simple, readable implementations.

Do not introduce:
- microservices
- Kubernetes
- Redis
- Celery
- complex authentication
- unnecessary vector databases

unless explicitly requested.

Keep modules small and testable.

Write tests for financial logic.

## Product

The frontend should feel like a finance operations dashboard.

Prioritize:
- reconciliation summary
- exceptions
- evidence
- explanations
- confidence
- audit trail

Avoid unnecessary animations or decorative UI.

## Coding Style

Python:
- type hints
- Pydantic models
- FastAPI
- pytest
- clear functions
- meaningful names

Frontend:
- TypeScript
- React
- simple reusable components

Do not rewrite unrelated files.

Do not add dependencies without justification.