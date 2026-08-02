# Calisthenics Trainer — Web version

Same engine as the Windows app (`core/` is unchanged, copy-pasted) — this
just swaps CustomTkinter for a Flask web front end, so you open it from
any browser instead of dealing with iOS sideloading at all.

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
