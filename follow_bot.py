#!/usr/bin/env python3
"""
TikTok follow-back bot — hybrid.
- Scrape: comment API direct with cookie header (no browser, works from any IP)
- Follow: X-Bogus v2 via npm tiktok-signature (puppeteer chromium on runner)
"""
import json, os, random, re, subprocess, sys, time, urllib.request, urllib.parse
from pathlib import Path

BASE = Path(__file__).parent
COOKIE_FILE = BASE / "tiktok_cookies.json"
CACHE_FILE = BASE / "targets_cache.json"
LOG_FILE = BASE / "follow_log.json"

DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "60"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "15"))
MIN_DELAY = float(os.environ.get("MIN_DELAY", "75"))
MAX_DELAY = float(os.environ.get("MAX_DELAY", "120"))
SEED_VIDEOS = os.environ.get("SEED_VIDEOS", "7679312134496324885,7652009062904761621").split(",")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# --- cookies ---
def load_cookies():
    if os.environ.get("TIKTOK_COOKIE_HEADER"):
        return os.environ["TIKTOK_COOKIE_HEADER"]
    cookies = json.loads(COOKIE_FILE.read_text())
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)

COOKIE_STR = ""

# --- http ---
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
        return {"error": e.code, "body": e.read().decode()[:150]}
    except Exception as e:
        return {"error": str(e)[:150]}

def get_comments(vid, count=300):
    comments = []
    cursor = 0
    pages = 0
    while pages < 12 and len(comments) < count:
        d = http("https://www.tiktok.com/api/comment/list/", {
            "aweme_id": vid, "count": "50", "cursor": cursor, "aid": "1988"})
        if d.get("error") or not d.get("comments"):
            break
        cmts = d["comments"]
        comments.extend(cmts)
        cursor = d.get("cursor") or (cursor + 50)
        pages += 1
        if not d.get("hasMore"):
            break
        time.sleep(1)
    return comments

# --- signature (X-Bogus v2 via npm tiktok-signature) ---
def get_xbogus(url):
    """Generate X-Bogus v2 using tiktok-signature npm (puppeteer-based)."""
    code = (
        "const { TikTokSignature } = require('tiktok-signature');"
        "(async () => {"
        "  const s = new TikTokSignature('" + UA + "');"
        "  await s.init();"
        "  const sig = await s.sign('" + url + "');"
        "  process.stdout.write(JSON.stringify(sig));"
        "  await s.close();"
        "})().catch(e => { process.stderr.write(String(e).slice(0,300)); process.exit(1); });"
    )
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True,
                       cwd=str(BASE), timeout=60)
    if r.returncode != 0:
        print("  sig err:", r.stderr[-200:])
        return ""
    try:
        obj = json.loads(r.stdout.strip())
        return obj.get("X-Bogus") or ""
    except Exception:
        return ""

def follow_user(uid, sec_uid):
    q = {"aid": "1988", "user_id": uid, "secUid": sec_uid,
         "from_page": "user", "type": "1", "source_type": "personal_homepage"}
    base = "https://www.tiktok.com/api/social/follow/?" + urllib.parse.urlencode(q)
    bogus = get_xbogus(base)
    if not bogus:
        return "sig_fail"
    url = base + "&X-Bogus=" + bogus
    d = http(url, post=True)
    msg = d.get("status_msg") or d.get("error") or json.dumps(d)[:80]
    return msg

KEYWORDS = [
    r"follow\s*back", r"followback", r"f4f", r"follw\s*back", r"follow\s*for\s*follow",
    r"follow4follow", r"back\s*follow", r"fb\b", r"f2f", r"mutual", r"moots",
    r"follback", r"follow\s*balik", r"follow\s*bck", r"pasti\s*di\s*fb", r"di\s*fb",
    r"kumpul.*fb", r"fb\s*kok", r"fb\s*ko", r"fb\s*kokk", r"pasti\s*fb",
    r"affiliate\s*pemula", r"akun\s*baru", r"day\s*1\s*akun", r"day\s*2\s*akun",
    r"geng\s*viral", r"kumpul\s*geng", r"akun\s*baruuu",
]
FLEX = re.compile("|".join(KEYWORDS), re.I)

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
    global COOKIE_STR
    COOKIE_STR = load_cookies()
    today = time.strftime("%Y-%m-%d")
    cache = load_json(CACHE_FILE, [])
    log = load_json(LOG_FILE, {"days": {}, "followed": {}})

    already = set()
    for d in log.get("days", {}).values():
        already.update(d)
    for uid in (log.get("followed") or {}):
        already.add(uid)
    seen = {str(t.get("uid")) for t in cache}

    # --- scrape ---
    new_targets = 0
    for vid in SEED_VIDEOS:
        try:
            cmts = get_comments(vid)
        except Exception as e:
            print(f"comments {vid}: {str(e)[:80]}")
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
                "found_at": time.time(),
            })
            seen.add(uid)
            new_targets += 1
        time.sleep(2)
    save_json(CACHE_FILE, cache)
    print(f"scrape: +{new_targets} new (total {len(cache)})")

    # --- follow batch ---
    followed_today = log["days"].get(today, [])
    remaining = DAILY_LIMIT - len(followed_today)
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
        msg = follow_user(uid, t.get("sec_uid", ""))
        good = ("match" not in msg and "error" not in msg and "sig_fail" not in msg
                and "success" in msg.lower() or msg == "success")
        if good:
            ok += 1
            status = "ok"
            print(f"  ✓ @{t['username']} ({msg})")
        else:
            status = f"fail:{msg[:50]}"
            print(f"  ✗ @{t['username']} ({msg[:60]})")
        followed_map[uid] = {"username": t["username"], "at": time.time(), "status": status}
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    log["days"].setdefault(today, []).extend([str(t["uid"]) for t in batch])
    save_json(LOG_FILE, log)
    print(f"follow: {ok}/{len(batch)} ok, today total {len(log['days'].get(today, []))}")
    print(f"remaining targets: {len(cache) - len(already)}")

if __name__ == "__main__":
    main()