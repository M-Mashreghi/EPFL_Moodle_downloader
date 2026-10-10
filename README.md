# EPFL Moodle Downloader

Downloads every file, folder, page, link and video (Moodle-hosted and YouTube)
from all your EPFL Moodle courses, sorted as

    <your folder>\<Course name>\<NN - Week / section name>\...

Each run only downloads what is new or changed since the last run.

## Use

1. Double-click `EPFL-Moodle-Downloader.exe`.
2. First run asks for your EPFL username, password (stored in Windows
   Credential Manager) and the folder to save into, then offers to run
   automatically every Monday at 12:00 (or at next start-up if the PC was off).
3. That's it. Run it again anytime to fetch the latest files.

Options (run from a terminal):

| Option | What it does |
|---|---|
| `--setup` | change username, password or folder |
| `--schedule FRI --at 18:00` | change the weekly day/time |
| `--unschedule` | stop the weekly run |
| `--course "Analyse"` | only courses whose name contains the text |
| `--no-videos` | skip videos |
| `--show-browser` | watch the login happen (for troubleshooting) |

A log of every run is in `<your folder>\.moodle-downloader\log.txt`.

## How sign-in works

EPFL accounts use single sign-on, so the tool opens Moodle's "mobile app"
login in a hidden Microsoft Edge window, fills in your saved credentials, and
receives a Moodle access token (the same way the official Moodle app does).
The token is reused until it expires. If the automatic sign-in gets stuck, a
visible window opens so you can finish it yourself.

## Videos

Any video it can find is downloaded: videos uploaded to Moodle, YouTube, and
links or embedded players from about 1800 other sites (Vimeo, Zoom
recordings, SwitchTube, direct .mp4 links, ...). Moodle links to other pages
are tried too; if a page has no video, a shortcut (.url) to it is saved.
Videos are saved up to 1080p (ffmpeg is built in).

Anything that could not be downloaded is listed at the end of each run and in
`<your folder>\_Could not download.html`, with the course, section, link and
reason. Those items are retried on the next run.

## Build the .exe

Install Python 3.10+ from python.org, then double-click `build.bat`.
