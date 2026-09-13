#!/usr/bin/env python3
"""
TikTok follow-back bot — runs on GitHub Actions.
Uses TikTokApi 6.x (playwright-backed) for signature + follow.
"""
import asyncio, json, os, random, re, sys, time
from pathlib import Path

BASE = Path(__file__).parent
COOKIE_FILE = BASE / "tiktok_cookies.json"
CACHE_FILE = BASE / "targets_cache.json"
LOG_FILE = BASE / "follow_log.json"

DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "60"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "10"))
MIN_DELAY = float(os.environ.get("MIN_DELAY", "75"))
MAX_DELAY = float(os.environ.get("MAX_DELAY", "120"))
SEED_VIDEOS = os.environ.get("SEED_VIDEOS", "7679312134496324885,7652009062904761621").split(",")

async def main():
    from TikTokApi import TikTokApi

    # load cookies
    cookie_dict = {}
    if os.environ.get("TIKTOK_COOKIE_HEADER"):
        for part in os.environ["TIKTOK_COOKIE_HEADER"].split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookie_dict[k] = v
    else:
        cookies = json.loads(COOKIE_FILE.read_text())
        cookie_dict = {c["name"]: c["value"] for c in cookies}

    ms_token = cookie_dict.get("msToken", "")

    async with TikTokApi() as api:
        await api.create_sessions(ms_tokens=[ms_token], num_sessions=1,
                                  headless=True, browser="chromium")

        today = time.strftime("%Y-%m-%d")
        cache = load_json(CACHE_FILE, [])
        log = load_json(LOG_FILE, {"days": {}, "followed": {}})
        already = set()
        for d in log.get("days", {}).values():
            already.update(d)
        seen = {t.get("uid") for t in cache}

        # --- scrape new targets ---
        new_targets = 0
        for vid_id in SEED_VIDEOS:
            try:
                video = api.video(url=f"https://www.tiktok.com/@{'_'}x/video/{vid_id}")
                comments = video.comments(count=200)
                print(f"video {vid_id}: comments fetched")
                for c in comments:
                    text = (c.get("text") or "")
                    if not FLEX.search(text):
                        continue
                    u = c.get("user") or {}
                    uid = str(u.get("id") or u.get("uid") or "")
                    uname = u.get("uniqueId") or u.get("unique_id") or ""
                    if not uid or uid in seen:
                        continue
                    cache.append({
                        "username": uname, "uid": uid,
                        "sec_uid": u.get("secUid") or u.get("sec_uid") or "",
                        "comment": text[:150], "video_id": vid_id,
                        "found_at": time.time(), "followed": False,
                    })
                    seen.add(uid)
                    new_targets += 1
            except Exception as e:
                print(f"scrape {vid_id}: {str(e)[:100]}")
            await asyncio.sleep(2)
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
            try:
                user = api.user(uid)
                await user.follow()
                ok += 1
                followed_map[uid] = {"username": t["username"], "at": time.time(), "status": "ok"}
                print(f"  ✓ @{t['username']}")
            except Exception as e:
                followed_map[uid] = {"username": t["username"], "at": time.time(), "status": f"fail:{str(e)[:60]}"}
                print(f"  ✗ @{t['username']} ({str(e)[:80]})")
            await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        log["days"].setdefault(today, []).extend([t["uid"] for t in batch])
        save_json(LOG_FILE, log)
        print(f"follow: {ok}/{len(batch)} ok, today total {len(log['days'].get(today, []))}")
        print(f"remaining targets: {len(cache) - len(already)}")

def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default

def save_json(path, data):
    path.write_text(json.dumps(data, indent=1))

KEYWORDS = [
    r"follow\s*back", r"followback", r"f4f", r"follw\s*back", r"follow\s*for\s*follow",
    r"follow4follow", r"back\s*follow", r"fb\b", r"f2f", r"mutual", r"moots",
    r"follback", r"follow\s*balik", r"follow\s*bck", r"pasti\s*di\s*fb", r"di\s*fb",
    r"kumpul.*fb", r"fb\s*kok", r"fb\s*ko", r"fb\s*kokk", r"pasti\s*fb",
    r"affiliate\s*pemula", r"akun\s*baru", r"day\s*1\s*akun", r"day\s*2\s*akun",
    r"geng\s*viral", r"kumpul\s*geng", r"akun\s*baruuu",
]
FLEX = re.compile("|".join(KEYWORDS), re.I)

if __name__ == "__main__":
    asyncio.run(main())