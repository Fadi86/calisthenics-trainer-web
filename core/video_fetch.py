"""
core/video_fetch.py — automatically finds a demonstration video for each
exercise via YouTube Data API v3, so you're not manually searching or
linking 208 videos by hand.

Needs a free API key (Google Cloud Console -> enable "YouTube Data API v3"
-> Credentials -> Create API key). Free quota is 10,000 units/day; each
search costs 100 units, so ~100 exercises/day on the free tier — running
this once covers the whole library in 2-3 days, or once if you request a
quota bump (also free, just a form).

No extra pip install — uses urllib from the standard library.
"""
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from core import db as dbmod
from core import library

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


def build_query(exercise):
    return f"{exercise['name']} exercise tutorial correct form"


def search_youtube(api_key, query, max_results=3):
    """Returns a list of {video_id, title, channel, url} or raises on error."""
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_results,
        "key": api_key,
        "videoEmbeddable": "true",
        "safeSearch": "moderate",
    }
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"YouTube API error {e.code}: {body[:300]}")
    except urllib.error.URLError as e:
        raise ConnectionError(f"Could not reach YouTube API: {e}")

    results = []
    for item in data.get("items", []):
        vid = item.get("id", {}).get("videoId")
        if not vid:
            continue
        snippet = item.get("snippet", {})
        results.append({
            "video_id": vid,
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    return results


def save_videos(conn, exercise_id, videos):
    for i, v in enumerate(videos):
        conn.execute("""
            INSERT INTO exercise_videos (exercise_id, video_id, title, channel, url, is_primary, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (exercise_id, v["video_id"], v["title"], v["channel"], v["url"],
              1 if i == 0 else 0, dbmod.now_iso()))
    conn.commit()


def fetch_all(conn, api_key, only_missing=True, limit=None, max_results_per_exercise=1,
              sleep_seconds=0.5, progress_callback=None):
    """
    Fetches a video for every exercise (or only ones without one yet).
    Returns {"done": n, "skipped": n, "errors": [(exercise_id, message), ...]}.
    Stops early and reports clearly if the API key is invalid or quota runs out —
    doesn't silently fail partway through.
    """
    exercises = library.list_exercises(conn)
    if only_missing:
        has_video = {r["exercise_id"] for r in
                     conn.execute("SELECT DISTINCT exercise_id FROM exercise_videos")}
        exercises = [e for e in exercises if e["id"] not in has_video]
    if limit:
        exercises = exercises[:limit]

    done, skipped, errors = 0, 0, []
    for i, ex in enumerate(exercises):
        try:
            videos = search_youtube(api_key, build_query(ex), max_results_per_exercise)
            if videos:
                save_videos(conn, ex["id"], videos)
                done += 1
            else:
                skipped += 1
        except RuntimeError as e:
            # quota exceeded or bad key — these repeat for every subsequent
            # call, so stop instead of burning through the rest with the
            # same failure
            errors.append((ex["id"], str(e)))
            if "quota" in str(e).lower() or "403" in str(e) or "400" in str(e):
                break
        except ConnectionError as e:
            errors.append((ex["id"], str(e)))
            break

        if progress_callback:
            progress_callback(i + 1, len(exercises), ex["name"])
        time.sleep(sleep_seconds)

    return {"done": done, "skipped": skipped, "errors": errors, "total_considered": len(exercises)}


def get_exercise_youtube_search_url(exercise_name):
    """
    Direct YouTube search link, no API key or pre-fetch needed. This is the
    fallback for any exercise that doesn't have a pre-fetched video yet
    (191 of 208, until fetch_videos.py is run with an API key) - guarantees
    every single exercise has a working "watch" button today.
    """
    query = urllib.parse.quote(f"{exercise_name} calisthenics form tutorial")
    return f"https://www.youtube.com/results?search_query={query}"
