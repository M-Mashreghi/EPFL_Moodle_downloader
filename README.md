# EPFL Moodle Downloader

Downloads everything from your EPFL Moodle courses to your PC: slides, PDFs,
folders, assignment files, pages, links, and videos (uploaded to Moodle,
YouTube, Vimeo, Zoom recordings, and more). Files are sorted by course and
week. Each later run downloads only what's new or changed, so you can run it
every week, or let Windows run it for you.

```
D:\EPFL Courses\
├── Analyse I\
│   ├── 00 - General\
│   │   └── syllabus.pdf
│   ├── 01 - Week 1 - Limits\
│   │   ├── lecture1.pdf
│   │   ├── Exercises\ex1.pdf
│   │   ├── Lecture recording [abc123].mp4
│   │   └── Course website.url
│   └── 02 - Week 2 - Derivatives\
├── Physique générale I\
└── _Could not download.html    ← only if something failed
```

---

## Requirements

- Windows 10 or 11
- Microsoft Edge (already on every Windows PC, used only to sign in)
- An EPFL account with access to moodle.epfl.ch

Python is only needed if you build the `.exe` yourself (see
[Build from source](#build-from-source)).

---

## Quick start

### 1. Get the program

- **Easiest:** download `EPFL-Moodle-Downloader.exe` from this repository's
  **Releases** page, if one is published.
- **Or build it yourself:** see [Build from source](#build-from-source).

Put the `.exe` in a folder where it can stay, for example
`D:\Moodle downloader\`. The weekly task runs it from that location.

### 2. First run

Double-click `EPFL-Moodle-Downloader.exe`. A black window opens and asks:

1. **EPFL username:** your GASPAR username, for example `jdoe` (not your email).
2. **EPFL password:** nothing is shown while you type. That's normal.
3. **Download folder:** a folder picker opens. Choose where courses go.
4. **Download videos too?** Press Enter for yes, or type `n` for no.
5. **Run automatically every week?** Press Enter for yes (Monday 12:00).

It then signs in and starts downloading. The first run can take a long
time if your courses have many videos. Leave the window open until it
says **Done**.

> **Two-factor authentication (2FA):** if EPFL asks for a second factor,
> the hidden sign-in can't finish on its own. After about two minutes a
> browser window opens. Complete the 2FA there (for example, approve it in
> your authenticator app), and the download continues. You only need to do
> this when the saved login expires.

### 3. Every week after that

Nothing to do. If you accepted the weekly task, Windows runs the program
every Monday at 12:00. If the PC was off at that time, it runs at the next
start-up. You can also double-click the `.exe` anytime to fetch the latest
files right away.

---

## Where things are saved

| What | Where |
|---|---|
| Your courses | The download folder you chose |
| Password and login token | Windows Credential Manager (encrypted by Windows) |
| Username and folder choice | `%APPDATA%\EPFLMoodleDownloader\config.json` |
| Download history and log | `<download folder>\.moodle-downloader\` |
| Failure report | `<download folder>\_Could not download.html` |

Your password is never written to a plain file, and nothing personal is
stored inside the program's own folder.

---

## Videos

The program tries every video it can find:

- videos uploaded to Moodle
- YouTube links and embedded YouTube players
- links to about 1800 other video sites (Vimeo, Zoom recordings,
  SwitchTube, direct `.mp4` links, and more)
- any other link a teacher added: if the page contains a video, it's
  downloaded; if not, a shortcut (`.url`) to the page is saved instead

Videos are saved up to 1080p. ffmpeg is built in. The first YouTube download
may take an extra minute while the program sets up a small JavaScript helper
that YouTube requires (Deno, downloaded once if Node or Deno isn't
installed).

To skip videos for one run: `EPFL-Moodle-Downloader.exe --no-videos`.
To turn them off permanently, run `--setup` and answer `n`.

---

## When something can't be downloaded

At the end of every run, the window lists anything that failed, with the
course, section, link and reason. The same list is saved as
`_Could not download.html` in your download folder. Open it in your browser
to click the links.

Failed items are retried on every run. The report disappears once
everything succeeds.

Common reasons:

| Reason in the report | What it means / what to do |
|---|---|
| `Private video`, `Video unavailable` | The video was removed or made private. Nothing to fix on your side. |
| `Sign in to confirm your age` / `you're not a bot` | YouTube wants a signed-in browser. Open the link and watch or download it manually. |
| `HTTP Error 403` / `401` | The site needs a login the program doesn't have (for example, some MediaSpace or Zoom recordings). Open the link in your browser. |
| `Unable to connect`, timeouts | Network problem. It will retry next run. |
| `could not read course` | Moodle refused access to that course, often an old or hidden course. |

---

## Options

Run these from a terminal (PowerShell or Command Prompt) in the program's
folder:

| Command | What it does |
|---|---|
| `EPFL-Moodle-Downloader.exe` | Download new files now |
| `EPFL-Moodle-Downloader.exe --setup` | Change username, password, folder or video choice |
| `EPFL-Moodle-Downloader.exe --schedule FRI --at 18:30` | Run weekly on another day or time (MON … SUN) |
| `EPFL-Moodle-Downloader.exe --unschedule` | Stop the weekly run |
| `EPFL-Moodle-Downloader.exe --course "Analyse"` | Only courses whose name contains this text |
| `EPFL-Moodle-Downloader.exe --no-videos` | Skip videos this time |
| `EPFL-Moodle-Downloader.exe --show-browser` | Show the sign-in window (for troubleshooting) |

> **Moved the `.exe`?** The weekly task still points to the old location.
> Run `EPFL-Moodle-Downloader.exe --schedule` once from the new place.

---

## Troubleshooting

**Windows says "Windows protected your PC".**
The program isn't signed by a publisher. Click **More info**, then **Run anyway**.

**Sign-in fails or keeps asking.**
Run `EPFL-Moodle-Downloader.exe --setup` and re-enter your password (for
example, after you change it). If it still fails, run with `--show-browser`
to watch what happens.

**The weekly run didn't happen.**
Open **Task Scheduler** and look for **EPFL Moodle Downloader**. If it's
missing or points to an old location, run `--schedule` again.

**I deleted a downloaded file and want it back.**
Run the program again. Missing files are downloaded again.

**Something else.**
Look at `<download folder>\.moodle-downloader\log.txt`, which has the full
output of every run.

---

## Build from source

1. Install **Python 3.10 or newer** from [python.org](https://www.python.org/downloads/)
   and tick **Add Python to PATH** during installation.
2. Download or clone this repository.
3. Double-click **`build.bat`**. It creates a virtual environment, installs
   the dependencies (`requirements.txt`) and packages everything with
   PyInstaller.
4. The finished `EPFL-Moodle-Downloader.exe` appears in the same folder
   (about 90 MB).

To run without building: `python -m moodle_downloader` in this folder,
after `pip install -r requirements.txt`.

### Project layout

```
moodle_downloader/
  app.py         first-run setup, options, weekly task
  auth.py        EPFL sign-in (gets a Moodle app token through Edge)
  api.py         Moodle web-service client
  downloader.py  walks courses, downloads files/videos, writes the report
  tools.py       ffmpeg and JavaScript runtime for video downloads
  config.py      settings and Windows Credential Manager storage
build.bat        builds the .exe
run.py           entry point for PyInstaller
```

### How sign-in works

EPFL accounts use single sign-on, so Moodle's plain username/password
login doesn't work for them. The program does what the official Moodle
mobile app does: it opens Moodle's app-login page in a hidden Edge window,
fills in your saved credentials, and receives a Moodle access token. That
token is stored in Windows Credential Manager and reused until it expires.
All downloads then go through Moodle's official web-service API.

---

## Disclaimer

This is an unofficial tool, not made or supported by EPFL. Use it only for
courses you're enrolled in, and keep the downloaded material for your own
study. Course content belongs to its authors.
