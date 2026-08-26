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


## 執行環境變數（實作補充）

| 變數 | 用途 | 缺少時的行為 |
|------|------|--------------|
| `RESEARCH_PIPELINE_ENABLED` | 是否啟用整條管線 | 預設 `false`：完全不初始化，pipeline API 回 503，既有 QA/market API 不受影響 |
| `RESEARCH_PIPELINE_CHECKPOINT_DSN` | LangGraph checkpoint 的 PostgreSQL DSN | 退回 `RESEARCH_PIPELINE_DB_DSN` |
| `RESEARCH_PIPELINE_DB_DSN` | 業務 run 表（`maya_sawa_research_pipeline_runs`）的 DSN | 業務表退回記憶體版；啟用狀態下兩個 DSN 都沒有則**啟動失敗** |
| `RESEARCH_PIPELINE_LOCAL_MODE` | 設為 `true` 時允許使用 in-memory checkpointer | 啟用且非 local mode 時缺 DSN 直接 fail fast |
| `RESEARCH_PIPELINE_DB_AUTO_MIGRATE` | 設為 `true` 時啟動自動建立業務表 | 需自行執行 `sql/create_research_pipeline_runs_table.sql` |

checkpointer 與業務表可以共用同一個 PostgreSQL instance：前者使用 LangGraph 自己的
`checkpoints*` 資料表，後者是 `maya_sawa_research_pipeline_runs`。需要更強的隔離時，
在 DSN 加上 `options=-csearch_path%3D<schema>`。

本機開發若不想接資料庫，設定 `RESEARCH_PIPELINE_LOCAL_MODE=true`；此時 process
重啟後等待審核的 run 無法 resume，approve 會得到 409。


## CRAG Gate（實作補充）

正式 mapping 的形狀已確認為 `rackParts`（TYMB `/tymb/resources/company-product-mapping`
原樣代理 OCI 物件，沒有任何轉換），change set 因此改為 rack-part 導向：
`update_rack_part` / `add_product_entry` / `update_product_entry`。
`rackParts[].id` 綁定前端 PowerRackDiagram 的 hover region，MVP 不允許新增或刪除 rack part。

CRAG 是 generator 前的**硬性 gate**，不是事後補一個分數：

```
load_mapping → collect_evidence → evaluate_retrieval
                                    ├─ correct   → refine_evidence
                                    └─ 其他      → corrective_retrieve → evaluate_retrieval
                                 → evidence_gate
                                    ├─ insufficient → notify_failure
                                    └─ sufficient   → generate_change_set
                                 → validate_grounding → validate_change_set → merge → approval → publish
```

- `evaluate_retrieval` 對每筆 evidence 檢查六項：rack part 對應、company 匹配、
  product 匹配、是否有可支持變更的敘述、是否為 allowlist primary source、
  時間/URL/內容是否完整。其中 rack part、company、primary source、欄位完整
  屬於 critical，未通過就不可能是 `correct`。
- 判定 `correct` / `ambiguous` / `incorrect`，score 與 reasons 一併保存。
- `corrective_retrieve` 只能從 `evidence_targets.json` 與 trusted-source registry
  擴充，永遠不接受 LLM 提供的 URL；最多兩輪，之後 fail closed。
- `refine_evidence` 只保留 `correct` evidence 中與 company/product 相關的句子並跨來源去重；
  `ambiguous` evidence 留在 state 供人工查看，但不會進入 refined_evidence，
  因此無法單獨支持任何 operation。
- `validate_grounding` 要求每個 operation 引用的 evidence 都存在於精煉結果、
  CRAG 判定為 `correct`，且 rackPartId 與 operation 一致。
- run 表保存 `retrieval_evaluation`、`retrieval_verdict`、`correction_attempts`、
  `refined_evidence`，審核畫面因此可以解釋「為什麼這筆變更通過」。

deterministic evaluator 是安全底線。未來加入 LLM evaluator 時，它只能加強語意判斷，
不能取代這裡的規則。


## Change-set Generator 邊界（實作補充）

LLM client 以 dependency injection 注入（`LlmClient` protocol），
測試一律使用 `FakeLlmClient`，不消耗任何 token。

模型輸出被視為完全不可信，依序通過三層：

1. `extract_json_object` — 只接受單一 JSON 物件，容忍 markdown code fence。
2. `parse_change_set` — schema 驗證；delete、`add_rack_part`、未知 op/欄位在這層被拒。
3. `boundary_errors` — evidenceId 必須來自本次提供的精煉證據，
   rackPartId 必須存在於目前 mapping。

malformed 輸出最多重試一次（`max_attempts=2`），仍失敗就讓 `generate_change_set`
節點乾淨失敗，不會退回「猜一個」。prompt 只包含相關 rack part 的現況與精煉證據，
模型看不到完整 production mapping。

真實模型 smoke test 位於 `tests/test_research_pipeline_llm_smoke.py`，
預設 skip，需 `RESEARCH_PIPELINE_LLM_SMOKE=true`；只送一份證據、一次呼叫、
限制 output token，且只驗證 schema 相容性，不驗證文字品質。
