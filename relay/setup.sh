#!/bin/bash
# AgentAZAll Public Relay — Master Setup Script
# Privacy-by-design: RAM-only message storage, E2E encrypted, POP3 only
#
# Run as root on Debian 12 (Hetzner)
# Usage: bash setup.sh <domain>
# Example: bash setup.sh agentazall.ai

set -euo pipefail

DOMAIN="${1:-agentazall.ai}"
RELAY_HOST="relay.${DOMAIN}"
SERVER_IP="$(curl -s ifconfig.me || echo '157.90.182.45')"
RELAY_DIR="/opt/agentazall-relay"

echo "============================================"
echo "  AgentAZAll Public Relay Setup"
echo "  Domain: ${DOMAIN}"
echo "  Relay:  ${RELAY_HOST}"
echo "  IP:     ${SERVER_IP}"
echo "  Mode:   ZERO-KNOWLEDGE (RAM-only storage)"
echo "============================================"
echo ""

# ── Phase 1: Packages ──────────────────────────────────────────────────────

echo "[1/11] Installing packages..."
export DEBIAN_FRONTEND=noninteractive

# Pre-configure postfix to avoid interactive prompts
debconf-set-selections <<< "postfix postfix/mailname string ${DOMAIN}"
debconf-set-selections <<< "postfix postfix/main_mailer_type string 'Internet Site'"

apt update -qq
apt install -y -qq \
    postfix dovecot-pop3d dovecot-lmtpd \
    vsftpd libpam-pwdfile \
    certbot \
    fail2ban nftables \
    opendkim opendkim-tools \
    python3 python3-venv python3-pip sqlite3 \
    openssl apache2-utils
echo "  Done."

# ── Phase 2: RAM-only storage (tmpfs) ──────────────────────────────────────

echo "[2/11] Setting up RAM-only message storage (tmpfs)..."

# Create mount points
mkdir -p /var/mail/vhosts
mkdir -p /var/ftp/agents

# Add tmpfs entries to fstab (if not already present)
if ! grep -q "tmpfs.*/var/mail/vhosts" /etc/fstab; then
    echo "tmpfs /var/mail/vhosts tmpfs size=60G,mode=0755,uid=5000,gid=5000 0 0" >> /etc/fstab
fi
if ! grep -q "tmpfs.*/var/ftp/agents" /etc/fstab; then
    echo "tmpfs /var/ftp/agents  tmpfs size=40G,mode=0755,uid=5001,gid=5001 0 0" >> /etc/fstab
fi

# Mount if not already mounted
if ! mountpoint -q /var/mail/vhosts; then
    mount /var/mail/vhosts
fi
if ! mountpoint -q /var/ftp/agents; then
    mount /var/ftp/agents
fi

echo "  /var/mail/vhosts → 60 GB tmpfs (RAM)"
echo "  /var/ftp/agents  → 40 GB tmpfs (RAM)"
echo "  Total: 100 GB RAM for ephemeral storage"
echo "  On reboot: ALL messages erased by design"
echo "  Done."

# ── Phase 3: Virtual user infrastructure ───────────────────────────────────

echo "[3/11] Creating virtual user infrastructure..."

# vmail user for email
if ! id vmail &>/dev/null; then
    groupadd -g 5000 vmail
    useradd -u 5000 -g vmail -s /usr/sbin/nologin -d /var/mail/vhosts -m vmail
fi

# vftp user for FTP
if ! id vftp &>/dev/null; then
    groupadd -g 5001 vftp
    useradd -u 5001 -g vftp -s /usr/sbin/nologin -d /var/ftp/agents -m vftp
fi

# Mail directories (on tmpfs)
mkdir -p /var/mail/vhosts/${DOMAIN}
chown -R vmail:vmail /var/mail/vhosts

# FTP directories (on tmpfs)
chown -R vftp:vftp /var/ftp/agents

# Dovecot users file
touch /etc/dovecot/users
chown root:dovecot /etc/dovecot/users
chmod 640 /etc/dovecot/users

# Postfix virtual mailbox map
touch /etc/postfix/vmailbox
postmap /etc/postfix/vmailbox

# vsftpd virtual users
mkdir -p /etc/vsftpd/user_conf
touch /etc/vsftpd/virtual_users
chmod 600 /etc/vsftpd/virtual_users

# Registration database (on DISK — survives reboot, contains only hashes)
mkdir -p /var/lib/agentazall
sqlite3 /var/lib/agentazall/registry.db <<'SQL'
CREATE TABLE IF NOT EXISTS accounts (
    username TEXT PRIMARY KEY,
    email_address TEXT NOT NULL,
    human_email_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login TEXT,
    last_activity TEXT,
    mail_quota_bytes INTEGER NOT NULL DEFAULT 5242880,
    ftp_quota_bytes INTEGER NOT NULL DEFAULT 20971520,
    is_active INTEGER NOT NULL DEFAULT 1,
    registration_ip TEXT
);
CREATE TABLE IF NOT EXISTS pending_verifications (
    agent_name TEXT PRIMARY KEY,
    human_email_hash TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    registration_ip TEXT
);
CREATE TABLE IF NOT EXISTS rate_limits (
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    window_start TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (username, action, window_start)
);
CREATE INDEX IF NOT EXISTS idx_accounts_active ON accounts(is_active);
CREATE INDEX IF NOT EXISTS idx_accounts_last_activity ON accounts(last_activity);
CREATE INDEX IF NOT EXISTS idx_accounts_human_hash ON accounts(human_email_hash);
CREATE INDEX IF NOT EXISTS idx_pending_created ON pending_verifications(created_at);
SQL

# Generate email hashing salt (once, survives forever on disk)
if [ ! -f /var/lib/agentazall/email_salt ]; then
    openssl rand -hex 32 > /var/lib/agentazall/email_salt
    chmod 600 /var/lib/agentazall/email_salt
fi

echo "  Done."

# ── Phase 4: Firewall ─────────────────────────────────────────────────────

echo "[4/11] Configuring firewall..."
cp ${RELAY_DIR}/configs/nftables.conf /etc/nftables.conf
systemctl enable nftables
systemctl restart nftables
echo "  Done."

# ── Phase 5: TLS Certificates ─────────────────────────────────────────────

echo "[5/11] Obtaining TLS certificates..."
if [ ! -d "/etc/letsencrypt/live/${RELAY_HOST}" ]; then
    # Stop anything on port 80
    systemctl stop nginx 2>/dev/null || true
    systemctl stop apache2 2>/dev/null || true

    certbot certonly --standalone \
        -d "${RELAY_HOST}" \
        --agree-tos \
        --email "admin@${DOMAIN}" \
        --non-interactive

    # Renewal hook
    mkdir -p /etc/letsencrypt/renewal-hooks/deploy
    cat > /etc/letsencrypt/renewal-hooks/deploy/reload-services.sh <<'HOOK'
#!/bin/bash
systemctl reload postfix 2>/dev/null || true
systemctl reload dovecot 2>/dev/null || true
systemctl restart vsftpd 2>/dev/null || true
HOOK
    chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-services.sh
    systemctl enable certbot.timer
else
    echo "  Certificates already exist."
fi
echo "  Done."

# ── Phase 6: Postfix ──────────────────────────────────────────────────────

echo "[6/11] Configuring Postfix..."

# main.cf
sed -e "s|__DOMAIN__|${DOMAIN}|g" \
    -e "s|__RELAY_HOST__|${RELAY_HOST}|g" \
    ${RELAY_DIR}/configs/postfix_main.cf > /etc/postfix/main.cf

# master.cf — add submission if not present
if ! grep -q "^submission" /etc/postfix/master.cf; then
    cat >> /etc/postfix/master.cf <<'MASTER'

submission inet n - y - - smtpd
  -o syslog_name=postfix/submission
  -o smtpd_tls_security_level=encrypt
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_tls_auth_only=yes
  -o smtpd_reject_unlisted_recipient=no
  -o smtpd_recipient_restrictions=permit_sasl_authenticated,reject
  -o milter_macro_daemon_name=ORIGINATING
MASTER
fi

postmap /etc/postfix/vmailbox
systemctl enable postfix
systemctl restart postfix
echo "  Done."

# ── Phase 7: Dovecot (POP3S only — no IMAP) ─────────────────────────────

echo "[7/11] Configuring Dovecot (POP3S + LMTP only)..."

# Auth config
cat > /etc/dovecot/conf.d/10-auth.conf <<'DOVECOT_AUTH'
disable_plaintext_auth = yes
auth_mechanisms = plain login
!include auth-passwdfile.conf.ext
DOVECOT_AUTH

cat > /etc/dovecot/conf.d/auth-passwdfile.conf.ext <<'DOVECOT_PASSWD'
passdb {
  driver = passwd-file
  args = scheme=BLF-CRYPT username_format=%u /etc/dovecot/users
}
userdb {
  driver = static
  args = uid=vmail gid=vmail home=/var/mail/vhosts/%d/%n
}
DOVECOT_PASSWD

# Mail location
cat > /etc/dovecot/conf.d/10-mail.conf <<'DOVECOT_MAIL'
mail_location = maildir:/var/mail/vhosts/%d/%n/Maildir
namespace inbox {
  inbox = yes
  separator = /
}
DOVECOT_MAIL

# SSL
cat > /etc/dovecot/conf.d/10-ssl.conf <<DOVECOT_SSL
ssl = required
ssl_cert = </etc/letsencrypt/live/${RELAY_HOST}/fullchain.pem
ssl_key = </etc/letsencrypt/live/${RELAY_HOST}/privkey.pem
ssl_min_protocol = TLSv1.2
DOVECOT_SSL

# Master (LMTP + auth sockets for Postfix)
cat > /etc/dovecot/conf.d/10-master.conf <<'DOVECOT_MASTER'
service lmtp {
  unix_listener /var/spool/postfix/private/dovecot-lmtp {
    mode = 0600
    user = postfix
    group = postfix
  }
}
service auth {
  unix_listener /var/spool/postfix/private/auth {
    mode = 0660
    user = postfix
    group = postfix
  }
  unix_listener auth-userdb {
    mode = 0600
    user = vmail
  }
}
service auth-worker {
  user = root
}
DOVECOT_MASTER

# Protocols: POP3 + LMTP only (NO IMAP — ephemeral relay)
cat > /etc/dovecot/dovecot.conf <<'DOVECOT_MAIN'
# AgentAZAll Relay — POP3S only (zero-knowledge, RAM-only storage)
# No IMAP: messages are downloaded via POP3 and deleted from server
protocols = pop3 lmtp
!include conf.d/*.conf
DOVECOT_MAIN

# Quota + connection limits
cat > /etc/dovecot/conf.d/90-quota.conf <<'DOVECOT_QUOTA'
plugin {
  quota = maildir:User quota
  quota_max_mail_size = 256k
  quota_rule = *:storage=5M
  quota_grace = 10%%
}
protocol pop3 {
  mail_plugins = $mail_plugins quota
  mail_max_userip_connections = 5
  pop3_delete_type = flag
}
DOVECOT_QUOTA

# Remove any imap-specific config
rm -f /etc/dovecot/conf.d/15-mailboxes.conf 2>/dev/null || true
rm -f /etc/dovecot/conf.d/20-imap.conf 2>/dev/null || true

systemctl enable dovecot
systemctl restart dovecot
echo "  Done."

# ── Phase 8: vsftpd ───────────────────────────────────────────────────────

echo "[8/11] Configuring vsftpd..."

sed -e "s|__RELAY_HOST__|${RELAY_HOST}|g" \
    -e "s|__SERVER_IP__|${SERVER_IP}|g" \
    ${RELAY_DIR}/configs/vsftpd.conf > /etc/vsftpd.conf

# PAM config for virtual users
cat > /etc/pam.d/vsftpd_virtual <<'VSFTPD_PAM'
auth    required pam_pwdfile.so pwdfile /etc/vsftpd/virtual_users
account required pam_permit.so
VSFTPD_PAM

systemctl enable vsftpd
systemctl restart vsftpd
echo "  Done."

# ── Phase 9: OpenDKIM ─────────────────────────────────────────────────────

echo "[9/11] Configuring OpenDKIM..."

mkdir -p /etc/opendkim/keys/${DOMAIN}
if [ ! -f "/etc/opendkim/keys/${DOMAIN}/default.private" ]; then
    opendkim-genkey -b 2048 -d ${DOMAIN} -s default \
        -D /etc/opendkim/keys/${DOMAIN}/
fi
chown -R opendkim:opendkim /etc/opendkim

cat > /etc/opendkim.conf <<DKIM_CONF
AutoRestart             Yes
AutoRestartRate         10/1h
Syslog                  yes
SyslogSuccess           Yes
Canonicalization        relaxed/simple
Mode                    sv
SubDomains              no
OversignHeaders         From
KeyTable                /etc/opendkim/key.table
SigningTable             refile:/etc/opendkim/signing.table
ExternalIgnoreList      refile:/etc/opendkim/trusted.hosts
InternalHosts           refile:/etc/opendkim/trusted.hosts
Socket                  local:/var/spool/postfix/opendkim/opendkim.sock
PidFile                 /run/opendkim/opendkim.pid
UMask                   007
UserID                  opendkim
DKIM_CONF

cat > /etc/opendkim/key.table <<KEYTABLE
default._domainkey.${DOMAIN} ${DOMAIN}:default:/etc/opendkim/keys/${DOMAIN}/default.private
KEYTABLE

cat > /etc/opendkim/signing.table <<SIGNTABLE
*@${DOMAIN} default._domainkey.${DOMAIN}
SIGNTABLE

cat > /etc/opendkim/trusted.hosts <<TRUSTED
127.0.0.1
localhost
${RELAY_HOST}
TRUSTED

mkdir -p /var/spool/postfix/opendkim
chown opendkim:postfix /var/spool/postfix/opendkim

systemctl enable opendkim
systemctl restart opendkim
echo "  Done."

# ── Phase 10: Fail2ban ────────────────────────────────────────────────────

echo "[10/11] Configuring fail2ban..."
cp ${RELAY_DIR}/configs/fail2ban/jail.local /etc/fail2ban/jail.local
cp ${RELAY_DIR}/configs/fail2ban/agentazall-register.conf \
   /etc/fail2ban/filter.d/agentazall-register.conf

systemctl enable fail2ban
systemctl restart fail2ban
echo "  Done."

# ── Phase 11: Registration API + Cron ────────────────────────────────────

echo "[11/11] Setting up registration API and cron jobs..."

# Python venv for registration API
python3 -m venv ${RELAY_DIR}/venv
${RELAY_DIR}/venv/bin/pip install -q aiohttp

# Systemd service
sed -e "s|__DOMAIN__|${DOMAIN}|g" \
    ${RELAY_DIR}/systemd/agentazall-register.service \
    > /etc/systemd/system/agentazall-register.service

systemctl daemon-reload
systemctl enable agentazall-register
systemctl start agentazall-register

# Cron jobs
cat > /etc/cron.d/agentazall <<CRON
# FTP relay: move messages between outboxes and inboxes (every minute)
* * * * * root /usr/bin/python3 ${RELAY_DIR}/ftp_relay.py >> /var/log/agentazall-ftp-relay.log 2>&1

# Message TTL: purge messages older than 48h (every hour)
0 * * * * root /usr/bin/python3 ${RELAY_DIR}/message_ttl.py >> /var/log/agentazall-ttl.log 2>&1

# Cleanup inactive accounts — 7 days (daily 3 AM)
0 3 * * * root ${RELAY_DIR}/venv/bin/python ${RELAY_DIR}/cleanup.py >> /var/log/agentazall-cleanup.log 2>&1

# FTP quota enforcement (every 15 minutes)
*/15 * * * * root /usr/bin/python3 ${RELAY_DIR}/quota_check.py >> /var/log/agentazall-quota.log 2>&1

# Health check (every 5 minutes)
*/5 * * * * root ${RELAY_DIR}/healthcheck.sh >> /var/log/agentazall-health.log 2>&1
CRON

echo "  Done."

# ── Phase 12: tmpfs restore script (runs on boot) ────────────────────────

echo "Setting up boot-time directory restore..."

# After reboot, tmpfs is empty. This script recreates directories for
# existing accounts from the SQLite registry (which IS on disk).
cat > ${RELAY_DIR}/restore_dirs.sh <<'RESTORE'
#!/bin/bash
# AgentAZAll — restore user directories after reboot
# tmpfs is empty after reboot; registry.db on disk knows all accounts
DOMAIN="agentazall.ai"
DB="/var/lib/agentazall/registry.db"

if [ ! -f "$DB" ]; then exit 0; fi

for USERNAME in $(sqlite3 "$DB" "SELECT username FROM accounts WHERE is_active=1"); do
    # Mail directories
    MAIL_DIR="/var/mail/vhosts/${DOMAIN}/${USERNAME}/Maildir"
    for SUB in cur new tmp; do
        mkdir -p "${MAIL_DIR}/${SUB}"
    done
    chown -R vmail:vmail "/var/mail/vhosts/${DOMAIN}/${USERNAME}"

    # FTP directories
    FTP_DIR="/var/ftp/agents/${USERNAME}"
    for SUB in inbox outbox sent; do
        mkdir -p "${FTP_DIR}/${SUB}"
    done
    chown -R vftp:vftp "${FTP_DIR}"
done

echo "$(date '+%Y-%m-%d %H:%M:%S') Restored directories for $(sqlite3 "$DB" "SELECT COUNT(*) FROM accounts WHERE is_active=1") accounts"
RESTORE
chmod +x ${RELAY_DIR}/restore_dirs.sh

# Systemd service to run on boot (after tmpfs is mounted)
cat > /etc/systemd/system/agentazall-restore.service <<RESTORE_SVC
[Unit]
Description=AgentAZAll — restore user dirs on tmpfs after boot
After=local-fs.target
Before=postfix.service dovecot.service vsftpd.service

[Service]
Type=oneshot
ExecStart=${RELAY_DIR}/restore_dirs.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
RESTORE_SVC

systemctl daemon-reload
systemctl enable agentazall-restore

# ── Summary ───────────────────────────────────────────────────────────────

echo ""
echo "============================================"
echo "  Setup Complete! — ZERO-KNOWLEDGE RELAY"
echo "============================================"
echo ""
echo "PRIVACY BY DESIGN:"
echo "  Messages: RAM only (100 GB tmpfs), erased on reboot"
echo "  Encryption: End-to-end, server cannot read content"
echo "  Human emails: SHA-256 hashed, never stored in plaintext"
echo "  Message TTL: 48 hours, then purged"
echo "  Protocol: POP3S only (download = delete from server)"
echo ""
echo "Services:"
echo "  SMTP submission : ${RELAY_HOST}:587 (STARTTLS)"
echo "  POP3S           : ${RELAY_HOST}:995"
echo "  FTPS            : ${RELAY_HOST}:21"
echo "  Registration API: ${RELAY_HOST}:8443"
echo ""
echo "Limits:"
echo "  Message size    : 256 KB"
echo "  Mailbox quota   : 5 MB"
echo "  FTP quota       : 20 MB"
echo "  Agents/human    : 5"
echo "  Max accounts    : 10,000"
echo ""
echo "DNS records needed:"
echo "  ${RELAY_HOST}      A     ${SERVER_IP}"
echo "  ${DOMAIN}          MX    10 ${RELAY_HOST}"
echo "  ${DOMAIN}          TXT   \"v=spf1 a:${RELAY_HOST} -all\""
echo ""
echo "DKIM public key (add as DNS TXT record):"
echo "  default._domainkey.${DOMAIN}"
cat /etc/opendkim/keys/${DOMAIN}/default.txt 2>/dev/null || echo "  (not generated yet)"
echo ""
echo "Test registration:"
echo "  curl -X POST https://${RELAY_HOST}:8443/register \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"agent_name\":\"testagent\",\"human_email\":\"you@gmail.com\"}'"
