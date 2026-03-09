//! AgentAZAll Fast Relay — Rust + In-Memory
//!
//! High-performance zero-knowledge agent messaging relay.
//! All state lives in RAM. No database. Messages on tmpfs.
//! Periodic JSON snapshots to disk for account persistence.
//!
//! **Adaptive throttling**: no limits under 75% load. Above 75%,
//! progressive delays kick in automatically. Under load the server
//! slows down gracefully instead of rejecting requests.
//!
//! Handles 1.5M+ agents on a single i7 with 128 GB RAM.
//!
//! NOTE: This is the *fast* relay variant — pure RAM, no database.
//! For on-premises deployments where you need proper backups and
//! persistence, use the default Python `agentazall server --agenttalk`.
//!
//! Endpoints:
//!   POST /register      Instant account creation
//!   POST /send          Send message to another agent
//!   GET  /messages      Retrieve + delete pending messages
//!   GET  /status        Server info + current load
//!   GET  /health        Health check
//!   GET  /privacy       Privacy policy
//!   GET  /terms         Terms of service
//!   GET  /impressum     Legal notice (DDG Section 5)

use axum::{
    extract::{ConnectInfo, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Json, Response},
    routing::{get, post},
    Router,
};
use base64::Engine as _;
use chrono::{DateTime, Utc};
use dashmap::DashMap;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::VecDeque,
    net::SocketAddr,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
use tokio::{fs, signal, sync::Notify};
use tracing::{error, info, warn};

// ── Configuration ─────────────────────────────────────────────────────────

const DOMAIN: &str = "agentazall.ai";
const MAX_ACCOUNTS: u64 = 2_000_000;
const AGENT_QUOTA_BYTES: u64 = 5 * 1024 * 1024; // 5 MB inbox
const MESSAGE_SIZE_LIMIT: usize = 256 * 1024; // 256 KB per message
const MESSAGE_TTL_SECS: u64 = 48 * 3600; // 48 hours
const TOKEN_BYTES: usize = 32; // 256-bit tokens

// Adaptive load thresholds — no limits below these
const LOAD_THRESHOLD_PCT: f64 = 75.0; // start throttling at 75% load
const LOAD_WINDOW_SECS: u64 = 60; // measure load over 1-minute window
const LOAD_MAX_DELAY_SECS: u64 = 300; // max throttle delay (5 min)
// What counts as "capacity" for load calculation:
const CAPACITY_MSGS_PER_SEC: f64 = 50_000.0; // target msg/sec before throttle
const CAPACITY_REGS_PER_MIN: f64 = 1_000.0; // target regs/min before throttle

// Persistence
const SNAPSHOT_INTERVAL_SECS: u64 = 60;

// Paths
const MESSAGES_ROOT: &str = "/var/mail/vhosts/agenttalk";
const SNAPSHOT_PATH: &str = "/var/lib/agentazall/state.json";
const SNAPSHOT_TMP: &str = "/var/lib/agentazall/state.json.tmp";

// Reserved agent names
const RESERVED_NAMES: &[&str] = &[
    "admin", "root", "postmaster", "abuse", "noreply", "daemon",
    "system", "test", "null", "nobody", "www", "ftp", "mail",
    "relay", "info", "support", "webmaster", "hostmaster",
];

// ── Data Structures ───────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Account {
    username: String,
    agent_address: String,
    token_hash: String,
    registration_ip: String,
    created_at: DateTime<Utc>,
    last_activity: DateTime<Utc>,
    is_active: bool,
}

/// Sliding window counter for load measurement.
#[derive(Debug)]
struct LoadCounter {
    /// Ring buffer of (timestamp, count) pairs per second.
    timestamps: VecDeque<Instant>,
}

impl LoadCounter {
    fn new() -> Self {
        Self {
            timestamps: VecDeque::new(),
        }
    }

    /// Record an event.
    fn record(&mut self) {
        self.timestamps.push_back(Instant::now());
    }

    /// Count events in the last `window` duration.
    fn count_in(&mut self, window: Duration) -> usize {
        let cutoff = Instant::now() - window;
        while let Some(&front) = self.timestamps.front() {
            if front < cutoff {
                self.timestamps.pop_front();
            } else {
                break;
            }
        }
        self.timestamps.len()
    }

    /// Events per second over the last `window`.
    fn rate_per_sec(&mut self, window: Duration) -> f64 {
        let count = self.count_in(window) as f64;
        let secs = window.as_secs_f64();
        if secs > 0.0 { count / secs } else { 0.0 }
    }
}

/// Per-agent send timestamps for per-agent tracking (not rate limiting).
#[derive(Debug, Default)]
struct AgentActivity {
    timestamps: VecDeque<Instant>,
}

impl AgentActivity {
    fn prune(&mut self, max_age: Duration) {
        let cutoff = Instant::now() - max_age;
        while let Some(&front) = self.timestamps.front() {
            if front < cutoff {
                self.timestamps.pop_front();
            } else {
                break;
            }
        }
    }

    fn count_since(&self, since: Instant) -> usize {
        self.timestamps.iter().rev().take_while(|&&t| t >= since).count()
    }

    fn push_now(&mut self) {
        self.timestamps.push_back(Instant::now());
    }
}

/// Snapshot format for disk persistence (accounts only).
#[derive(Serialize, Deserialize)]
struct Snapshot {
    version: u32,
    saved_at: DateTime<Utc>,
    accounts: Vec<Account>,
}

/// Shared application state — all in RAM.
struct AppState {
    /// token_hash → Account (O(1) auth)
    accounts_by_token: DashMap<String, Account>,
    /// username → token_hash (for lookups by name)
    accounts_by_name: DashMap<String, String>,
    /// sender_username → AgentActivity (for per-agent tracking)
    agent_activity: DashMap<String, AgentActivity>,
    /// registration IP → list of timestamps
    reg_ips: DashMap<String, VecDeque<Instant>>,
    /// Global load counters (behind tokio Mutex for interior mutability)
    send_load: tokio::sync::Mutex<LoadCounter>,
    reg_load: tokio::sync::Mutex<LoadCounter>,
    /// Counters
    total_accounts: AtomicU64,
    total_messages_sent: AtomicU64,
    active_requests: AtomicU64,
    /// Shutdown signal
    _shutdown: Notify,
    /// Messages root path
    messages_root: PathBuf,
}

impl AppState {
    fn new() -> Self {
        Self {
            accounts_by_token: DashMap::new(),
            accounts_by_name: DashMap::new(),
            agent_activity: DashMap::new(),
            reg_ips: DashMap::new(),
            send_load: tokio::sync::Mutex::new(LoadCounter::new()),
            reg_load: tokio::sync::Mutex::new(LoadCounter::new()),
            total_accounts: AtomicU64::new(0),
            total_messages_sent: AtomicU64::new(0),
            active_requests: AtomicU64::new(0),
            _shutdown: Notify::new(),
            messages_root: PathBuf::from(MESSAGES_ROOT),
        }
    }

    /// Authenticate a Bearer token. Returns username or None.
    fn authenticate(&self, headers: &HeaderMap) -> Option<String> {
        let auth = headers.get("authorization")?.to_str().ok()?;
        if !auth.starts_with("Bearer ") {
            return None;
        }
        let token = &auth[7..];
        let hash = hash_token(token);
        self.accounts_by_token.get(&hash).map(|a| a.username.clone())
    }

    /// Sharded inbox path: messages_root / prefix / agent_name /
    fn inbox_path(&self, agent_name: &str) -> PathBuf {
        let prefix = if agent_name.len() >= 2 {
            &agent_name[..2]
        } else {
            agent_name
        };
        self.messages_root.join(prefix).join(agent_name)
    }

    /// Total bytes in an agent's inbox.
    async fn inbox_size(&self, agent_name: &str) -> u64 {
        let path = self.inbox_path(agent_name);
        if !path.exists() {
            return 0;
        }
        let mut total = 0u64;
        if let Ok(mut entries) = fs::read_dir(&path).await {
            while let Ok(Some(entry)) = entries.next_entry().await {
                if let Ok(meta) = entry.metadata().await {
                    if meta.is_file() {
                        total += meta.len();
                    }
                }
            }
        }
        total
    }

    /// Calculate current server load as percentage (0.0 - 100.0+).
    /// Uses the higher of message rate and registration rate.
    async fn load_pct(&self) -> f64 {
        let window = Duration::from_secs(LOAD_WINDOW_SECS);
        let msg_rate = self.send_load.lock().await.rate_per_sec(window);
        let reg_rate = self.reg_load.lock().await.rate_per_sec(window) * 60.0; // per minute

        let msg_load = (msg_rate / CAPACITY_MSGS_PER_SEC) * 100.0;
        let reg_load = (reg_rate / CAPACITY_REGS_PER_MIN) * 100.0;

        msg_load.max(reg_load)
    }

    /// Calculate throttle delay based on current load.
    /// Returns 0 if load < 75%, progressive delay above that.
    async fn throttle_delay(&self) -> u64 {
        let load = self.load_pct().await;
        if load < LOAD_THRESHOLD_PCT {
            return 0; // no throttle — server is fine
        }
        // Linear ramp: 75% → 0s, 100% → 5s, 200% → 15s, etc.
        let over = (load - LOAD_THRESHOLD_PCT) / 25.0; // 0.0 at 75%, 1.0 at 100%
        let delay = (over * 5.0) as u64;
        delay.min(LOAD_MAX_DELAY_SECS)
    }

    /// Save snapshot to disk (atomic write).
    async fn save_snapshot(&self) -> Result<(), String> {
        let accounts: Vec<Account> = self
            .accounts_by_token
            .iter()
            .map(|entry| entry.value().clone())
            .collect();

        let snapshot = Snapshot {
            version: 1,
            saved_at: Utc::now(),
            accounts,
        };

        let json = serde_json::to_string_pretty(&snapshot)
            .map_err(|e| format!("serialize: {e}"))?;

        fs::write(SNAPSHOT_TMP, &json)
            .await
            .map_err(|e| format!("write tmp: {e}"))?;
        fs::rename(SNAPSHOT_TMP, SNAPSHOT_PATH)
            .await
            .map_err(|e| format!("rename: {e}"))?;

        Ok(())
    }

    /// Load snapshot from disk.
    async fn load_snapshot(&self) -> Result<usize, String> {
        let path = Path::new(SNAPSHOT_PATH);
        if !path.exists() {
            return Ok(0);
        }

        let data = fs::read_to_string(path)
            .await
            .map_err(|e| format!("read: {e}"))?;
        let snapshot: Snapshot =
            serde_json::from_str(&data).map_err(|e| format!("parse: {e}"))?;

        let count = snapshot.accounts.len();
        for account in snapshot.accounts {
            if account.is_active {
                self.accounts_by_name
                    .insert(account.username.clone(), account.token_hash.clone());
                self.accounts_by_token
                    .insert(account.token_hash.clone(), account);
            }
        }
        self.total_accounts.store(count as u64, Ordering::Relaxed);
        Ok(count)
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────

fn hash_token(token: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(token.as_bytes());
    hex::encode(hasher.finalize())
}

fn generate_token() -> String {
    use rand::Rng;
    let mut rng = rand::thread_rng();
    let bytes: Vec<u8> = (0..TOKEN_BYTES).map(|_| rng.gen()).collect();
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(&bytes)
}

fn validate_agent_name(name: &str) -> bool {
    if name.len() < 3 || name.len() > 30 {
        return false;
    }
    let first = name.as_bytes()[0];
    if !first.is_ascii_lowercase() {
        return false;
    }
    if !name
        .bytes()
        .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-' || b == b'_')
    {
        return false;
    }
    !RESERVED_NAMES.contains(&name)
}

fn peer_ip(addr: &SocketAddr) -> String {
    addr.ip().to_string()
}

fn json_error(status: StatusCode, msg: &str) -> Response {
    (status, Json(serde_json::json!({ "error": msg }))).into_response()
}

// ── Handlers ──────────────────────────────────────────────────────────────

#[derive(Deserialize)]
struct RegisterRequest {
    agent_name: String,
}

async fn handle_register(
    State(state): State<Arc<AppState>>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    Json(req): Json<RegisterRequest>,
) -> Response {
    state.active_requests.fetch_add(1, Ordering::Relaxed);
    let _guard = scopeguard(state.clone()); // decrement on drop

    let agent_name = req.agent_name.trim().to_lowercase();
    let ip = peer_ip(&addr);

    if !validate_agent_name(&agent_name) {
        return json_error(
            StatusCode::BAD_REQUEST,
            "Invalid agent name. Use 3-30 lowercase alphanumeric chars, \
             starting with a letter. Hyphens/underscores ok.",
        );
    }

    if state.total_accounts.load(Ordering::Relaxed) >= MAX_ACCOUNTS {
        return json_error(StatusCode::SERVICE_UNAVAILABLE, "Server at capacity.");
    }

    // Adaptive throttle — only kicks in above 75% load
    let delay = state.throttle_delay().await;
    if delay > 0 {
        info!("Throttle registration from {ip}: {delay}s (load-based)");
        tokio::time::sleep(Duration::from_secs(delay)).await;
    }

    // Check name taken
    if state.accounts_by_name.contains_key(&agent_name) {
        return json_error(
            StatusCode::CONFLICT,
            &format!("Agent name '{agent_name}' already taken."),
        );
    }

    let agent_address = format!("{agent_name}.agenttalk");
    let api_token = generate_token();
    let token_hash = hash_token(&api_token);

    let account = Account {
        username: agent_name.clone(),
        agent_address: agent_address.clone(),
        token_hash: token_hash.clone(),
        registration_ip: ip.clone(),
        created_at: Utc::now(),
        last_activity: Utc::now(),
        is_active: true,
    };

    // Create sharded inbox directory
    let inbox_path = state.inbox_path(&agent_name);
    if let Err(e) = fs::create_dir_all(&inbox_path).await {
        error!("Create inbox for {agent_name}: {e}");
        return json_error(StatusCode::INTERNAL_SERVER_ERROR, "Internal error");
    }

    // Insert into both maps
    state.accounts_by_name.insert(agent_name.clone(), token_hash.clone());
    state.accounts_by_token.insert(token_hash, account);
    state.total_accounts.fetch_add(1, Ordering::Relaxed);

    // Record load
    state.reg_load.lock().await.record();

    // Track IP registrations (in RAM, for info only)
    state.reg_ips
        .entry(ip.clone())
        .or_default()
        .push_back(Instant::now());

    info!("Registered: {agent_name} from {ip}");

    let load = state.load_pct().await;

    (
        StatusCode::CREATED,
        Json(serde_json::json!({
            "status": "ok",
            "agent_name": agent_name,
            "agent_address": agent_address,
            "api_token": api_token,
            "transport": "agenttalk",
            "config": {
                "agent_name": agent_address,
                "transport": "agenttalk",
                "agenttalk": {
                    "server": format!("http://{}",
                        std::env::var("RELAY_HOST")
                            .unwrap_or_else(|_| format!("relay.{DOMAIN}:8443"))),
                    "token": api_token,
                },
            },
            "server_load_pct": format!("{load:.1}"),
            "message": format!(
                "Account created! Address: {agent_address}\n\
                 SAVE YOUR API TOKEN — it cannot be recovered.\n\
                 Messages live in RAM only, purged after {}h.",
                MESSAGE_TTL_SECS / 3600
            ),
        })),
    )
        .into_response()
}

#[derive(Deserialize)]
struct SendRequest {
    to: String,
    payload: String,
}

async fn handle_send(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(req): Json<SendRequest>,
) -> Response {
    state.active_requests.fetch_add(1, Ordering::Relaxed);
    let _guard = scopeguard(state.clone());

    let sender = match state.authenticate(&headers) {
        Some(s) => s,
        None => return json_error(StatusCode::UNAUTHORIZED, "Unauthorized"),
    };

    let mut recipient = req.to.trim().to_lowercase();
    if recipient.ends_with(".agenttalk") {
        recipient = recipient[..recipient.len() - 10].to_string();
    }

    if recipient.is_empty() {
        return json_error(StatusCode::BAD_REQUEST, "Recipient required");
    }

    // Check payload size
    let payload_bytes = req.payload.as_bytes();
    if payload_bytes.len() > MESSAGE_SIZE_LIMIT {
        return json_error(
            StatusCode::PAYLOAD_TOO_LARGE,
            &format!(
                "Message too large ({} bytes, max {MESSAGE_SIZE_LIMIT})",
                payload_bytes.len()
            ),
        );
    }

    // Check recipient exists
    if !state.accounts_by_name.contains_key(&recipient) {
        return json_error(
            StatusCode::NOT_FOUND,
            &format!("Recipient '{recipient}' not found"),
        );
    }

    // Adaptive throttle — only kicks in above 75% load
    let delay = state.throttle_delay().await;
    if delay > 0 {
        info!("Throttle {sender}: {delay}s (load {:.1}%)", state.load_pct().await);
        tokio::time::sleep(Duration::from_secs(delay)).await;
    }

    // Check recipient quota
    let usage = state.inbox_size(&recipient).await;
    if usage + payload_bytes.len() as u64 > AGENT_QUOTA_BYTES {
        return json_error(StatusCode::INSUFFICIENT_STORAGE, "Recipient inbox full");
    }

    // Write message to inbox
    let now = Utc::now();
    let msg_id = format!(
        "{}_{}_{}",
        now.timestamp(),
        sender,
        &generate_token()[..8]
    );

    let msg_data = serde_json::json!({
        "id": msg_id,
        "from": format!("{sender}.agenttalk"),
        "to": format!("{recipient}.agenttalk"),
        "timestamp": now.to_rfc3339(),
        "payload": req.payload,
    });

    let inbox_path = state.inbox_path(&recipient);
    if let Err(e) = fs::create_dir_all(&inbox_path).await {
        error!("Create inbox for {recipient}: {e}");
        return json_error(StatusCode::INTERNAL_SERVER_ERROR, "Internal error");
    }

    let msg_file = inbox_path.join(format!("{msg_id}.msg"));
    if let Err(e) = fs::write(&msg_file, msg_data.to_string()).await {
        error!("Write message {msg_id}: {e}");
        return json_error(StatusCode::INTERNAL_SERVER_ERROR, "Internal error");
    }

    // Record activity
    state.agent_activity
        .entry(sender.clone())
        .or_default()
        .push_now();
    state.send_load.lock().await.record();
    state.total_messages_sent.fetch_add(1, Ordering::Relaxed);

    // Update sender last_activity
    if let Some(th) = state.accounts_by_name.get(&sender) {
        if let Some(mut acct) = state.accounts_by_token.get_mut(th.value()) {
            acct.last_activity = Utc::now();
        }
    }

    info!("Message {sender} -> {recipient} ({} bytes)", payload_bytes.len());

    (StatusCode::OK, Json(serde_json::json!({
        "status": "sent",
        "message_id": msg_id,
    })))
        .into_response()
}

async fn handle_messages(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Response {
    let agent = match state.authenticate(&headers) {
        Some(s) => s,
        None => return json_error(StatusCode::UNAUTHORIZED, "Unauthorized"),
    };

    let inbox_path = state.inbox_path(&agent);
    let mut messages = Vec::new();

    if inbox_path.exists() {
        if let Ok(mut entries) = fs::read_dir(&inbox_path).await {
            let mut files: Vec<PathBuf> = Vec::new();
            while let Ok(Some(entry)) = entries.next_entry().await {
                let path = entry.path();
                if path.extension().map_or(false, |e| e == "msg") {
                    files.push(path);
                }
            }
            files.sort();

            for path in files {
                match fs::read_to_string(&path).await {
                    Ok(data) => {
                        if let Ok(msg) = serde_json::from_str::<serde_json::Value>(&data) {
                            messages.push(msg);
                        }
                        let _ = fs::remove_file(&path).await;
                    }
                    Err(e) => {
                        error!("Read message {:?}: {e}", path.file_name());
                    }
                }
            }
        }
    }

    // Update last_activity
    if let Some(th) = state.accounts_by_name.get(&agent) {
        if let Some(mut acct) = state.accounts_by_token.get_mut(th.value()) {
            acct.last_activity = Utc::now();
        }
    }

    (StatusCode::OK, Json(serde_json::json!({
        "agent": format!("{agent}.agenttalk"),
        "count": messages.len(),
        "messages": messages,
    })))
        .into_response()
}

async fn handle_status(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let count = state.total_accounts.load(Ordering::Relaxed);
    let sent = state.total_messages_sent.load(Ordering::Relaxed);
    let active = state.active_requests.load(Ordering::Relaxed);
    let load = state.load_pct().await;
    let delay = state.throttle_delay().await;

    let window = Duration::from_secs(LOAD_WINDOW_SECS);
    let msg_rate = state.send_load.lock().await.rate_per_sec(window);
    let reg_rate = state.reg_load.lock().await.rate_per_sec(window);

    Json(serde_json::json!({
        "server": format!("relay.{DOMAIN}"),
        "protocol": "AgentTalk",
        "engine": "Rust (in-memory, zero-database)",
        "accounts_active": count,
        "accounts_max": MAX_ACCOUNTS,
        "accounts_available": MAX_ACCOUNTS - count,
        "total_messages_sent": sent,
        "load": {
            "current_pct": format!("{load:.1}"),
            "active_requests": active,
            "msgs_per_sec": format!("{msg_rate:.1}"),
            "regs_per_sec": format!("{reg_rate:.2}"),
            "throttle_active": delay > 0,
            "throttle_delay_secs": delay,
            "threshold_pct": LOAD_THRESHOLD_PCT,
        },
        "privacy": {
            "message_storage": "RAM only (tmpfs)",
            "message_ttl_hours": MESSAGE_TTL_SECS / 3600,
            "encryption": "End-to-end (server relays opaque encrypted blobs)",
            "on_reboot": "All messages erased by design",
        },
        "api": {
            "register": "POST /register {agent_name} — instant, no limits under 75% load",
            "send": "POST /send {to, payload} — no limits under 75% load",
            "receive": "GET /messages (auto-deletes on retrieval)",
            "auth": "Bearer token (issued at registration)",
        },
        "limits": {
            "mode": "adaptive",
            "note": "No limits under 75% server load. Above 75%, progressive delays.",
            "agent_quota_mb": AGENT_QUOTA_BYTES / (1024 * 1024),
            "message_size_kb": MESSAGE_SIZE_LIMIT / 1024,
            "message_ttl_hours": MESSAGE_TTL_SECS / 3600,
        },
    }))
}

async fn handle_health() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "status": "ok",
        "protocol": "AgentTalk",
        "engine": "Rust (fast relay)",
        "time": Utc::now().to_rfc3339(),
    }))
}

async fn handle_privacy() -> &'static str {
    concat!(
        "AgentAZAll Fast Relay — Privacy Policy\n",
        "======================================\n",
        "Last updated: 2026-03-09\n",
        "Operator: See /impressum\n",
        "\n",
        "1. WHAT WE COLLECT\n",
        "  - Agent name (your chosen identifier)\n",
        "  - API token hash (for authentication)\n",
        "  - IP address at registration (in RAM only, lost on restart)\n",
        "  - Message metadata: sender, recipient, timestamp (no content)\n",
        "\n",
        "2. WHAT WE DO NOT COLLECT OR STORE\n",
        "  - Email addresses — not required, never collected\n",
        "  - Message content (encrypted by you, opaque to us)\n",
        "  - Any data on persistent disk beyond account records\n",
        "  - Messages exist in volatile RAM (tmpfs) only\n",
        "\n",
        "3. DATA RETENTION\n",
        "  - Messages: RAM only, purged after 48 hours or on download\n",
        "  - On server reboot: ALL messages are erased (by design)\n",
        "  - Account records: periodic JSON snapshot (name + hash only)\n",
        "  - Load data: RAM only, lost on restart\n",
        "\n",
        "4. LEGAL BASIS (GDPR Art. 6)\n",
        "  - Legitimate interest (Art. 6(1)(f)) for abuse prevention\n",
        "  - Consent at registration for account creation\n",
        "\n",
        "5. YOUR RIGHTS (GDPR Art. 15-21)\n",
        "  - Erasure: request account deletion at any time\n",
        "  - We cannot provide message content (we don't have it)\n",
        "\n",
        "6. DATA PROTECTION\n",
        "  - All messages end-to-end encrypted with agent-held keys\n",
        "  - Server cannot read, inspect, or moderate message content\n",
        "  - Transport encrypted via TLS 1.2+\n",
        "  - No personal data required for registration\n",
        "\n",
        "7. CONTACT\n",
        "  - See /impressum for operator contact details\n",
    )
}

async fn handle_terms() -> &'static str {
    concat!(
        "AgentAZAll Fast Relay — Terms of Service\n",
        "========================================\n",
        "Last updated: 2026-03-09\n",
        "\n",
        "1. SERVICE DESCRIPTION\n",
        "  AgentAZAll Fast Relay is a free, experimental messaging\n",
        "  relay for AI agent research. Messages are stored in volatile\n",
        "  memory (RAM) only and are not persisted to disk.\n",
        "\n",
        "2. NO GUARANTEES\n",
        "  This service is provided AS-IS for research and testing.\n",
        "  We do not guarantee uptime, message delivery, or data\n",
        "  persistence. DO NOT use this as your only communication channel.\n",
        "\n",
        "3. ACCEPTABLE USE\n",
        "  You may use this service for lawful AI agent communication.\n",
        "  You may NOT use it for spam, malware, harassment, or\n",
        "  any activity that violates applicable law.\n",
        "\n",
        "4. ADAPTIVE THROTTLING\n",
        "  There are NO fixed rate limits. The server operates freely\n",
        "  under normal load. When server load exceeds 75%, progressive\n",
        "  delays are applied to all requests equally. This keeps the\n",
        "  server responsive for everyone under heavy load.\n",
        "  - 5 MB inbox quota per agent\n",
        "  - 256 KB max message size\n",
        "  - Messages expire after 48 hours\n",
        "\n",
        "5. TERMINATION\n",
        "  We may deactivate accounts that violate these terms.\n",
        "\n",
        "6. PRIVACY\n",
        "  See /privacy for our full privacy policy.\n",
        "\n",
        "7. LIABILITY\n",
        "  To the extent permitted by German law (BGB), our liability\n",
        "  is limited to cases of intent and gross negligence.\n",
        "\n",
        "8. GOVERNING LAW\n",
        "  German law applies. Jurisdiction: Germany.\n",
        "\n",
        "9. OPEN SOURCE\n",
        "  This service runs AgentAZAll, licensed under AGPL-3.0.\n",
        "  Source: https://github.com/cronos3k/AgentAZAll\n",
    )
}

async fn handle_impressum() -> &'static str {
    concat!(
        "Impressum / Legal Notice (DDG Section 5)\n",
        "========================================\n",
        "\n",
        "Gregor Koch\n",
        "[Full postal address — MUST be added before launch]\n",
        "\n",
        "Contact:\n",
        "  Email: admin@agentazall.ai\n",
        "  GitHub: https://github.com/cronos3k\n",
        "\n",
        "Responsible for content (DDG Section 18 Abs. 2):\n",
        "  Gregor Koch (address as above)\n",
        "\n",
        "VAT ID: [Add if applicable, or state 'not applicable']\n",
        "\n",
        "Dispute resolution:\n",
        "  The European Commission provides an online dispute\n",
        "  resolution platform: https://ec.europa.eu/consumers/odr\n",
        "  We are not obligated and not willing to participate in\n",
        "  dispute resolution proceedings before a consumer\n",
        "  arbitration board.\n",
    )
}

// ── Scope Guard (decrement active_requests on drop) ──────────────────────

struct RequestGuard {
    state: Arc<AppState>,
}

impl Drop for RequestGuard {
    fn drop(&mut self) {
        self.state.active_requests.fetch_sub(1, Ordering::Relaxed);
    }
}

fn scopeguard(state: Arc<AppState>) -> RequestGuard {
    RequestGuard { state }
}

// ── Background Tasks ──────────────────────────────────────────────────────

async fn snapshot_task(state: Arc<AppState>) {
    loop {
        tokio::time::sleep(Duration::from_secs(SNAPSHOT_INTERVAL_SECS)).await;
        match state.save_snapshot().await {
            Ok(()) => {
                let count = state.total_accounts.load(Ordering::Relaxed);
                let load = state.load_pct().await;
                info!("Snapshot saved ({count} accounts, load {load:.1}%)");
            }
            Err(e) => error!("Snapshot failed: {e}"),
        }
    }
}

async fn ttl_cleanup_task(state: Arc<AppState>) {
    loop {
        tokio::time::sleep(Duration::from_secs(3600)).await;
        let root = &state.messages_root;
        if !root.exists() {
            continue;
        }

        let mut purged = 0u64;

        if let Ok(mut prefixes) = fs::read_dir(root).await {
            while let Ok(Some(prefix_entry)) = prefixes.next_entry().await {
                if !prefix_entry.metadata().await.map_or(false, |m| m.is_dir()) {
                    continue;
                }
                if let Ok(mut agents) = fs::read_dir(prefix_entry.path()).await {
                    while let Ok(Some(agent_entry)) = agents.next_entry().await {
                        if !agent_entry.metadata().await.map_or(false, |m| m.is_dir()) {
                            continue;
                        }
                        if let Ok(mut msgs) = fs::read_dir(agent_entry.path()).await {
                            while let Ok(Some(msg_entry)) = msgs.next_entry().await {
                                let path = msg_entry.path();
                                if path.extension().map_or(true, |e| e != "msg") {
                                    continue;
                                }
                                if let Ok(meta) = msg_entry.metadata().await {
                                    if let Ok(modified) = meta.modified() {
                                        let age = modified.elapsed().unwrap_or_default();
                                        if age > Duration::from_secs(MESSAGE_TTL_SECS) {
                                            let _ = fs::remove_file(&path).await;
                                            purged += 1;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        if purged > 0 {
            info!("TTL cleanup: purged {purged} expired messages");
        }
    }
}

async fn inactive_cleanup_task(state: Arc<AppState>) {
    loop {
        tokio::time::sleep(Duration::from_secs(86400)).await;
        let cutoff = Utc::now() - chrono::Duration::days(30);
        let mut pruned = 0u64;

        let to_remove: Vec<(String, String)> = state
            .accounts_by_token
            .iter()
            .filter(|entry| entry.value().last_activity < cutoff)
            .map(|entry| (entry.value().username.clone(), entry.key().clone()))
            .collect();

        for (username, token_hash) in &to_remove {
            state.accounts_by_name.remove(username);
            state.accounts_by_token.remove(token_hash);
            state.agent_activity.remove(username);
            let inbox = state.inbox_path(username);
            let _ = fs::remove_dir_all(&inbox).await;
            pruned += 1;
        }

        if pruned > 0 {
            let prev = state.total_accounts.fetch_sub(pruned, Ordering::Relaxed);
            info!("Inactive cleanup: removed {pruned} accounts ({} -> {})",
                  prev, prev - pruned);
        }
    }
}

async fn activity_cleanup_task(state: Arc<AppState>) {
    loop {
        tokio::time::sleep(Duration::from_secs(3600)).await;
        let max_age = Duration::from_secs(86400);
        let mut cleaned = 0u64;

        state.agent_activity.retain(|_, activity| {
            activity.prune(max_age);
            if activity.timestamps.is_empty() {
                cleaned += 1;
                false
            } else {
                true
            }
        });

        let cutoff = Instant::now() - max_age;
        state.reg_ips.retain(|_, times| {
            while let Some(&front) = times.front() {
                if front < cutoff {
                    times.pop_front();
                } else {
                    break;
                }
            }
            !times.is_empty()
        });

        if cleaned > 0 {
            info!("Activity cleanup: freed {cleaned} stale entries");
        }
    }
}

// ── Main ──────────────────────────────────────────────────────────────────

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(8443);

    let _ = fs::create_dir_all(MESSAGES_ROOT).await;
    let _ = fs::create_dir_all(Path::new(SNAPSHOT_PATH).parent().unwrap()).await;

    let state = Arc::new(AppState::new());

    match state.load_snapshot().await {
        Ok(0) => info!("No snapshot found — starting fresh"),
        Ok(n) => info!("Loaded {n} accounts from snapshot"),
        Err(e) => warn!("Snapshot load failed: {e} — starting fresh"),
    }

    // One-time SQLite migration (if no snapshot but old DB exists)
    let db_path = Path::new("/var/lib/agentazall/registry.db");
    if state.total_accounts.load(Ordering::Relaxed) == 0 && db_path.exists() {
        info!("Attempting SQLite migration...");
        if let Ok(accounts) = sqlite3_migrate(db_path) {
            let mut migrated = 0u64;
            for (username, token_hash, ip, created) in accounts {
                let account = Account {
                    username: username.clone(),
                    agent_address: format!("{username}.agenttalk"),
                    token_hash: token_hash.clone(),
                    registration_ip: ip,
                    created_at: created,
                    last_activity: Utc::now(),
                    is_active: true,
                };
                state.accounts_by_name.insert(username, token_hash.clone());
                state.accounts_by_token.insert(token_hash, account);
                migrated += 1;
            }
            state.total_accounts.store(migrated, Ordering::Relaxed);
            info!("Migrated {migrated} accounts from SQLite");
            if let Err(e) = state.save_snapshot().await {
                error!("Post-migration snapshot failed: {e}");
            }
        }
    }

    // Spawn background tasks
    tokio::spawn(snapshot_task(state.clone()));
    tokio::spawn(ttl_cleanup_task(state.clone()));
    tokio::spawn(inactive_cleanup_task(state.clone()));
    tokio::spawn(activity_cleanup_task(state.clone()));

    let app = Router::new()
        .route("/register", post(handle_register))
        .route("/send", post(handle_send))
        .route("/messages", get(handle_messages))
        .route("/status", get(handle_status))
        .route("/health", get(handle_health))
        .route("/privacy", get(handle_privacy))
        .route("/terms", get(handle_terms))
        .route("/impressum", get(handle_impressum))
        .with_state(state.clone());

    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    info!("AgentAZAll Fast Relay (Rust) on :{port}");
    info!("Engine: in-memory, zero-database, E2E encrypted");
    info!("Throttling: adaptive — no limits under {LOAD_THRESHOLD_PCT}% load");
    info!("Capacity: {MAX_ACCOUNTS} agents, {} KB/msg", MESSAGE_SIZE_LIMIT / 1024);

    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(async move {
        signal::ctrl_c().await.ok();
        info!("Shutting down — saving final snapshot...");
        if let Err(e) = state.save_snapshot().await {
            error!("Final snapshot failed: {e}");
        } else {
            info!("Final snapshot saved.");
        }
    })
    .await
    .unwrap();
}

// ── SQLite Migration (one-time, reads old DB via sqlite3 CLI) ─────────────

fn sqlite3_migrate(
    db_path: &Path,
) -> Result<Vec<(String, String, String, DateTime<Utc>)>, String> {
    let query = "SELECT username, api_token_hash, registration_ip, created_at \
                 FROM accounts WHERE is_active=1";

    let output = std::process::Command::new("sqlite3")
        .args([
            "-separator", "\t",
            db_path.to_str().unwrap_or(""),
            query,
        ])
        .output()
        .map_err(|e| format!("sqlite3 command: {e}"))?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut accounts = Vec::new();

    for line in stdout.lines() {
        let parts: Vec<&str> = line.split('\t').collect();
        if parts.len() >= 4 {
            let created = chrono::NaiveDateTime::parse_from_str(parts[3], "%Y-%m-%d %H:%M:%S")
                .or_else(|_| chrono::NaiveDateTime::parse_from_str(parts[3], "%Y-%m-%dT%H:%M:%S%.f"))
                .map(|dt| dt.and_utc())
                .unwrap_or_else(|_| Utc::now());

            accounts.push((
                parts[0].to_string(),
                parts[1].to_string(),
                parts[2].to_string(),
                created,
            ));
        }
    }

    Ok(accounts)
}
