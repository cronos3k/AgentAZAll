#!/bin/bash
# Deploy Dovecot, Postfix, vsftpd configs + boot restore + cron
# Run on server: bash /opt/agentazall-relay/deploy_configs.sh
set -euo pipefail

DOMAIN="agentazall.ai"
RELAY_HOST="relay.agentazall.ai"
RELAY_DIR="/opt/agentazall-relay"
SERVER_IP="$(curl -s ifconfig.me || echo '157.90.182.45')"

echo "=== Configuring Dovecot (POP3S + LMTP only) ==="

cat > /etc/dovecot/conf.d/10-auth.conf << 'EOF'
disable_plaintext_auth = yes
auth_mechanisms = plain login
!include auth-passwdfile.conf.ext
EOF

cat > /etc/dovecot/conf.d/auth-passwdfile.conf.ext << 'EOF'
passdb {
  driver = passwd-file
  args = scheme=BLF-CRYPT username_format=%u /etc/dovecot/users
}
userdb {
  driver = static
  args = uid=vmail gid=vmail home=/var/mail/vhosts/%d/%n
}
EOF

cat > /etc/dovecot/conf.d/10-mail.conf << 'EOF'
mail_location = maildir:/var/mail/vhosts/%d/%n/Maildir
namespace inbox {
  inbox = yes
  separator = /
}
EOF

cat > /etc/dovecot/conf.d/10-master.conf << 'EOF'
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
EOF

cat > /etc/dovecot/dovecot.conf << 'EOF'
protocols = pop3 lmtp
!include conf.d/*.conf
EOF

cat > /etc/dovecot/conf.d/90-quota.conf << 'QUOTAEOF'
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
QUOTAEOF

# No SSL config yet (waiting for certbot)
# Remove IMAP configs
rm -f /etc/dovecot/conf.d/15-mailboxes.conf 2>/dev/null || true
rm -f /etc/dovecot/conf.d/20-imap.conf 2>/dev/null || true
rm -f /etc/dovecot/conf.d/10-ssl.conf 2>/dev/null || true

echo "  Dovecot: POP3S + LMTP, no IMAP"

echo "=== Configuring Postfix ==="
sed -e "s|__DOMAIN__|${DOMAIN}|g" \
    -e "s|__RELAY_HOST__|${RELAY_HOST}|g" \
    ${RELAY_DIR}/configs/postfix_main.cf > /etc/postfix/main.cf

if ! grep -q "^submission" /etc/postfix/master.cf; then
    cat >> /etc/postfix/master.cf << 'EOF'

submission inet n - y - - smtpd
  -o syslog_name=postfix/submission
  -o smtpd_tls_security_level=encrypt
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_tls_auth_only=yes
  -o smtpd_reject_unlisted_recipient=no
  -o smtpd_recipient_restrictions=permit_sasl_authenticated,reject
  -o milter_macro_daemon_name=ORIGINATING
EOF
    echo "  Added submission to master.cf"
fi
postmap /etc/postfix/vmailbox
echo "  Postfix: 256 KB limit, SASL via Dovecot"

echo "=== Configuring vsftpd ==="
sed -e "s|__RELAY_HOST__|${RELAY_HOST}|g" \
    -e "s|__SERVER_IP__|${SERVER_IP}|g" \
    ${RELAY_DIR}/configs/vsftpd.conf > /etc/vsftpd.conf

cat > /etc/pam.d/vsftpd_virtual << 'EOF'
auth    required pam_pwdfile.so pwdfile /etc/vsftpd/virtual_users
account required pam_permit.so
EOF
echo "  vsftpd: virtual users, TLS, chroot"

echo "=== Boot restore service ==="
cat > ${RELAY_DIR}/restore_dirs.sh << 'EOF'
#!/bin/bash
DOMAIN="agentazall.ai"
DB="/var/lib/agentazall/registry.db"
if [ ! -f "$DB" ]; then exit 0; fi
for USERNAME in $(sqlite3 "$DB" "SELECT username FROM accounts WHERE is_active=1"); do
    MAIL_DIR="/var/mail/vhosts/${DOMAIN}/${USERNAME}/Maildir"
    for SUB in cur new tmp; do mkdir -p "${MAIL_DIR}/${SUB}"; done
    chown -R vmail:vmail "/var/mail/vhosts/${DOMAIN}/${USERNAME}"
    FTP_DIR="/var/ftp/agents/${USERNAME}"
    for SUB in inbox outbox sent; do mkdir -p "${FTP_DIR}/${SUB}"; done
    chown -R vftp:vftp "${FTP_DIR}"
done
echo "$(date '+%Y-%m-%d %H:%M:%S') Restored dirs for $(sqlite3 "$DB" "SELECT COUNT(*) FROM accounts WHERE is_active=1") accounts"
EOF
chmod +x ${RELAY_DIR}/restore_dirs.sh

cat > /etc/systemd/system/agentazall-restore.service << 'EOF'
[Unit]
Description=AgentAZAll restore user dirs on tmpfs after boot
After=local-fs.target
Before=postfix.service dovecot.service vsftpd.service

[Service]
Type=oneshot
ExecStart=/opt/agentazall-relay/restore_dirs.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable agentazall-restore
echo "  Boot restore: enabled"

echo "=== Cron jobs ==="
cat > /etc/cron.d/agentazall << 'EOF'
* * * * * root /usr/bin/python3 /opt/agentazall-relay/ftp_relay.py >> /var/log/agentazall-ftp-relay.log 2>&1
0 * * * * root /usr/bin/python3 /opt/agentazall-relay/message_ttl.py >> /var/log/agentazall-ttl.log 2>&1
0 3 * * * root /opt/agentazall-relay/venv/bin/python /opt/agentazall-relay/cleanup.py >> /var/log/agentazall-cleanup.log 2>&1
*/15 * * * * root /usr/bin/python3 /opt/agentazall-relay/quota_check.py >> /var/log/agentazall-quota.log 2>&1
*/5 * * * * root /opt/agentazall-relay/healthcheck.sh >> /var/log/agentazall-health.log 2>&1
EOF
echo "  Cron: FTP relay, TTL purge, cleanup, quota, health"

echo "=== Registration API ==="
sed -e "s|__DOMAIN__|${DOMAIN}|g" \
    ${RELAY_DIR}/systemd/agentazall-register.service \
    > /etc/systemd/system/agentazall-register.service
systemctl daemon-reload
systemctl enable agentazall-register
systemctl restart agentazall-register
sleep 2
if systemctl is-active --quiet agentazall-register; then
    echo "  Registration API: RUNNING"
else
    echo "  Registration API: FAILED"
    journalctl -u agentazall-register --no-pager -n 10
fi

echo ""
echo "============================================"
echo "  ALL CONFIGS DEPLOYED"
echo "============================================"
echo "Waiting for: DNS + certbot for TLS certs"
echo "Then restart: postfix dovecot vsftpd"
