-- Git commit knowledge table for maya-sawa.
-- Stores parsed git log metadata plus an optional pgvector embedding.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS maya_sawa_git_commits (
  id BIGSERIAL PRIMARY KEY,
  commit_hash CHAR(40) UNIQUE NOT NULL,
  git_url VARCHAR(500),
  commit_time TIMESTAMPTZ NOT NULL,
  commit_message TEXT,
  changed_files_summary TEXT,
  embedding vector(1536),
  is_trivial BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_maya_sawa_git_commits_commit_time
  ON maya_sawa_git_commits (commit_time DESC);

CREATE INDEX IF NOT EXISTS idx_maya_sawa_git_commits_is_trivial
  ON maya_sawa_git_commits (is_trivial);
