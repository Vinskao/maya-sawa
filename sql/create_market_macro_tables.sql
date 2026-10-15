-- Additive macro data schema. Safe to re-run; does not touch market/company data.
CREATE TABLE IF NOT EXISTS maya_sawa_macro_series (
  code text PRIMARY KEY, name text NOT NULL, unit text NOT NULL, frequency text NOT NULL, source text NOT NULL
);
CREATE TABLE IF NOT EXISTS maya_sawa_macro_observations (
  id bigserial PRIMARY KEY, series_code text NOT NULL REFERENCES maya_sawa_macro_series(code),
  reference_period text NOT NULL, value text NOT NULL, preliminary integer NOT NULL DEFAULT 0,
  source_published_at timestamptz, fetched_at timestamptz NOT NULL, source text NOT NULL,
  CONSTRAINT uq_macro_observation_period UNIQUE(series_code, reference_period)
);
CREATE INDEX IF NOT EXISTS ix_maya_sawa_macro_observations_series ON maya_sawa_macro_observations(series_code);
CREATE TABLE IF NOT EXISTS maya_sawa_macro_observation_revisions (
  id bigserial PRIMARY KEY, series_code text NOT NULL, reference_period text NOT NULL,
  old_value text, new_value text NOT NULL, changed_at timestamptz NOT NULL, source text NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_maya_sawa_macro_observation_revisions_series ON maya_sawa_macro_observation_revisions(series_code);
CREATE TABLE IF NOT EXISTS maya_sawa_macro_events (
  id text PRIMARY KEY, source_id text NOT NULL, group_id text NOT NULL, event_type text NOT NULL, title text NOT NULL,
  reference_period text, scheduled_date date NOT NULL, scheduled_at timestamptz, time_precision text NOT NULL DEFAULT 'date',
  schedule_verification text NOT NULL DEFAULT 'expected', published_at timestamptz, status text NOT NULL DEFAULT 'scheduled',
  consensus_value text, actual_value text, surprise_value text, expectation_source text,
  source text NOT NULL, source_url text NOT NULL, updated_at timestamptz NOT NULL,
  CONSTRAINT uq_macro_event_source_id UNIQUE(source, source_id)
);
-- Safe additive upgrade for installations created before consensus comparison was added.
ALTER TABLE maya_sawa_macro_events ADD COLUMN IF NOT EXISTS consensus_value text;
ALTER TABLE maya_sawa_macro_events ADD COLUMN IF NOT EXISTS actual_value text;
ALTER TABLE maya_sawa_macro_events ADD COLUMN IF NOT EXISTS surprise_value text;
ALTER TABLE maya_sawa_macro_events ADD COLUMN IF NOT EXISTS expectation_source text;
CREATE INDEX IF NOT EXISTS ix_maya_sawa_macro_events_group ON maya_sawa_macro_events(group_id);
CREATE INDEX IF NOT EXISTS ix_maya_sawa_macro_events_date ON maya_sawa_macro_events(scheduled_date);
CREATE TABLE IF NOT EXISTS maya_sawa_macro_event_revisions (
  id bigserial PRIMARY KEY, event_id text NOT NULL, changed_at timestamptz NOT NULL, old_payload text NOT NULL, new_payload text NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_maya_sawa_macro_event_revisions_event ON maya_sawa_macro_event_revisions(event_id);
CREATE TABLE IF NOT EXISTS maya_sawa_macro_fetch_runs (
  id bigserial PRIMARY KEY, source text NOT NULL, started_at timestamptz NOT NULL, finished_at timestamptz,
  status text NOT NULL, http_status integer, record_count integer NOT NULL DEFAULT 0, detail text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_maya_sawa_macro_fetch_runs_source ON maya_sawa_macro_fetch_runs(source);
CREATE INDEX IF NOT EXISTS ix_maya_sawa_macro_fetch_runs_started ON maya_sawa_macro_fetch_runs(started_at);
