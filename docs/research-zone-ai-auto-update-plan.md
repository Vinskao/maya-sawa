# Research Zone AI Auto-Update Pipeline MVP Plan

## Purpose

Build a narrow, reliable research publishing pipeline for Research Zone company/product mapping updates.

The goal is not to let AI rewrite the production JSON every day. The goal is to create a controlled pipeline that is source-backed, traceable, reversible, and resistant to hallucinated or destructive updates.

This document is prepared for the next implementation agent.

## Recommended MVP

Phase 1 should stay intentionally small:

- Allow only 3-5 trusted sources.
- Support `add` and `update` operations only.
- Do not allow automatic deletion in the MVP.
- Ask AI to produce a change set, not a full replacement mapping.
- Validate with JSON Schema and business rules before publishing.
- Save the previous OCI object version before writing the new version.
- Send failure notifications to Telegram.
- Expose `updatedAt`, data status, and sources to the frontend.
- First verify the full flow with a manual trigger.
- Add the daily schedule only after the manual flow is stable.

## Architecture Direction

Keep the overall five-layer architecture, but change the processing core to:

```text
evidence -> change set -> deterministic merge -> validation -> publish
```

The important design decision is that AI should not directly publish final production data.

Instead:

1. The crawler/research step collects source evidence.
2. The AI summarizes evidence into a constrained change set.
3. Deterministic code merges the change set into the existing mapping.
4. Validators reject unsafe or malformed results.
5. The publisher stores the previous version, writes the new version, and records metadata.

## Non-Goals for MVP

- No automatic deletion.
- No broad web crawling.
- No untrusted source expansion.
- No direct AI write to production JSON.
- No frontend rewrite unless the current UI cannot show metadata.
- No daily automation until manual end-to-end validation passes.

## Proposed Components

### 1. Trusted Source Registry

Create a static allowlist of trusted sources.

Each source should include:

- source id
- source name
- base URL or API endpoint
- supported company/product scope
- fetch method
- trust level
- rate-limit notes

The MVP should reject evidence from sources outside this registry.

### 2. Evidence Collector

Responsible for collecting raw facts from trusted sources.

Recommended output shape:

```json
{
  "sourceId": "example-source",
  "sourceUrl": "https://example.com/company/product",
  "fetchedAt": "2026-06-25T00:00:00Z",
  "company": "Example Company",
  "product": "Example Product",
  "evidenceText": "Short extracted evidence...",
  "confidence": "high"
}
```

### 3. AI Change Set Generator

The AI should produce only a constrained change set.

Recommended operation types for MVP:

- `add_company`
- `update_company`
- `add_product`
- `update_product`

Deletion-related operations should be rejected until a later phase.

Recommended output shape:

```json
{
  "generatedAt": "2026-06-25T00:00:00Z",
  "operations": [
    {
      "op": "add_product",
      "companyKey": "example-company",
      "productKey": "example-product",
      "data": {
        "name": "Example Product",
        "category": "Example Category",
        "description": "Short description"
      },
      "evidence": [
        {
          "sourceId": "example-source",
          "sourceUrl": "https://example.com/company/product"
        }
      ],
      "confidence": "high"
    }
  ]
}
```

### 4. Deterministic Merger

The merger applies valid change-set operations to the existing mapping.

Rules:

- Existing fields should not be overwritten by empty values.
- Updates must include evidence.
- Unknown operation types must fail.
- Deletions must fail in MVP.
- Duplicate keys must fail unless the operation is an explicit update.
- Merge output must be stable and deterministic.

### 5. Validation Layer

Use two validation levels.

JSON Schema validation:

- required fields
- allowed data types
- allowed enum values
- object shape
- metadata shape

Business validation:

- every new or updated item has evidence
- every source is from the trusted registry
- no automatic deletions
- no suspiciously large diff
- required display fields exist
- `updatedAt` is refreshed
- output remains compatible with the frontend endpoint

### 6. Versioned Publisher

Before writing to OCI:

1. Fetch current production mapping.
2. Save it as the previous version or rollback object.
3. Write the validated new mapping.
4. Write/update metadata.
5. Emit success/failure logs.

If publishing fails after backup, the pipeline should leave enough metadata to restore the previous version.

### 7. Telegram Notification

Send Telegram notification on failure.

The notification should include:

- pipeline name
- environment
- failed stage
- error summary
- timestamp
- rollback/previous version location if available

Success notification can be optional in MVP to reduce noise.

### 8. Frontend Metadata

The frontend does not need a major rewrite.

Expose enough metadata for Research Zone to show:

- `updatedAt`
- data status, such as `fresh`, `stale`, `validation_failed`, or `manual_review_required`
- source list or source count
- optional last successful publish time

## Formal Prerequisites

These should be completed before enabling the daily schedule:

1. Celery Beat or another reliable scheduler is confirmed and deployed.
2. OCI PUT/write permission is verified in the target environment.
3. Previous-version backup and rollback path are tested.
4. Embedding/vectorization completion behavior is confirmed if the pipeline depends on indexed content.
5. Telegram failure notification is tested.
6. Manual end-to-end trigger passes at least once.

## Implementation Checklist

### Phase 0: Discovery

- Locate the current Research Zone mapping endpoint and OCI object path.
- Confirm current frontend fetch behavior.
- Confirm backend ownership of mapping publication.
- Confirm current deployment environment variables and secrets.
- Confirm whether this repo should own the scheduler or only the worker/job logic.

### Phase 1: Manual MVP

- Add trusted source registry.
- Implement evidence collection for 3-5 sources.
- Define JSON Schema for change-set output.
- Define JSON Schema for final mapping output.
- Implement AI prompt for constrained change-set generation.
- Implement deterministic merger.
- Implement business validation.
- Implement previous-version backup.
- Implement OCI publish function.
- Implement Telegram failure notification.
- Add a manual CLI or API trigger.
- Add tests for merge, validation, and rejection cases.

### Phase 2: Frontend Metadata

- Add/update backend response metadata:
  - `updatedAt`
  - `status`
  - `sources`
  - `lastSuccessfulPublishAt`
- Confirm frontend displays metadata without changing its core data-fetch flow.

### Phase 3: Scheduling

- Add Celery Beat or the selected scheduler only after manual flow is stable.
- Run daily job in dry-run mode first.
- Enable production publishing after dry-run confidence is acceptable.

## Acceptance Criteria

The MVP is ready when:

- A manual trigger can collect evidence from trusted sources.
- AI returns a valid change set, not a full mapping replacement.
- Deterministic merge produces a valid final mapping.
- JSON Schema validation catches malformed output.
- Business validation rejects unsupported deletes, untrusted sources, and unsafe diffs.
- Previous production mapping is saved before every OCI write.
- OCI write is verified in the target environment.
- Telegram receives a failure notification when a stage fails.
- Frontend can display `updatedAt`, status, and source metadata.
- Daily scheduling is not enabled until the above checks pass.

## Suggested First Tasks for the Next Agent

1. Inspect current Research Zone mapping usage in frontend and backend.
2. Identify the existing OCI read path and confirm the intended OCI write path.
3. Create schemas for:
   - evidence item
   - AI change set
   - final company/product mapping
4. Implement the deterministic merge module with tests.
5. Add a manual dry-run command that prints:
   - evidence collected
   - generated change set
   - validation result
   - final diff summary

## Key Design Principle

AI can propose changes, but deterministic code must decide whether those changes are safe to publish.

