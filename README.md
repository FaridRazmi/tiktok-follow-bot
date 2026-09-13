# TikTok Follow Bot (GitHub Actions)

Auto follow-back bot for @hziqadam. Scrapes followback comments from seed videos,
follows targets at a safe rate (60/day max), and reports to Telegram.

## Setup (6 steps)

1. **Fork/import repo** to your GitHub account.

2. **Add secrets** (Settings → Secrets and variables → Actions → New repository secret):
   - `TIKTOK_COOKIE_HEADER` — paste cookie header string:
     Open tiktok.com in browser (logged in) → DevTools (F12) → Network →
     click any request → Request Headers → copy the whole `cookie: ...` value.
   - `TIKTOK_COOKIES_JSON` — optional. If you used Cookie-Editor export, base64 it:
     `base64 -w0 tiktok_cookies.json` → paste value.
   - `TG_BOT_TOKEN` — your Telegram bot token (reidinfo or any).
   - `TG_CHAT_ID` — `888551505`.

3. **Enable workflow**: Actions tab → enable.

4. **Test run now**: Actions → TikTok Follow Bot → Run workflow (manual trigger).

5. Bot runs 4×/day (10:00, 13:00, 16:00, 20:00 MYT = 02:00, 05:00, 08:00, 12:00 UTC).

6. **Refresh cookies** when msToken expires (~10 days):
   Re-copy cookie header → update `TIKTOK_COOKIE_HEADER` secret.

## Notes

- Seed videos env `SEED_VIDEOS` configurable (default: known f4f videos).
- Batch size 15/run, daily cap 60, delay 75–120s between follows.
- X-Bogus signed via npm `xbogus` (works on Linux runner).
- If follow requests fail with "url doesn't match", signature version needs
  updating — swap `xbogus` for `tiktok-signature` (npm, uses puppeteer) for
  X-Bogus v2 + X-Gnarly. See `follow_bot.py` `make_bogus()`.

## Files

- `follow_bot.py` — main bot (scrape + follow + log)
- `.github/workflows/follow.yml` — schedule + Telegram report
- `tiktok_cookies.json` — cookie store (gitignored or secret)