-- ============================================
-- Multi-Domain Chatbot - Supabase Schema
-- Run this in Supabase SQL Editor
-- ============================================

-- 1. Chat Sessions
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT 'New Chat',
    user_id TEXT DEFAULT 'default',
    context_summary TEXT DEFAULT '',
    summary_message_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_sessions_domain ON chat_sessions(domain);
CREATE INDEX idx_sessions_user ON chat_sessions(user_id);
CREATE INDEX idx_sessions_updated ON chat_sessions(updated_at DESC);

-- 2. Chat Messages
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    image_data TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_messages_session ON chat_messages(session_id);

-- 3. LLM Config
CREATE TABLE IF NOT EXISTS llm_config (
    id INTEGER PRIMARY KEY DEFAULT 1,
    model TEXT NOT NULL DEFAULT 'openai/gpt-4o-mini',
    temperature REAL NOT NULL DEFAULT 0.7,
    max_tokens INTEGER NOT NULL DEFAULT 2048,
    system_prompt TEXT DEFAULT '',
    stream BOOLEAN NOT NULL DEFAULT true,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 4. Agent Memory (Self-Improvement)
-- Each domain agent stores learned insights about each user
-- This enables personalized responses over time
CREATE TABLE IF NOT EXISTS agent_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL DEFAULT 'default',
    domain TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    importance INTEGER DEFAULT 5,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_memory_user_domain ON agent_memory(user_id, domain);
CREATE INDEX idx_memory_importance ON agent_memory(importance DESC);

-- Memory types:
--   'preference'   : User preferences (e.g., likes action movies, vegetarian diet)
--   'context'      : Background info (e.g., has knee injury, loves Nolan films)
--   'feedback'     : What worked/didn't (e.g., user liked detailed explanations)
--   'goal'         : User goals (e.g., lose 5kg, watch all Oscar winners)
--   'interaction'  : Key interaction summaries for continuity

COMMENT ON TABLE agent_memory IS 'Per-user, per-domain agent memory for self-improvement and personalization';
COMMENT ON COLUMN agent_memory.memory_type IS 'preference | context | feedback | goal | interaction';
COMMENT ON COLUMN agent_memory.importance IS '1-10 scale, higher = more important to recall';

-- 5. Domain Knowledge (for rule-based responses without LLM)
-- Generic table for all domains: movie, healthcare, construction, etc.
CREATE TABLE IF NOT EXISTS domain_knowledge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain TEXT NOT NULL,
    external_id TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    data JSONB NOT NULL DEFAULT '{}',
    tags TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(domain, external_id)
);

CREATE INDEX idx_knowledge_domain ON domain_knowledge(domain);
CREATE INDEX idx_knowledge_category ON domain_knowledge(domain, category);
CREATE INDEX idx_knowledge_tags ON domain_knowledge USING GIN(tags);
CREATE INDEX idx_knowledge_title ON domain_knowledge USING GIN(to_tsvector('simple', title));
CREATE INDEX idx_knowledge_content ON domain_knowledge USING GIN(to_tsvector('simple', content));
CREATE INDEX idx_knowledge_data ON domain_knowledge USING GIN(data);

COMMENT ON TABLE domain_knowledge IS 'Domain-specific knowledge base for rule-based responses without LLM';
COMMENT ON COLUMN domain_knowledge.external_id IS 'Unique ID from source (e.g., tmdb_123, wiki_456)';
COMMENT ON COLUMN domain_knowledge.category IS 'Type within domain (e.g., movie, genre, actor for movie domain)';
COMMENT ON COLUMN domain_knowledge.data IS 'Flexible JSONB for domain-specific structured data';
COMMENT ON COLUMN domain_knowledge.tags IS 'Searchable tags array for keyword matching';

-- 6. Insert default config
INSERT INTO llm_config (id, model, temperature, max_tokens, system_prompt, stream)
VALUES (1, 'openai/gpt-4o-mini', 0.7, 2048, '', true)
ON CONFLICT (id) DO NOTHING;

-- ============================================
-- Migration: Context Management (Sliding Window + Summary)
-- Run this if tables already exist
-- ============================================
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS context_summary TEXT DEFAULT '';
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS summary_message_count INTEGER DEFAULT 0;
