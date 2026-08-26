-- Research Zone AI 更新管線的業務 run 表。
--
-- 與 LangGraph checkpoint 分工：
--   * LangGraph checkpointer 保存 graph execution state，負責 resume。
--   * 這張表保存可查詢的業務狀態、操作者、版本與錯誤，API 只讀這裡。
--
-- revision 用於 optimistic concurrency：每次更新 +1，approve/reject 帶入
-- 讀到的 revision，避免兩個審核者同時操作同一個 run。

CREATE TABLE IF NOT EXISTS maya_sawa_research_pipeline_runs (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL,
  triggered_by TEXT NOT NULL,
  dry_run BOOLEAN NOT NULL DEFAULT TRUE,
  current_node TEXT,

  mapping_provenance JSONB,
  evidence JSONB,
  retrieval_evaluation JSONB,
  retrieval_verdict TEXT,
  correction_attempts INTEGER NOT NULL DEFAULT 0,
  refined_evidence JSONB,
  change_set JSONB,
  diff_summary JSONB,
  validation_warnings JSONB,

  approval_decision TEXT,
  approved_by TEXT,
  approval_note TEXT,
  approval_decided_at TIMESTAMPTZ,

  backup_version TEXT,
  published_version TEXT,

  failed_node TEXT,
  error TEXT,

  revision INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_maya_sawa_research_runs_status
  ON maya_sawa_research_pipeline_runs (status);

CREATE INDEX IF NOT EXISTS idx_maya_sawa_research_runs_created_at
  ON maya_sawa_research_pipeline_runs (created_at DESC);
