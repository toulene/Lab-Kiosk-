#!/bin/bash
# Opens the kiosk full-screen once the server is up. Started by the desktop at login.
URL="http://127.0.0.1:5000"

for i in $(seq 1 120); do
    curl -s -o /dev/null "$URL/api/status" && break
    sleep 1
done

BROWSER=$(command -v chromium-browser || command -v chromium)
exec "$BROWSER" --kiosk --incognito --noerrdialogs --disable-infobars --no-first-run \
    --disable-session-crashed-bubble --disable-features=Translate --password-store=basic \
    --check-for-update-interval=31536000 "$URL"
