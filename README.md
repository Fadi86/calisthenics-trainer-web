# Calisthenics Trainer — Web version

Same engine as the Windows app (`core/` is unchanged, copy-pasted) — this
just swaps CustomTkinter for a Flask web front end, so you open it from
any browser instead of dealing with iOS sideloading at all.

## v5.7.1 — real bug fix: error messages were hiding the actual detail

Found while chasing down the Gemini 404: `except urllib.error.URLError`
was placed BEFORE `except urllib.error.HTTPError` in both the Claude and
Gemini call functions. Since `HTTPError` is a subclass of `URLError`,
Python matched the first (wrong) clause every time - meaning every HTTP
error (401, 404, 429, etc.) from either provider showed a generic
"Could not reach the API" message instead of the specific detail Gemini
or Claude actually sent back (which exact model wasn't found, which key
was rejected, etc.). Swapped the order so the specific error always wins.

Also added the API key as a `?key=` query param in addition to the
`x-goog-api-key` header for Gemini calls (different doc versions show
different auth methods - sending both removes the ambiguity), and error
messages now include which model name was being requested.

## v5.7.0 — Gemini as a free alternative to Claude

Settings now has an "AI Provider" choice: Claude (paid, usage-billed) or
**Gemini (Google) — which has a genuinely free tier, no credit card
needed**. Get a free key at aistudio.google.com if you'd rather not pay
for the Instant Trainer Recommendation feature. One shared key/provider
setting covers all 5 profiles - nobody needs to set up their own.

Removed the old, now-meaningless "AI feedback mode" (rule_based/claude_api)
toggle left over from the removed Health page - it didn't do anything
useful anymore once Health was replaced with Chat.

## v5.6.0 — Instant Trainer Recommendation (AI chat on Progress)

New card at the bottom of the Progress page: "Get Instant Trainer
Recommendation" sends your real progress data (tiers, last-tested dates,
weighted maxes, recent assessment history) to Claude and gets back a
specific, grounded recommendation - not generic advice. After that, a
chat box lets you keep asking follow-ups ("why am I stuck on X") with the
same context still in play.

**Requires your own Anthropic API key**, set in Settings (same field the
old Health page used) - billed to you directly, nothing is embedded in
the app. No key set -> a clear message telling you to add one, not a
crash. "Clear conversation" resets and lets you start fresh any time.

This conversation is private to your profile - it's stored separately
from the shared group Chat between the 5 profiles, and never mixes with
another profile's data.

## v5.5.0 — full history management (redo weeks, edit/delete everything)

- **Redo Week** (Schedule tab) - regenerates the CURRENT week with fresh
  picks instead of always creating a new one. "Start Week N" still moves
  forward; this replaces in place.
- **Delete Week** (Schedule and Calendar tabs) - removes a week from
  history entirely.
- **Calendar prev/next navigation** - step through weeks directly instead
  of only using the dropdown.
- **Calendar now shows what you actually logged**, not just what was
  planned - each day shows a real "Actually logged" section with your
  logged sets, and you can edit or delete individual sets, or the whole
  session, right there.
- **Assessment History** (Progress tab) - your last 25 assessments, each
  editable or deletable. Fixing a typo or removing a bad entry correctly
  recomputes the tier from whatever assessment is now the most recent for
  that pattern - confirmed this handles the "performance dropped due to
  injury" case correctly too (tested end-to-end: strong result -> tier up,
  weak result entered afterward -> tier correctly comes back down, Progress
  page shows "regress").

## v5.4.0 — "Full Body" groups the non-muscle categories

The category dropdown (1st classification) had Conditioning/Mobility/
Warm-up sitting as peers next to real muscle groups (Pull/Push/Legs/Core/
Handstand) - but they aren't muscles, which is exactly why the type badge
(3rd classification) kept repeating the same word. Now the dropdown shows
6 options: the 5 muscle groups, plus one "Full Body" that combines all
three non-muscle categories.

This is display-only - each exercise's real `category` field in the
database is completely untouched (a conditioning exercise is still
`category="conditioning"`, not overwritten to "full_body"), so the
scheduler (which depends on those exact real category values to build
e.g. the Handstand+Conditioning day) works exactly as before. Individual
exercise rows still show their true, specific category badge (Conditioning/
Mobility/Warm-up) even inside the Full Body view - only the top-level
filter dropdown is grouped, nothing else.

## v5.3.1 — type filter fix

The "type" dropdown in the Library only ever offered Main/Extra (the raw
underlying data field), while the badges themselves had already grown to
six values (main/skills/mobility/conditioning/extra/accessory) - so
everything looked "mixed together" because the filter couldn't actually
narrow down to any of the newer classifications. The dropdown now offers
all six, and filtering works against the same classification the badges
show, not the old binary field.

## v5.3.0 — muscle-linked warm-up/mobility in the Library

Selecting a muscle-group category (Legs, Pull, Push, Core) now also shows
a "Related warm-up & mobility" section below the main list - exercises
whose own category is Warm-up/Mobility/Conditioning, but whose tagged
muscles match that group. Found via muscle tags, not a rigid category
reassignment, so an item can legitimately appear under more than one group
(shoulder mobility shows under both Push and Pull, for instance) instead
of being forced into a single "correct" bucket.

## v5.2.0 — automatic backups, group chat, Health removed

- **Health tab removed, replaced with Chat** - a simple shared group chat
  visible to all 5 profiles (new messages appear automatically every few
  seconds, no manual refresh needed).
- **Automatic safety-net backup** - roughly once a day, a full snapshot of
  every profile's data plus the chat log gets written to a plain JSON file
  on the server (`data/backups/`), completely separate from both the live
  database and the git repo. A `git pull` deployment can never touch it,
  and it survives even if the live database were somehow damaged. Keeps
  the last 14 days automatically. You can also download it manually any
  time from Settings ("Download ALL Profiles Backup").
- **Added `.gitignore`** - the database file and the backups folder are
  now explicitly excluded from git, so personal data can never accidentally
  end up in a commit.

### Updating your already-deployed PythonAnywhere site

```
cd ~/calisthenics-trainer-web
git pull
```
Then go to the Web tab and click Reload. Existing data is untouched -
this only adds a new `chat_messages` table and a `data/backups/` folder,
nothing is deleted or restructured.

## v5.1.0 — mobile clarity pass

- **Bottom nav redesigned**: was a single cramped row (9 items squeezed
  into ~36-50px each, only 32px tall). Now a 3x3 grid with a small icon
  above each label - every item measures 125x52px, well above the 44px
  minimum mobile touch target, with zero horizontal overflow.
- **Library classification fixed**: three distinct badges - category
  (Pull/Push/Legs/Core/Handstand/Conditioning/Warm-up/Mobility), tier
  (unchanged), and type (main/skills/mobility/conditioning/extra/accessory)
  - now always render grouped together on their own line under the
  exercise name, instead of the type badge sometimes wrapping onto a
  separate line disconnected from the other two (measured and confirmed
  with real browser layout, not just code review).
- **Mobility library rounded out**: added knee and ankle-plantarflexion
  coverage, closing the last body-region gaps (now 28 mobility exercises
  across 13 regions).

## v5.0.0 — multi-profile support (up to 5 people)

One app password still gates the whole site (unchanged). After logging in,
you now pick **which profile's data** to view/edit from a shared list of
up to 5 - no per-person password, since this is for a small trusted
testing group, not a public multi-tenant product.

- **"Who's training?" screen** appears after login if no profile is
  selected yet. Create up to 5 profiles, switch between them any time via
  the name shown in the top-right corner, delete a profile (and everything
  scoped to it) if needed.
- **Every table that holds personal data is now profile-scoped**:
  assessments, tier progress, sessions/sets, health metrics, and the
  weekly schedule history. Two profiles' data never mixes.
- **Backup export/import is now per-profile** - exporting only downloads
  the currently active profile's data, and importing only restores into
  the currently active profile (never overwrites someone else's).

### If you already had real data (your own account before this update)

Your existing data automatically migrates into a real profile named after
whatever was already in your Profile page (or "Profile 1" if you hadn't
filled that in) - nothing is deleted. This was tested against a simulated
copy of the actual production schema/data before shipping.

### Updating your already-deployed PythonAnywhere site

```
cd ~/calisthenics-trainer-web
git pull
```
Then go to the Web tab and click Reload. First visit after updating will
either ask for your password (unchanged) or, if you're already logged in,
take you straight to your migrated profile.

## v4.0.0 — what's new

- **Password login** — first visit sets a password, every visit after
  requires it. Your data is now protected on the public URL.
- **Profile page** — name, gender, age, weight, height. Saved directly to
  the server database (no manual export needed), and included in backups.
- **Real weekly history** — generating a new schedule no longer erases the
  old one. Every week is kept with its real calendar date. Browse them all
  on the new **Calendar** page.
- **Progress page rewritten** — under each of Pull/Push/Core/Legs, shows
  the well-known calisthenics skills specifically (Pull-up/Chin-up,
  Muscle-up, Front/Back Lever, Planche, L-sit, Dragon Flag, Pistol Squat,
  etc.), each with its tier, last assessment date, the date your next
  reassessment is due (computed from your Settings interval), and a short
  recommendation (ready to progress / hold here / regress).
- **Weighted Strength Maxes now has 3 tests**: Pull-up and Dip (reps x
  weight -> estimated 1RM via Epley), and **Weighted Plank** — logged as
  weight + hold duration directly, since Epley's formula is for reps, not
  isometric holds, and applying it to a hold would just be a made-up number.
- **Tier colors** — T1 through T6 each get a distinct color everywhere a
  tier badge appears, for fast visual scanning.
- **Category icons in the Library** — 💪 pull, 🔼 push, 🦵 legs, 🎯 core,
  🤸 handstand, 🏃 conditioning, 🔥 warm-up, 🧘 mobility.
- **Language toggle** (Settings) — Arabic for menus/labels/buttons, but
  exercise names and cues always stay in English (that content isn't
  translated, on purpose).
- **PDF export with clickable YouTube links** — the Watch buttons are real
  hyperlinks (not JavaScript), so when you Print → Save as PDF from your
  phone, the exercise names in the PDF stay tappable and open YouTube.

### Updating your already-deployed PythonAnywhere site

```
cd ~/calisthenics-trainer-web
git pull
```
Then go to the Web tab and click Reload. Your existing data (assessments,
sessions, tiers) is untouched — the database only gains new columns/tables,
nothing is deleted. **First load after updating will ask you to set a
password** since none existed before.

## Earlier changes

- **Tier badge** next to every exercise everywhere (library, schedule, train)
- **Schedule editing** — swap, remove, or add exercises to any day, right
  from the Schedule page (tap "Edit" under any exercise)
- **Guided work/rest timer** on the Train page — tap "Start Guided Timer"
  on any exercise, it counts down work → rest → work automatically for
  all your sets, with a beep at each transition and a longer beep when done
- **Watch button everywhere** — schedule, train, and library, for every
  single exercise (pre-fetched video if you've run `fetch_videos.py`,
  otherwise a live YouTube search link)
- **60-minute day cap** — shown as "~XX min" on each schedule day; if a day
  would run long, lowest-priority items get trimmed automatically (see the
  Windows app's changelog for the exact priority order)

## Setup

```
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:5000** on the same computer to confirm it works.

## Opening it from your phone

**Option A — same WiFi as your PC (works today, zero extra setup):**

1. Find your PC's local IP address:
   - Windows: open Command Prompt, run `ipconfig`, look for "IPv4 Address"
     (something like `192.168.1.23`)
2. Make sure your PC's firewall allows incoming connections on port 5000
   (Windows will usually prompt you the first time you run the app — allow it)
3. On your phone, connected to the **same WiFi network**, open:
   `http://192.168.1.23:5000` (use your actual IP)
4. Bookmark it / add to home screen for quick access

This only works while your PC is on and both devices are on the same WiFi.

**Option B — access from anywhere (free, more setup):**

Deploy to a free hosting service like Render.com, which can build straight
from your GitHub repo (same one from the iOS build, or a new one).

Important trade-off: most free hosting tiers have **ephemeral storage** —
your SQLite database (workout history, assessments) may reset every time
the service restarts or redeploys, unless you pay for a persistent disk
add-on. For now, Option A (local network) keeps your data safe; Option B
is better suited to "let me check my schedule from anywhere" than to
long-term history tracking, until a persistent-disk tier is set up.

If you want to try it anyway:
1. Push this folder to a GitHub repo
2. On Render.com, create a new "Web Service", connect the repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `python app.py`
5. Render gives you a public `https://your-app.onrender.com` URL

## The guided timer, in plain terms

Each exercise gets a work/rest estimate based on its tier (from the same
`prescriptions.json` used everywhere else in the app):
- Hold-based exercises: work time = top of your target hold range
- Rep-based exercises: work time = a reasonable window to complete your
  reps unrushed (not a strict pace — no need to rush)
- Rest time: the midpoint of your tier's prescribed rest range

Tap **Start Guided Timer**, and it walks through work → rest → work for
however many sets that exercise calls for, beeping at each transition
(short beep at each switch, longer beep when the whole set block is done).
Pause and Skip buttons are there if you need to adjust on the fly.

## Testing

This version was tested with real HTTP requests through Flask's test
client (not a UI stub like the desktop versions needed) — every route,
every form submission, the JSON APIs for the timer/session, and the
schedule editing endpoints were exercised directly:

```
python tests/test_web_app.py
```

Should print `ALL WEB APP TESTS PASSED` at the end.

## Known limitations

- Single-user by design (like the desktop versions) — the Flask session
  cookie tracks "the active session" per browser, not per login account.
  Fine for personal use on your own devices.
- No HTTPS by default when self-hosting locally — fine on a private home
  network, but don't expose port 5000 directly to the open internet
  without adding a reverse proxy + TLS certificate first.
- Health data import is manual-entry only in this version (same as the
  current Windows app) — file import can be added later.
