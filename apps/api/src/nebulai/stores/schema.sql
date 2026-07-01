CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE,
  name TEXT NOT NULL,
  avatar_url TEXT,
  provider TEXT NOT NULL DEFAULT 'email',
  provider_subject TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workspace_members (
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'owner',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE IF NOT EXISTS auth_email_codes (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO users (id, email, name, provider)
VALUES ('local-user', 'local@nebulai.dev', 'Local User', 'local')
ON CONFLICT (id) DO NOTHING;

INSERT INTO workspaces (id, name, owner_user_id)
VALUES ('local-workspace', 'Local Workspace', 'local-user')
ON CONFLICT (id) DO NOTHING;

INSERT INTO workspace_members (workspace_id, user_id, role)
VALUES ('local-workspace', 'local-user', 'owner')
ON CONFLICT (workspace_id, user_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE,
  title TEXT NOT NULL DEFAULT '新的知识库问答',
  summary TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  status TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_blobs (
  document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
  content_type TEXT NOT NULL DEFAULT 'unknown',
  byte_size INTEGER NOT NULL DEFAULT 0,
  data BYTEA NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE,
  parent_id TEXT REFERENCES chunks(id) ON DELETE CASCADE,
  level TEXT NOT NULL CHECK (level IN ('L1', 'L2', 'L3')),
  ordinal INTEGER NOT NULL DEFAULT 0,
  text TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag_runs (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE,
  question TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  mode TEXT NOT NULL DEFAULT 'mock',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE,
  kind TEXT NOT NULL DEFAULT 'document_ingestion',
  status TEXT NOT NULL DEFAULT 'queued',
  progress INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  worker_id TEXT,
  error TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  locked_at TIMESTAMPTZ,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag_steps (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES rag_runs(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL,
  status TEXT NOT NULL,
  score DOUBLE PRECISION,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag_sources (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES rag_runs(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE,
  document_title TEXT NOT NULL,
  chunk_id TEXT NOT NULL,
  excerpt TEXT NOT NULL,
  score DOUBLE PRECISION,
  rerank_score DOUBLE PRECISION,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE;
ALTER TABLE rag_runs ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE rag_runs ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE;
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE;
ALTER TABLE rag_steps ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE rag_steps ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE;
ALTER TABLE rag_sources ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'local-user' REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE rag_sources ADD COLUMN IF NOT EXISTS workspace_id TEXT NOT NULL DEFAULT 'local-workspace' REFERENCES workspaces(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_rag_steps_run_created ON rag_steps(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chunks_document_level ON chunks(document_id, level);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status_created ON ingestion_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_document_created ON ingestion_jobs(document_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_workspace_updated ON sessions(workspace_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_workspace_updated ON documents(workspace_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chunks_workspace_ids ON chunks(workspace_id, id);
CREATE INDEX IF NOT EXISTS idx_rag_runs_workspace_session ON rag_runs(workspace_id, session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_workspace_created ON ingestion_jobs(workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_email_codes_email_created ON auth_email_codes(email, created_at DESC);
