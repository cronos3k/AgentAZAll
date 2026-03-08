#!/bin/bash
# AgentAZAll Relay — health check (zero-knowledge relay)
FAIL=0
DATE=$(date '+%Y-%m-%d %H:%M:%S')

# Check Postfix
if ! systemctl is-active --quiet postfix; then
    echo "$DATE FAIL: postfix down"
    FAIL=1
fi

# Check Dovecot
if ! systemctl is-active --quiet dovecot; then
    echo "$DATE FAIL: dovecot down"
    FAIL=1
fi

# Check vsftpd
if ! systemctl is-active --quiet vsftpd; then
    echo "$DATE FAIL: vsftpd down"
    FAIL=1
fi

# Check registration API
if ! systemctl is-active --quiet agentazall-register; then
    echo "$DATE FAIL: registration API down"
    FAIL=1
fi

# Check TLS cert expiry (warn at 14 days)
CERT="/etc/letsencrypt/live/relay.agentazall.ai/fullchain.pem"
if [ -f "$CERT" ]; then
    EXPIRY=$(openssl x509 -enddate -noout -in "$CERT" 2>/dev/null | cut -d= -f2)
    if [ -n "$EXPIRY" ]; then
        EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s 2>/dev/null)
        NOW_EPOCH=$(date +%s)
        DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
        if [ "$DAYS_LEFT" -lt 14 ]; then
            echo "$DATE WARN: TLS cert expires in $DAYS_LEFT days"
        fi
    fi
fi

# Check tmpfs RAM usage (mail)
MAIL_USED=$(df /var/mail/vhosts --output=pcent 2>/dev/null | tail -1 | tr -d ' %')
if [ -n "$MAIL_USED" ] && [ "$MAIL_USED" -gt 80 ]; then
    echo "$DATE WARN: mail tmpfs usage ${MAIL_USED}%"
fi

# Check tmpfs RAM usage (ftp)
FTP_USED=$(df /var/ftp/agents --output=pcent 2>/dev/null | tail -1 | tr -d ' %')
if [ -n "$FTP_USED" ] && [ "$FTP_USED" -gt 80 ]; then
    echo "$DATE WARN: ftp tmpfs usage ${FTP_USED}%"
fi

# Check overall RAM
RAM_PCT=$(free | awk '/Mem:/{printf "%.0f", $3/$2*100}')
if [ -n "$RAM_PCT" ] && [ "$RAM_PCT" -gt 90 ]; then
    echo "$DATE WARN: RAM usage ${RAM_PCT}%"
fi

# Check tmpfs mounts are present
if ! mountpoint -q /var/mail/vhosts 2>/dev/null; then
    echo "$DATE FAIL: /var/mail/vhosts not mounted as tmpfs!"
    FAIL=1
fi
if ! mountpoint -q /var/ftp/agents 2>/dev/null; then
    echo "$DATE FAIL: /var/ftp/agents not mounted as tmpfs!"
    FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
    echo "$DATE OK: all services healthy (RAM-only relay)"
fi
