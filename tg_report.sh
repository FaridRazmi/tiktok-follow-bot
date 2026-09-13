#!/bin/bash
# Telegram report helper for TikTok bot
set -u
TG_TOKEN="$1"
TG_CHAT="$2"
SUMMARY_FILE="${3:-run_output.txt}"

SUMMARY="$(tail -8 "$SUMMARY_FILE" 2>/dev/null || echo 'no output')"
python3 -c "
import json, sys, urllib.request
token, chat = sys.argv[1], sys.argv[2]
summary = sys.stdin.read()
text = '🤖 TikTok bot:\n' + summary
data = json.dumps({'chat_id': chat, 'text': text}).encode()
req = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage',
                             data=data, headers={'Content-Type': 'application/json'})
try:
    urllib.request.urlopen(req, timeout=20)
except Exception as e:
    print('TG send err:', e)
" "$TG_TOKEN" "$TG_CHAT" <<< "$SUMMARY"