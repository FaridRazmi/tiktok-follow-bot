#!/usr/bin/env python3
"""
TikTok follow-back bot — runs on GitHub Actions.
Scrapes followback comments → follows targets at safe rate → tracks followbacks.

Designed for cron schedule (4x/day). Each run follows a small batch.
"""
import json, os, random, re, sys, time, urllib.request, urllib.parse
from pathlib import Path

BASE = Path(__file__).parent
COOKIE_FILE = BASE / "tiktok_cookies.json"
CACHE_FILE = BASE / "targets_cache.json"
LOG_FILE = BASE / "follow_log.json"

# --- config (env-overridable) ---
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "60"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "15"))
MIN_DELAY = float(os.environ.get("MIN_DELAY", "75"))
MAX_DELAY = float(os.environ.get("MAX_DELAY", "120"))

# --- cookies (from GitHub secret via env) ---
COOKIE_STR = os.environ.get("TIKTOK_COOKIE_HEADER", "")
if not COOKIE_STR:
    COOKIE_STR = "; ".join(f"{c['name']}={c['value']}" for c in json.loads(COOKIE_FILE.read_text()))
MS_TOKEN = os.environ.get("TIKTOK_MS_TOKEN", "")
for c in []:
    pass

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# --- signature via Node xbogus (fallback) or npm tiktok-signature ---
def make_bogus(url):
    """Generate X-Bogus using node xbogus package."""
    import subprocess
    code = f"const x=require('xbogus');process.stdout.write(x('{url}','{UA}'))"
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True, cwd=str(BASE), timeout=15)
    return r.stdout.strip()

def sign_url(url):
    """Append X-Bogus to URL."""
    sig = make_bogus(url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}X-Bogus={sig}"

# --- http helpers ---
def http(url, params=None, post=False):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = b"" if post else None
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA, "Cookie": COOKIE_STR,
        "Referer": "https://www.tiktok.com/", "Origin": "https://www.tiktok.com",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        return {"error": e.code, "body": body}
    except Exception as e:
        return {"error": str(e)[:150]}

def get_comments(vid, count=200):
    """Fetch comments for a video (paginated)."""
    comments = []
    cursor = 0
    pages = 0
    while pages < 10 and len(comments) < count:
        d = http("https://www.tiktok.com/api/comment/list/", {
            "aweme_id": vid, "count": "50", "cursor": cursor, "aid": "1988"})
        if d.get("error"):
            print(f"  comment err: {d['error']}")
            break
        cmts = d.get("comments") or []
        if not cmts:
            break
        comments.extend(cmts)
        cursor = d.get("cursor") or (cursor + 50)
        pages += 1
        if not d.get("hasMore") and not d.get("has_more"):
            break
        time.sleep(1.2)
    return comments

KEYWORDS = [
    r"follow\s*back", r"followback", r"f4f", r"follw\s*back", r"follow\s*for\s*follow",
    r"follow4follow", r"back\s*follow", r"fb\b", r"f2f", r"mutual", r"moots",
    r"follback", r"follow\s*balik", r"follow\s*bck", r"pasti\s*di\s*fb", r"di\s*fb",
    r"kumpul.*fb", r"fb\s*kok", r"fb\s*ko", r"fb\s*kokk", r"pasti\s*fb",
    r"affiliate\s*pemula", r"akun\s*baru", r"day\s*1\s*akun", r"day\s*2\s*akun",
    r"geng\s*viral", r"kumpul\s*geng", r"akun\s*baruuu",
]
FLEX = re.compile("|".join(KEYWORDS), re.I)

# seed videos: known-good IDs with f4f comments + refresh via env
SEED_VIDEOS = os.environ.get("SEED_VIDEOS", "7679312134496324885,7652009062904761621").split(",")

def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default

def save_json(path, data):
    path.write_text(json.dumps(data, indent=1))

def main():
    today = time.strftime("%Y-%m-%d")
    cache = load_json(CACHE_FILE, [])
    log = load_json(LOG_FILE, {"days": {}, "followed": {}, "followbacks": {}})

    already = set()
    for d in log.get("days", {}).values():
        already.update(d)
    for uid, info in (log.get("followed") or {}).items():
        already.add(uid)

    # --- scrape new targets ---
    new_targets = 0
    seen = {t.get("uid") for t in cache}
    for vid in SEED_VIDEOS:
        try:
            cmts = get_comments(vid)
        except Exception as e:
            print(f"comments {vid}: {e}")
            continue
        print(f"video {vid}: {len(cmts)} comments")
        for c in cmts:
            text = c.get("text") or ""
            if not FLEX.search(text):
                continue
            u = c.get("user") or {}
            uid = str(u.get("uid") or "")
            uname = u.get("unique_id") or u.get("uniqueId") or ""
            if not uid or uid in seen:
                continue
            cache.append({
                "username": uname, "uid": uid,
                "sec_uid": u.get("sec_uid") or u.get("secUid") or "",
                "comment": text[:150], "video_id": vid,
                "found_at": time.time(), "followed": False,
            })
            seen.add(uid)
            new_targets += 1
        time.sleep(2)
    save_json(CACHE_FILE, cache)
    print(f"scrape: +{new_targets} new (total {len(cache)})")

    # --- follow batch ---
    followers_today = log["days"].get(today, [])
    remaining = DAILY_LIMIT - len(followers_today)
    if remaining <= 0:
        print(f"daily limit reached ({DAILY_LIMIT})")
        return

    candidates = [t for t in cache if str(t.get("uid")) not in already]
    random.shuffle(candidates)
    batch = candidates[:min(BATCH_SIZE, remaining)]
    if not batch:
        print("no candidates left")
        return

    ok = 0
    followed_map = log.setdefault("followed", {})
    for t in batch:
        uid = str(t.get("uid"))
        sec = t.get("sec_uid", "")
        # follow via signed URL
        q = {"aid": "1988", "user_id": uid, "secUid": sec,
             "from_page": "user", "type": "1", "source_type": "personal_homepage"}
        url = "https://www.tiktok.com/api/social/follow/?" + urllib.parse.urlencode(q)
        url = sign_url(url)
        d = http(url, post=True)
        msg = d.get("status_msg") or d.get("error") or json.dumps(d)[:80]
        if d.get("status_code") == 0 and "match" not in str(msg):
            ok += 1
            followed_map[uid] = {"username": t["username"], "at": time.time(), "status": "ok"}
            print(f"  ✓ @{t['username']} ({msg})")
        else:
            followed_map[uid] = {"username": t["username"], "at": time.time(), "status": f"fail:{msg}"}
            print(f"  ✗ @{t['username']} ({msg})")
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    log["days"].setdefault(today, []).extend(followed_map.keys())
    # careful: extend with batch uids
    save_json(LOG_FILE, log)
    print(f"follow: {ok}/{len(batch)} ok today total {len(log['days'].get(today, []))}")
    print(f"remaining targets: {len(cache) - len(already)}")

if __name__ == "__main__":
    main()