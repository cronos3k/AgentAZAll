#!/bin/bash
# AgentAZAll Relay — TLS deployment script
# Run on Hetzner server (157.90.182.45) once DNS resolves globally.
#
# Prerequisites:
#   - DNS for relay.agentazall.ai and agentazall.ai resolving to this server
#   - nginx installed (apt install nginx)
#   - certbot installed (apt install certbot)
#   - Rust relay running on localhost:3777
#
# Usage: sudo bash deploy-tls.sh

set -euo pipefail

RELAY_DOMAIN="relay.agentazall.ai"
ROOT_DOMAIN="agentazall.ai"
RELAY_PORT=3777
NGINX_CONF="/etc/nginx/sites-available/agentazall-relay"
CERTBOT_WEBROOT="/var/www/certbot"

echo "=== AgentAZAll TLS Deployment ==="
echo ""

# 1. Check DNS
echo "[1/7] Checking DNS resolution..."
RELAY_IP=$(dig +short "$RELAY_DOMAIN" @8.8.8.8 2>/dev/null || true)
ROOT_IP=$(dig +short "$ROOT_DOMAIN" @8.8.8.8 2>/dev/null || true)

if [ -z "$RELAY_IP" ]; then
    echo "ERROR: $RELAY_DOMAIN does not resolve on Google DNS yet."
    echo "Try: dig $RELAY_DOMAIN @8.8.8.8"
    exit 1
fi
echo "  $RELAY_DOMAIN → $RELAY_IP"
echo "  $ROOT_DOMAIN → ${ROOT_IP:-'(not set)'}"

# 2. Check relay is running
echo "[2/7] Checking relay on localhost:$RELAY_PORT..."
if ! curl -sf "http://127.0.0.1:$RELAY_PORT/health" > /dev/null 2>&1; then
    echo "ERROR: Relay not responding on localhost:$RELAY_PORT"
    echo "Start it first: systemctl start agentazall-relay"
    exit 1
fi
echo "  Relay is healthy."

# 3. Install nginx if needed
echo "[3/7] Ensuring nginx is installed..."
if ! command -v nginx &> /dev/null; then
    apt-get update -qq && apt-get install -y -qq nginx
fi
echo "  nginx: $(nginx -v 2>&1)"

# 4. Stop nginx temporarily for standalone certbot
echo "[4/7] Obtaining TLS certificate..."
mkdir -p "$CERTBOT_WEBROOT"
systemctl stop nginx 2>/dev/null || true

certbot certonly --standalone \
    -d "$RELAY_DOMAIN" \
    -d "$ROOT_DOMAIN" \
    --non-interactive \
    --agree-tos \
    --email contact@agentazall.ai \
    --cert-name "$RELAY_DOMAIN"

echo "  Certificate obtained."

# 5. Deploy nginx config
echo "[5/7] Deploying nginx config..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/configs/nginx-relay.conf" "$NGINX_CONF"
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/agentazall-relay

# Remove default site if it exists
rm -f /etc/nginx/sites-enabled/default

# Test config
nginx -t
echo "  nginx config OK."

# 6. Start nginx
echo "[6/7] Starting nginx..."
systemctl start nginx
systemctl enable nginx
echo "  nginx started and enabled."

# 7. Verify
echo "[7/7] Verifying HTTPS..."
sleep 2
HTTP_CODE=$(curl -so /dev/null -w "%{http_code}" "https://$RELAY_DOMAIN/health" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo "  ✓ https://$RELAY_DOMAIN/health → 200 OK"
else
    echo "  ✗ HTTPS check returned $HTTP_CODE — check nginx logs"
    echo "  Try: journalctl -u nginx --no-pager -n 20"
fi

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Endpoints:"
echo "  https://$RELAY_DOMAIN/health"
echo "  https://$RELAY_DOMAIN/status"
echo "  https://$RELAY_DOMAIN/impressum"
echo "  https://$RELAY_DOMAIN/privacy"
echo "  https://$RELAY_DOMAIN/terms"
echo ""
echo "Certbot auto-renewal: systemctl status certbot.timer"
echo "Manual renewal: certbot renew --post-hook 'systemctl reload nginx'"
