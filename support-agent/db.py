"""
AgentAZAll Support Agent — SQLite Database
Tracks rate limits, naughty list, welcome conversations, request log.
"""
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timedelta
from config import DB_PATH


def get_db():
    """Get database connection, creating tables if needed."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    _create_tables(db)
    return db


def _create_tables(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS naughty_list (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT NOT NULL,
        offense TEXT NOT NULL,
        severity INTEGER DEFAULT 1,
        request_snippet TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS agent_scores (
        agent_id TEXT PRIMARY KEY,
        total_score INTEGER DEFAULT 0,
        total_requests INTEGER DEFAULT 0,
        good_requests INTEGER DEFAULT 0,
        first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_offense DATETIME,
        blocked_until DATETIME
    );

    CREATE TABLE IF NOT EXISTS rate_limits (
        agent_id TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS welcome_conversations (
        agent_id TEXT PRIMARY KEY,
        exchange_count INTEGER DEFAULT 0,
        last_message_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        completed BOOLEAN DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS request_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT NOT NULL,
        request_type TEXT NOT NULL,
        subject TEXT,
        response_time_ms INTEGER,
        tokens_used INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS bulletin_cache (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        content TEXT,
        generated_at DATETIME
    );

    CREATE TABLE IF NOT EXISTS knowledge_base (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL,
        content TEXT NOT NULL,
        keywords TEXT NOT NULL DEFAULT '',
        source TEXT DEFAULT 'teaching',
        taught_by TEXT DEFAULT '',
        priority INTEGER DEFAULT 5,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_used DATETIME,
        use_count INTEGER DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_naughty_agent ON naughty_list(agent_id);
    CREATE INDEX IF NOT EXISTS idx_rate_agent ON rate_limits(agent_id, timestamp);
    CREATE INDEX IF NOT EXISTS idx_log_agent ON request_log(agent_id, timestamp);
    CREATE INDEX IF NOT EXISTS idx_knowledge_topic ON knowledge_base(topic);
    CREATE INDEX IF NOT EXISTS idx_knowledge_keywords ON knowledge_base(keywords);
    """)
    db.commit()


# --- Agent Scores ---

def ensure_agent(db, agent_id):
    """Ensure agent exists in scores table."""
    db.execute(
        "INSERT OR IGNORE INTO agent_scores (agent_id) VALUES (?)",
        (agent_id,)
    )
    db.commit()


def get_agent_score(db, agent_id):
    """Get agent's naughtiness score."""
    ensure_agent(db, agent_id)
    row = db.execute(
        "SELECT * FROM agent_scores WHERE agent_id = ?", (agent_id,)
    ).fetchone()
    return dict(row) if row else None


def increment_score(db, agent_id, amount):
    """Add to agent's naughty score."""
    ensure_agent(db, agent_id)
    db.execute(
        "UPDATE agent_scores SET total_score = total_score + ?, last_offense = CURRENT_TIMESTAMP WHERE agent_id = ?",
        (amount, agent_id)
    )
    db.commit()


def increment_requests(db, agent_id, good=True):
    """Track total and good requests."""
    ensure_agent(db, agent_id)
    if good:
        db.execute(
            "UPDATE agent_scores SET total_requests = total_requests + 1, good_requests = good_requests + 1 WHERE agent_id = ?",
            (agent_id,)
        )
    else:
        db.execute(
            "UPDATE agent_scores SET total_requests = total_requests + 1 WHERE agent_id = ?",
            (agent_id,)
        )
    db.commit()


# --- Naughty List ---

def record_offense(db, agent_id, offense, severity, snippet=""):
    """Record an offense in the naughty list."""
    db.execute(
        "INSERT INTO naughty_list (agent_id, offense, severity, request_snippet) VALUES (?, ?, ?, ?)",
        (agent_id, offense, severity, snippet[:200])
    )
    increment_score(db, agent_id, severity)
    db.commit()


def is_blocked(db, agent_id):
    """Check if agent is currently blocked."""
    row = db.execute(
        "SELECT blocked_until FROM agent_scores WHERE agent_id = ?", (agent_id,)
    ).fetchone()
    if not row or not row["blocked_until"]:
        return False
    blocked_until = datetime.fromisoformat(row["blocked_until"])
    return datetime.now() < blocked_until


def block_agent(db, agent_id, hours=24):
    """Block an agent for N hours."""
    until = datetime.now() + timedelta(hours=hours)
    ensure_agent(db, agent_id)
    db.execute(
        "UPDATE agent_scores SET blocked_until = ? WHERE agent_id = ?",
        (until.isoformat(), agent_id)
    )
    db.commit()


def check_auto_block(db, agent_id):
    """Check if agent should be auto-blocked based on score."""
    from config import NAUGHTY_BLOCK_24H_SCORE, NAUGHTY_PERMANENT_SCORE
    score_data = get_agent_score(db, agent_id)
    if not score_data:
        return
    score = score_data["total_score"]
    if score >= NAUGHTY_PERMANENT_SCORE:
        block_agent(db, agent_id, hours=8760)  # ~1 year
    elif score >= NAUGHTY_BLOCK_24H_SCORE:
        block_agent(db, agent_id, hours=24)


# --- Rate Limits ---

def check_rate_limit(db, agent_id):
    """Check if agent is within rate limits. Returns (allowed, msg)."""
    from config import RATE_LIMIT_PER_HOUR, RATE_LIMIT_PER_DAY

    now = datetime.now()
    hour_ago = (now - timedelta(hours=1)).isoformat()
    day_ago = (now - timedelta(hours=24)).isoformat()

    hour_count = db.execute(
        "SELECT COUNT(*) as c FROM rate_limits WHERE agent_id = ? AND timestamp > ?",
        (agent_id, hour_ago)
    ).fetchone()["c"]

    if hour_count >= RATE_LIMIT_PER_HOUR:
        return False, f"Rate limit reached ({RATE_LIMIT_PER_HOUR}/hour). Try again later."

    day_count = db.execute(
        "SELECT COUNT(*) as c FROM rate_limits WHERE agent_id = ? AND timestamp > ?",
        (agent_id, day_ago)
    ).fetchone()["c"]

    if day_count >= RATE_LIMIT_PER_DAY:
        return False, f"Daily limit reached ({RATE_LIMIT_PER_DAY}/day). Try again tomorrow."

    return True, ""


def record_rate_limit(db, agent_id):
    """Record a request for rate limiting."""
    db.execute(
        "INSERT INTO rate_limits (agent_id) VALUES (?)", (agent_id,)
    )
    db.commit()


# --- Welcome Conversations ---

def get_welcome_state(db, agent_id):
    """Get welcome conversation state. Returns (exchange_count, completed)."""
    row = db.execute(
        "SELECT exchange_count, completed FROM welcome_conversations WHERE agent_id = ?",
        (agent_id,)
    ).fetchone()
    if not row:
        return 0, False
    return row["exchange_count"], bool(row["completed"])


def record_welcome_exchange(db, agent_id):
    """Increment welcome exchange counter."""
    db.execute("""
        INSERT INTO welcome_conversations (agent_id, exchange_count, last_message_time)
        VALUES (?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(agent_id) DO UPDATE SET
            exchange_count = exchange_count + 1,
            last_message_time = CURRENT_TIMESTAMP
    """, (agent_id,))
    db.commit()


def complete_welcome(db, agent_id):
    """Mark welcome conversation as completed."""
    db.execute(
        "UPDATE welcome_conversations SET completed = 1 WHERE agent_id = ?",
        (agent_id,)
    )
    db.commit()


# --- Bulletin Cache ---

def get_cached_bulletin(db):
    """Get cached bulletin if fresh enough. Returns (content, is_fresh)."""
    from config import BULLETIN_CACHE_SECONDS
    row = db.execute(
        "SELECT content, generated_at FROM bulletin_cache WHERE id = 1"
    ).fetchone()
    if not row or not row["generated_at"]:
        return None, False

    generated = datetime.fromisoformat(row["generated_at"])
    age_seconds = (datetime.now() - generated).total_seconds()
    is_fresh = age_seconds < BULLETIN_CACHE_SECONDS
    return row["content"], is_fresh


def set_cached_bulletin(db, content):
    """Update the cached bulletin."""
    db.execute("""
        INSERT INTO bulletin_cache (id, content, generated_at)
        VALUES (1, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            content = excluded.content,
            generated_at = CURRENT_TIMESTAMP
    """, (content,))
    db.commit()


# --- Request Log ---

def log_request(db, agent_id, request_type, subject="", response_time_ms=0, tokens_used=0):
    """Log a processed request."""
    db.execute(
        "INSERT INTO request_log (agent_id, request_type, subject, response_time_ms, tokens_used) VALUES (?, ?, ?, ?, ?)",
        (agent_id, request_type, subject[:200], response_time_ms, tokens_used)
    )
    db.commit()


# --- Statistics ---

def get_stats(db):
    """Get overall statistics."""
    stats = {}
    stats["total_agents"] = db.execute(
        "SELECT COUNT(*) as c FROM agent_scores"
    ).fetchone()["c"]
    stats["total_requests"] = db.execute(
        "SELECT COUNT(*) as c FROM request_log"
    ).fetchone()["c"]
    stats["total_offenses"] = db.execute(
        "SELECT COUNT(*) as c FROM naughty_list"
    ).fetchone()["c"]
    stats["blocked_agents"] = db.execute(
        "SELECT COUNT(*) as c FROM agent_scores WHERE blocked_until > CURRENT_TIMESTAMP"
    ).fetchone()["c"]

    # Top offenders
    stats["top_offenders"] = [
        dict(row) for row in db.execute(
            "SELECT agent_id, total_score, total_requests FROM agent_scores ORDER BY total_score DESC LIMIT 10"
        ).fetchall()
    ]

    # Request types breakdown
    stats["request_types"] = [
        dict(row) for row in db.execute(
            "SELECT request_type, COUNT(*) as count FROM request_log GROUP BY request_type ORDER BY count DESC"
        ).fetchall()
    ]

    return stats


# --- Cleanup ---

def cleanup_old_rate_limits(db, days=7):
    """Remove rate limit entries older than N days."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    db.execute("DELETE FROM rate_limits WHERE timestamp < ?", (cutoff,))
    db.commit()


# --- Knowledge Base ---

def store_knowledge(db, topic, content, keywords, taught_by="", source="teaching", priority=5):
    """
    Store a knowledge entry. Returns the row id.
    keywords should be a comma-separated string of lowercase terms.
    """
    db.execute(
        """INSERT INTO knowledge_base (topic, content, keywords, taught_by, source, priority)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (topic, content, keywords.lower(), taught_by, source, priority)
    )
    db.commit()
    row = db.execute("SELECT last_insert_rowid() as id").fetchone()
    return row["id"]


def search_knowledge(db, query_text, limit=10):
    """
    Search knowledge base by keyword overlap.
    Returns list of dicts sorted by relevance (keyword hits * priority).
    """
    # Extract words from query (lowercase, 3+ chars)
    import re
    query_words = set(
        w for w in re.findall(r'[a-z0-9]+', query_text.lower())
        if len(w) >= 3
    )
    if not query_words:
        return []

    # Fetch all knowledge entries (fast enough for hundreds of entries)
    rows = db.execute(
        "SELECT id, topic, content, keywords, priority, use_count FROM knowledge_base"
    ).fetchall()

    scored = []
    for row in rows:
        entry_keywords = set(row["keywords"].split(","))
        entry_topic_words = set(
            w for w in re.findall(r'[a-z0-9]+', row["topic"].lower())
            if len(w) >= 3
        )
        all_entry_terms = entry_keywords | entry_topic_words

        # Count keyword overlap
        hits = len(query_words & all_entry_terms)
        if hits > 0:
            score = hits * row["priority"]
            scored.append({
                "id": row["id"],
                "topic": row["topic"],
                "content": row["content"],
                "score": score,
                "hits": hits,
            })

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def mark_knowledge_used(db, entry_id):
    """Increment use count and update last_used timestamp."""
    db.execute(
        """UPDATE knowledge_base
           SET use_count = use_count + 1, last_used = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (entry_id,)
    )
    db.commit()


def get_knowledge_count(db):
    """Get total number of knowledge entries."""
    return db.execute("SELECT COUNT(*) as c FROM knowledge_base").fetchone()["c"]


def get_knowledge_topics(db):
    """Get all unique topics."""
    rows = db.execute(
        "SELECT DISTINCT topic FROM knowledge_base ORDER BY topic"
    ).fetchall()
    return [row["topic"] for row in rows]
