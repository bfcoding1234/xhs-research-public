PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS authors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id TEXT NOT NULL UNIQUE,
    xhs_id TEXT DEFAULT '',
    display_name TEXT DEFAULT '',
    profile_url TEXT DEFAULT '',
    bio TEXT DEFAULT '',
    ip_location TEXT DEFAULT '',
    followers_count INTEGER,
    following_count INTEGER,
    likes_collections_count INTEGER,
    total_post_count INTEGER,
    avatar_url TEXT DEFAULT '',
    avatar_local_path TEXT DEFAULT '',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_profile_fetched_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id TEXT NOT NULL UNIQUE,
    author_id INTEGER REFERENCES authors(id),
    title TEXT DEFAULT '',
    content TEXT DEFAULT '',
    note_type TEXT DEFAULT '',
    note_url TEXT DEFAULT '',
    cover_url TEXT DEFAULT '',
    cover_local_path TEXT DEFAULT '',
    publish_date TEXT DEFAULT '',
    likes_count INTEGER,
    favorites_count INTEGER,
    comments_count INTEGER,
    detail_level TEXT NOT NULL DEFAULT 'card',
    content_hash TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_detail_fetched_at TEXT,
    last_comments_fetched_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    research_type TEXT NOT NULL CHECK (research_type IN ('author','keyword','mixed')),
    status TEXT NOT NULL DEFAULT 'active',
    config_json TEXT NOT NULL DEFAULT '{}',
    latest_report_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    author_id INTEGER REFERENCES authors(id) ON DELETE SET NULL,
    post_id INTEGER REFERENCES posts(id) ON DELETE SET NULL,
    task_type TEXT NOT NULL DEFAULT 'research' CHECK (task_type IN ('research','vision','ai_report','keyword_suggestions','comments')),
    mode TEXT NOT NULL CHECK (mode IN ('author','keyword','mixed','post')),
    created_from TEXT NOT NULL CHECK (created_from IN ('codex','web','test')),
    input_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    current_phase TEXT NOT NULL DEFAULT 'queued',
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS post_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    comment_id TEXT NOT NULL,
    parent_comment_id TEXT NOT NULL DEFAULT '',
    root_comment_id TEXT NOT NULL DEFAULT '',
    comment_type TEXT NOT NULL CHECK (comment_type IN ('root','reply_preview')),
    is_reply_preview INTEGER NOT NULL DEFAULT 0,
    author_user_id TEXT DEFAULT '',
    author_name TEXT DEFAULT '',
    author_avatar_url TEXT DEFAULT '',
    content TEXT DEFAULT '',
    likes_count INTEGER NOT NULL DEFAULT 0,
    published_at TEXT DEFAULT '',
    ip_location TEXT DEFAULT '',
    platform_reply_count INTEGER NOT NULL DEFAULT 0,
    status INTEGER,
    is_invalid INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(post_id, comment_id)
);

CREATE TABLE IF NOT EXISTS task_comments (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    post_comment_id INTEGER NOT NULL REFERENCES post_comments(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    page_rank INTEGER NOT NULL,
    is_reply_preview INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (task_id, post_comment_id)
);

CREATE TABLE IF NOT EXISTS post_comment_checkpoints (
    post_id INTEGER PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    next_cursor TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','exhausted','invalid')),
    completed_pages INTEGER NOT NULL DEFAULT 0,
    last_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    last_error TEXT NOT NULL DEFAULT '',
    captured_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_posts (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    first_task_id TEXT REFERENCES tasks(id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_featured INTEGER NOT NULL DEFAULT 0,
    popularity_score REAL,
    popularity_percentile REAL,
    popularity_level TEXT DEFAULT '',
    popularity_method TEXT DEFAULT '',
    score_version TEXT DEFAULT '',
    scored_at TEXT,
    project_notes TEXT DEFAULT '',
    PRIMARY KEY (project_id, post_id)
);

CREATE TABLE IF NOT EXISTS project_authors (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    first_task_id TEXT REFERENCES tasks(id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    project_notes TEXT DEFAULT '',
    PRIMARY KEY (project_id, author_id, relation_type)
);

CREATE TABLE IF NOT EXISTS project_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    normalized_keyword TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, normalized_keyword)
);

CREATE TABLE IF NOT EXISTS task_posts (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_value TEXT NOT NULL,
    source_rank INTEGER,
    discovered_at TEXT NOT NULL,
    PRIMARY KEY (task_id, post_id, source_type, source_value)
);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    cache_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running','completed','failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    input_chars INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL DEFAULT '{}',
    diagnostics_json TEXT NOT NULL DEFAULT '{}',
    error_message TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(task_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS media_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    media_index INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    original_url TEXT DEFAULT '',
    local_path TEXT DEFAULT '',
    sha256 TEXT DEFAULT '',
    file_size_bytes INTEGER NOT NULL DEFAULT 0,
    ocr_text TEXT DEFAULT '',
    ocr_engine TEXT DEFAULT '',
    ocr_version TEXT DEFAULT '',
    ocr_completed_at TEXT,
    download_status TEXT NOT NULL DEFAULT 'pending',
    updated_at TEXT NOT NULL,
    UNIQUE(post_id, media_index, media_type)
);

CREATE TABLE IF NOT EXISTS vision_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    cache_key TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    image_scope TEXT NOT NULL DEFAULT 'all',
    analysis_json TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 0,
    UNIQUE(post_id, cache_key)
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    report_type TEXT NOT NULL,
    generator_type TEXT NOT NULL DEFAULT 'template',
    generator_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'completed',
    title TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    content_markdown TEXT NOT NULL,
    evidence_post_count INTEGER NOT NULL DEFAULT 0,
    evidence_author_count INTEGER NOT NULL DEFAULT 0,
    model TEXT DEFAULT '',
    prompt_version TEXT DEFAULT '',
    evidence_snapshot_json TEXT NOT NULL DEFAULT '{}',
    generation_config_json TEXT NOT NULL DEFAULT '{}',
    generated_at TEXT NOT NULL,
    UNIQUE(project_id, version)
);

CREATE TABLE IF NOT EXISTS author_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    report_type TEXT NOT NULL DEFAULT 'author',
    generator_type TEXT NOT NULL DEFAULT 'llm',
    generator_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'completed',
    title TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    content_markdown TEXT NOT NULL,
    evidence_post_count INTEGER NOT NULL DEFAULT 0,
    evidence_author_count INTEGER NOT NULL DEFAULT 1,
    model TEXT DEFAULT '',
    prompt_version TEXT DEFAULT '',
    evidence_snapshot_json TEXT NOT NULL DEFAULT '{}',
    generation_config_json TEXT NOT NULL DEFAULT '{}',
    generated_at TEXT NOT NULL,
    UNIQUE(author_id, version)
);

CREATE TABLE IF NOT EXISTS report_presentations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_report_id INTEGER REFERENCES reports(id) ON DELETE CASCADE,
    author_report_id INTEGER REFERENCES author_reports(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'generating' CHECK (status IN ('generating','completed')),
    title TEXT NOT NULL,
    page_mode TEXT NOT NULL DEFAULT 'standard' CHECK (page_mode IN ('concise','standard','complete')),
    slide_count INTEGER NOT NULL DEFAULT 0,
    slides_json TEXT NOT NULL DEFAULT '{}',
    html_content TEXT NOT NULL DEFAULT '',
    model TEXT DEFAULT '',
    prompt_version TEXT DEFAULT '',
    generation_config_json TEXT NOT NULL DEFAULT '{}',
    generated_at TEXT NOT NULL,
    CHECK ((project_report_id IS NOT NULL) != (author_report_id IS NOT NULL)),
    UNIQUE(project_report_id, version),
    UNIQUE(author_report_id, version)
);

CREATE INDEX IF NOT EXISTS idx_report_presentations_project_report
ON report_presentations(project_report_id, version DESC);

CREATE INDEX IF NOT EXISTS idx_report_presentations_author_report
ON report_presentations(author_report_id, version DESC);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_releases (
    id TEXT PRIMARY KEY,
    source_data_dir TEXT NOT NULL,
    target_data_dir TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed','failed')),
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    error_message TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_id);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id, id);
CREATE INDEX IF NOT EXISTS idx_report_chunks_cache ON report_chunks(cache_key, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_report_chunks_task ON report_chunks(task_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_project_posts_project ON project_posts(project_id);
CREATE INDEX IF NOT EXISTS idx_project_keywords_project ON project_keywords(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_posts_post_task ON task_posts(post_id, task_id);
CREATE INDEX IF NOT EXISTS idx_vision_cache_key ON vision_analyses(cache_key);
CREATE INDEX IF NOT EXISTS idx_data_releases_created ON data_releases(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_post_comments_post ON post_comments(post_id, comment_type, id);
CREATE INDEX IF NOT EXISTS idx_task_comments_task ON task_comments(task_id, page_number, page_rank);

-- Database.initialize installs the partial unique active-enrichment index
-- only after reconciling duplicate active tasks in databases from older releases.
