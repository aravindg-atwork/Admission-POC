#!/bin/bash
# Turn on HTTPS for MITRA.
#
#   mitra-enable-tls.sh mitra.example.org you@example.org [--staging]
#
# --staging issues from Let's Encrypt's test service: it proves the whole path
# works without spending one of the five-per-week real certificate attempts.
# Rehearse with it once, then run for real.
#
# Everything this needs is already in place: certbot installed, 443 open, the
# challenge webroot mounted into the nginx container, and the challenge path
# served over HTTP. This script only validates, issues, swaps config and
# reloads - it never recreates a container.
set -uo pipefail

HOST="${1:-}"; EMAIL="${2:-}"; MODE="${3:-}"
INFRA=/opt/admission-platform/infra
LIVE=$INFRA/nginx.prod.conf
BACKUP=$INFRA/nginx.prod.conf.pre-tls
WEB=admission-platform-web-1

die() { echo "ERROR: $*" >&2; exit 1; }
[ -n "$HOST" ] && [ -n "$EMAIL" ] || die "usage: $0 <hostname> <email> [--staging]"

echo "==> 1/6  does $HOST point at this server?"
MY4=$(curl -s -m 10 -4 ifconfig.me 2>/dev/null)
GOT=$(getent ahostsv4 "$HOST" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ')
echo "    this server : $MY4"
echo "    $HOST resolves to: ${GOT:-nothing}"
case " $GOT " in
  *" $MY4 "*) echo "    ok" ;;
  *) die "$HOST does not resolve to $MY4. Add an A record pointing at it, wait for the TTL, then re-run." ;;
esac

echo "==> 2/6  can the certificate authority reach the challenge path over that name?"
echo "mitra-acme-ok" > /var/www/certbot/.well-known/acme-challenge/selftest
BODY=$(curl -s -m 15 "http://$HOST/.well-known/acme-challenge/selftest")
[ "$BODY" = "mitra-acme-ok" ] || die "http://$HOST/.well-known/acme-challenge/selftest did not return the test value (got: '$BODY')."
echo "    ok"

echo "==> 3/6  requesting the certificate"
STAGING=""; [ "$MODE" = "--staging" ] && STAGING="--staging" && echo "    (staging - this certificate will NOT be trusted by browsers)"
certbot certonly --webroot -w /var/www/certbot -d "$HOST" \
  --non-interactive --agree-tos -m "$EMAIL" --keep-until-expiring $STAGING || die "certbot failed - nothing has been changed"
[ -f "/etc/letsencrypt/live/$HOST/fullchain.pem" ] || die "certificate files not found after issuance"
echo "    issued: $(openssl x509 -enddate -noout -in /etc/letsencrypt/live/$HOST/fullchain.pem)"

echo "==> 4/6  writing the HTTPS configuration"
cp "$LIVE" "$BACKUP"
sed -e "s/mitra\.mafsu\.ac\.in/$HOST/g" "$INFRA/nginx.https.template.conf" > "$LIVE.new"
# carry over the rate-limit zone, which lives at the top of the live file
grep -q "limit_req_zone" "$LIVE.new" || sed -i "1i $(grep -h 'limit_req_zone' "$BACKUP")" "$LIVE.new"
mv "$LIVE.new" "$LIVE"

echo "==> 5/6  testing and reloading nginx"
if ! docker exec "$WEB" nginx -t >/dev/null 2>&1; then
  docker exec "$WEB" nginx -t
  cp "$BACKUP" "$LIVE"; docker exec "$WEB" nginx -s reload
  die "new configuration failed nginx -t; rolled back to the previous one"
fi
docker exec "$WEB" nginx -s reload || { cp "$BACKUP" "$LIVE"; docker exec "$WEB" nginx -s reload; die "reload failed; rolled back"; }
sleep 2

echo "==> 6/6  verifying"
FAIL=0
R=$(curl -s -o /dev/null -w '%{http_code}' -m 15 "https://$HOST/api/healthz" ${STAGING:+-k}) ; echo "    https healthz     -> $R"; [ "$R" = "200" ] || FAIL=1
R=$(curl -s -o /dev/null -w '%{http_code}' -m 15 "http://$HOST/")                          ; echo "    http redirect     -> $R (expect 301)"; [ "$R" = "301" ] || FAIL=1
R=$(curl -sI -m 15 "https://$HOST/" ${STAGING:+-k} | grep -ci "strict-transport-security") ; echo "    HSTS header       -> $R (expect 1)"; [ "$R" = "1" ] || FAIL=1
R=$(curl -s -o /dev/null -w '%{http_code}' -m 15 "https://$HOST/admin/" ${STAGING:+-k})    ; echo "    admin still shut  -> $R (expect 404)"; [ "$R" = "404" ] || FAIL=1
R=$(curl -s -o /dev/null -w '%{http_code}' -m 15 --resolve "$HOST:443:$MY4" "https://$MY4/" -k 2>/dev/null || echo 000)
echo "    raw IP over TLS   -> $R (expect 000/444 - unknown hostnames are dropped)"

if [ "$FAIL" = "1" ]; then
  echo
  echo "One or more checks failed. To roll back:"
  echo "  cp $BACKUP $LIVE && docker exec $WEB nginx -s reload"
  exit 1
fi

echo
echo "HTTPS is live on https://$HOST"
echo "Next:"
echo "  1. point the widget at https://$HOST/api/chat  (data-chat-url)"
echo "  2. add the MAFSU page origin to CORS_ORIGINS for the api service, then roll the replicas"
echo "  3. renewal is automatic - verify with: certbot renew --dry-run"
echo "  4. keep $BACKUP until you are sure; it is the one-command way back"
