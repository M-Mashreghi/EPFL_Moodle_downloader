"""Walks every course and downloads files, folders, pages, links and videos.

Layout:  <destination>/<Course name>/<NN - Section name>/<files>
A state file in <destination>/.moodle-downloader/ remembers what was already
downloaded, so each run only fetches new or changed items.
"""
import html
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests

from .api import MoodleClient, MoodleError
from .config import SITE
from .tools import ffmpeg_path, js_runtimes

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

YOUTUBE_RE = re.compile(
    r"(?:https?:)?//(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:[^\"'<>\s]*&)?v=|embed/|shorts/|live/)"
    r"|youtube-nocookie\.com/embed/|youtu\.be/)([A-Za-z0-9_-]{11})")
PLUGINFILE_RE = re.compile(re.escape(SITE) + r"/(?:webservice/)?pluginfile\.php/[^\s\"'<>]+")
LINK_RE = re.compile(r"""(?:href|src|data-src)\s*=\s*["'](https?://[^"'<>\s]+)["']""", re.I)
IFRAME_RE = re.compile(r"""<iframe[^>]+?src\s*=\s*["'](https?://[^"'<>\s]+)["']""", re.I)
MEDIA_EXT = {".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi", ".wmv", ".flv", ".ogv",
             ".mpg", ".mpeg", ".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac"}
# yt-dlp errors that just mean "this page has no video", not a real failure.
NO_VIDEO_RE = re.compile(r"Unsupported URL|No video formats found|does not contain|not a video|"
                         r"no suitable|Unable to extract", re.I)

SKIP_MODULES = {"forum", "quiz", "choice", "feedback", "chat", "survey", "lti", "workshop",
                "data", "glossary", "wiki", "attendance", "questionnaire", "zoom", "bigbluebuttonbn"}


def safe_name(name: str, limit: int = 80) -> str:
    name = html.unescape(name or "").strip()
    name = name.replace(": ", " - ").replace(" / ", " - ").replace("/", "-")
    name = INVALID.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > limit:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 8:
            name = stem[: limit - len(ext) - 1].rstrip(" .") + "." + ext
        else:
            name = name[:limit].rstrip(" .")
    if name.split(".")[0].upper() in RESERVED:
        name = "_" + name
    return name or "untitled"


def strip_token(url: str) -> str:
    return re.sub(r"[?&]token=[^&]*", "", url)


def is_media_file(url: str) -> bool:
    return Path(urlparse(url).path).suffix.lower() in MEDIA_EXT


_extractors = None


def is_video_site(url: str) -> bool:
    """True when yt-dlp has a dedicated extractor for this link (YouTube,
    Vimeo, SwitchTube, Kaltura, Zoom, Panopto, ~1800 sites in total)."""
    global _extractors
    if _extractors is None:
        try:
            from yt_dlp.extractor import gen_extractor_classes
            _extractors = [ie for ie in gen_extractor_classes()
                           if ie.ie_key() != "Generic" and ie.working()]
        except ImportError:
            _extractors = []
    return any(ie.suitable(url) for ie in _extractors)


def short_error(e) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "").strip()
    msg = msg.split("; please report")[0].split("\n")[0]
    msg = re.sub(r"^\[[\w:]+\] [\w-]+: ", "", msg)  # "[youtube] abc123: "
    msg = re.sub(r" \(caused by .*$", "", msg)
    return msg[:300]


class _QuietLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class State:
    def __init__(self, dest: Path):
        self.dir = dest / ".moodle-downloader"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "state.json"
        try:
            self.items = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.items = {}

    @staticmethod
    def _norm(version):
        return json.loads(json.dumps(version))

    def done(self, key: str, version) -> bool:
        version = self._norm(version)
        item = self.items.get(key)
        if not item or item.get("version") != version:
            return False
        path = item.get("path")
        return not path or Path(path).exists()

    def mark(self, key: str, version, path) -> None:
        self.items[key] = {"version": self._norm(version), "path": str(path) if path else None,
                           "at": time.strftime("%Y-%m-%d %H:%M")}

    def path_for(self, key: str):
        item = self.items.get(key)
        return Path(item["path"]) if item and item.get("path") else None

    def save(self) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.file)


class Downloader:
    def __init__(self, client: MoodleClient, dest: Path, log=print, videos: bool = True):
        self.client = client
        self.dest = Path(dest)
        self.log = log
        self.videos = videos
        self.state = State(self.dest)
        self.stats = {"new": 0, "updated": 0, "videos": 0, "links": 0, "failed": 0}
        self.claimed = {}  # path -> key, to avoid two items overwriting one file
        self.where = ("", "", "")  # current (course, section, item), for the failure report
        self.failures = {}  # url -> (course, section, name, reason)
        self.tried = set()  # video keys attempted in this run

    def fail(self, url: str, name: str, reason: str) -> None:
        url = strip_token(url)
        if url in self.failures:
            return
        self.stats["failed"] += 1
        name = name or self.where[2] or "item"
        self.failures[url] = (self.where[0], self.where[1], name, reason)
        self.log(f"    ! could not download {name}: {reason}\n      {url}")

    # ---- helpers -------------------------------------------------------
    def _unique_path(self, path: Path, key: str) -> Path:
        previous = self.state.path_for(key)
        if previous and previous.parent == path.parent:
            return previous
        candidate, n = path, 2
        while True:
            owner = self.claimed.get(str(candidate).lower())
            taken_on_disk = candidate.exists() and not self._owned_by_us(candidate, key)
            if (owner is None or owner == key) and not taken_on_disk:
                break
            candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
            n += 1
        self.claimed[str(candidate).lower()] = key
        return candidate

    def _owned_by_us(self, path: Path, key: str) -> bool:
        p = self.state.path_for(key)
        if p and p == path:
            return True
        # A file we downloaded under another key is someone else's; an
        # unknown file already on disk (e.g. from an earlier run whose state
        # was lost) is treated as ours and overwritten with the same content.
        return not any(v.get("path") == str(path) for v in self.state.items.values())

    def download_file(self, url: str, folder: Path, filename: str, version) -> None:
        key = strip_token(url)
        if self.state.done(key, version):
            return
        if key in self.failures:
            return
        existed = key in self.state.items
        folder.mkdir(parents=True, exist_ok=True)
        target = self._unique_path(folder / safe_name(filename, 120), key)
        part = target.with_name(target.name + ".part")
        try:
            with self.client.session.get(self.client.file_url(url), stream=True, timeout=120) as r:
                r.raise_for_status()
                ctype = r.headers.get("content-type", "")
                if "application/json" in ctype:
                    raise MoodleError(r.text[:200])
                with open(part, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)
            part.replace(target)
        except Exception as e:
            self.fail(url, filename, short_error(e))
            part.unlink(missing_ok=True)
            return
        self.state.mark(key, version, target)
        self.stats["updated" if existed else "new"] += 1
        self.log(f"    {'~' if existed else '+'} {target.relative_to(self.dest)}")

    def save_link(self, url: str, folder: Path, name: str) -> None:
        key = "link:" + url
        if self.state.done(key, 1):
            return
        folder.mkdir(parents=True, exist_ok=True)
        target = self._unique_path(folder / (safe_name(name, 100) + ".url"), key)
        target.write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")
        self.state.mark(key, 1, target)
        self.stats["links"] += 1
        self.log(f"    + {target.relative_to(self.dest)}")

    def download_direct(self, url: str, folder: Path) -> None:
        """A plain link to a video/audio file on another website."""
        key = "direct:" + url
        if not self.videos or self.state.done(key, 1):
            return
        folder.mkdir(parents=True, exist_ok=True)
        name = unquote(urlparse(url).path.rsplit("/", 1)[-1]) or "video"
        target = self._unique_path(folder / safe_name(name, 120), key)
        part = target.with_name(target.name + ".part")
        self.log(f"    downloading video {url}")
        try:
            with requests.get(url, stream=True, timeout=120,
                              headers={"User-Agent": "Mozilla/5.0"}) as r:
                r.raise_for_status()
                with open(part, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)
            part.replace(target)
        except Exception as e:
            part.unlink(missing_ok=True)
            self.fail(url, None, short_error(e))
            return
        self.state.mark(key, 1, target)
        self.stats["videos"] += 1
        self.log(f"    + {target.relative_to(self.dest)}")

    def download_video(self, url: str, folder: Path, name: str = None, probe: bool = False) -> str:
        """Download with yt-dlp. Returns "ok", "skipped", "novideo" or "failed".

        probe=True is for links that may or may not contain a video: when
        yt-dlp finds none, that is not reported as a failure."""
        if not self.videos:
            return "skipped"
        m = YOUTUBE_RE.search(url)
        if m:
            url = f"https://www.youtube.com/watch?v={m.group(1)}"
        key = f"yt:{m.group(1)}" if m else "video:" + url
        if self.state.done(key, 1):
            return "ok"
        if key in self.tried:
            return "failed"
        self.tried.add(key)
        if probe and self.state.done("novideo:" + url, 1):
            return "novideo"
        try:
            from yt_dlp import YoutubeDL
        except ImportError:
            self.log("    ! yt-dlp is not installed, skipping video " + url)
            return "skipped"
        ffmpeg = ffmpeg_path()
        opts = {
            # Without ffmpeg, only single-file formats can be saved (often 360p on YouTube).
            "format": "bv*[height<=1080]+ba/b" if ffmpeg else "b[ext=mp4]/b",
            "outtmpl": str(folder / ((safe_name(name, 80).replace("%", "%%") if name else "%(title).80B")
                                     + " [%(id)s].%(ext)s")),
            "quiet": True, "no_warnings": True, "noprogress": True, "logger": _QuietLogger(),
            "noplaylist": True, "windowsfilenames": True,
            "merge_output_format": "mp4",
            "js_runtimes": js_runtimes(self.log),
            "remote_components": ["ejs:github"],
            "retries": 5, "fragment_retries": 5,
        }
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
        if not probe:
            self.log(f"    downloading video {url}")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    raise RuntimeError("no video found")
                if info.get("_type") == "playlist":
                    entries = [e for e in info.get("entries") or [] if e]
                    if not entries:
                        raise RuntimeError("No video formats found")
                    info = entries[0]
                path = ydl.prepare_filename(info)
                if not Path(path).exists():
                    path = str(Path(path).with_suffix(".mp4"))
        except Exception as e:
            reason = short_error(e)
            if probe and (NO_VIDEO_RE.search(reason) or re.search(r"HTTP Error 4\d\d|Unable to download webpage", reason)):
                self.state.mark("novideo:" + url, 1, None)
                return "novideo"
            self.fail(url, name, reason)
            return "failed"
        self.state.mark(key, 1, path if Path(path).exists() else None)
        self.stats["videos"] += 1
        self.log(f"    + {Path(path).name}")
        return "ok"

    def from_html(self, text: str, folder: Path) -> None:
        """Videos and files embedded in descriptions, labels and pages."""
        if not text:
            return
        text = html.unescape(text)
        done = set()
        for m in YOUTUBE_RE.finditer(text):
            if m.group(1) not in done:
                done.add(m.group(1))
                self.download_video(m.group(0), folder)
        for m in PLUGINFILE_RE.finditer(text):
            url = m.group(0).split("#")[0]
            if url not in done:
                done.add(url)
                name = unquote(urlparse(url).path.rsplit("/", 1)[-1]) or "file"
                self.download_file(url, folder, name, version="embedded")
        iframes = {u for u in IFRAME_RE.findall(text)}
        for url in LINK_RE.findall(text):
            url = url.split("#")[0]
            if url in done or url.startswith(SITE) or YOUTUBE_RE.search(url):
                continue
            done.add(url)
            if is_media_file(url):
                self.download_direct(url, folder)
            elif is_video_site(url):
                self.download_video(url, folder)
            elif url in iframes:
                # An embedded player we don't know: try it, quietly.
                self.download_video(url, folder, probe=True)

    # ---- modules -------------------------------------------------------
    def handle_files(self, contents, folder: Path) -> None:
        for c in contents or []:
            if c.get("type", "file") != "file" or not c.get("fileurl"):
                continue
            sub = folder
            for part in (c.get("filepath") or "/").strip("/").split("/"):
                if part:
                    sub = sub / safe_name(part)
            self.download_file(c["fileurl"], sub, c.get("filename") or "file",
                               (c.get("timemodified"), c.get("filesize")))

    def handle_module(self, mod: dict, section_dir: Path, assignments: dict) -> None:
        kind = mod.get("modname")
        name = mod.get("name") or kind
        if mod.get("uservisible") is False or kind in SKIP_MODULES:
            return
        contents = mod.get("contents") or []
        description = mod.get("description") or ""

        if kind == "resource":
            self.handle_files(contents, section_dir)
            self.from_html(description, section_dir)
        elif kind == "folder":
            self.handle_files(contents, section_dir / safe_name(name))
        elif kind == "url":
            for c in contents:
                link = c.get("fileurl")
                if not link:
                    continue
                if link.startswith(SITE):
                    if "pluginfile.php" in link:
                        self.from_html(link, section_dir)
                    else:
                        self.save_link(link, section_dir, name)
                elif is_media_file(link):
                    self.download_direct(link, section_dir)
                else:
                    # Any external link might hold a video: let yt-dlp try,
                    # and keep a shortcut whenever no video was saved.
                    known = YOUTUBE_RE.search(link) or is_video_site(link)
                    suffix = Path(urlparse(link).path).suffix.lower()
                    if not known and suffix not in ("", ".html", ".htm", ".php", ".aspx", ".jsp"):
                        result = "novideo"  # a document link, e.g. .pdf
                    else:
                        result = self.download_video(link, section_dir, name=name, probe=not known)
                    if result != "ok":
                        self.save_link(link, section_dir, name)
        elif kind == "page":
            page_dir = section_dir / safe_name(name)
            for c in contents:
                if c.get("filename") == "index.html" and c.get("fileurl"):
                    self.download_file(c["fileurl"], page_dir, safe_name(name) + ".html",
                                       (c.get("timemodified"), c.get("filesize")))
                    self.page_videos(c["fileurl"], page_dir, c.get("timemodified"))
            self.handle_files([c for c in contents if c.get("filename") != "index.html"], page_dir)
            self.from_html(description, page_dir)
        elif kind == "label":
            self.from_html(description, section_dir)
        elif kind == "assign":
            a = assignments.get(mod.get("id"), {})
            adir = section_dir / safe_name(name)
            self.handle_files(a.get("introattachments"), adir)
            self.handle_files(contents, adir)
            self.from_html(a.get("intro") or description, adir)
        else:
            # Anything else that exposes files (e.g. video plugins, books).
            if any(c.get("type") == "file" for c in contents):
                self.handle_files(contents, section_dir / safe_name(name))
            self.from_html(description, section_dir)

    def page_videos(self, url: str, folder: Path, version) -> None:
        key = "pagescan:" + strip_token(url)
        if self.state.done(key, version):
            return
        try:
            r = self.client.session.get(self.client.file_url(url), timeout=60)
            r.raise_for_status()
            self.from_html(r.text, folder)
            self.state.mark(key, version, None)
        except Exception as e:
            self.log(f"    ! could not read page {url}: {e}")

    # ---- top level -----------------------------------------------------
    def run(self, only=None) -> dict:
        info = self.client.site_info()
        self.log(f"Signed in as {info.get('fullname')}.")
        courses = self.client.courses(info["userid"])
        courses.sort(key=lambda c: c.get("fullname", ""))
        self.log(f"Found {len(courses)} courses.\n")
        for course in courses:
            title = course.get("fullname") or course.get("shortname") or str(course["id"])
            if only and not any(o.lower() in title.lower() for o in only):
                continue
            self.log(f"[{title}]")
            self.where = (title, "", "")
            course_dir = self.dest / safe_name(title, 70)
            try:
                sections = self.client.course_contents(course["id"])
                assignments = self.client.assignments(course["id"])
            except MoodleError as e:
                self.fail(f"{SITE}/course/view.php?id={course['id']}", title, f"could not read course: {e}")
                continue
            for i, section in enumerate(sections):
                number = section.get("section", i)
                sname = section.get("name") or ("General" if number == 0 else f"Week {number}")
                section_dir = course_dir / safe_name(f"{number:02d} - {sname}", 70)
                self.where = (title, sname, "Section description")
                self.from_html(section.get("summary"), section_dir)
                for mod in section.get("modules", []):
                    self.where = (title, sname, mod.get("name") or "")
                    try:
                        self.handle_module(mod, section_dir, assignments)
                    except Exception as e:
                        self.fail(mod.get("url") or f"{SITE}/course/view.php?id={course['id']}",
                                  mod.get("name") or "item", short_error(e))
                self.state.save()
        self.state.save()
        self.write_report()
        return self.stats

    REPORT = "_Could not download.html"

    def write_report(self) -> None:
        report = self.dest / self.REPORT
        if not self.failures:
            report.unlink(missing_ok=True)
            return
        self.log(f"\nCould not download {len(self.failures)} item(s):")
        rows = []
        for url, (course, section, name, reason) in sorted(self.failures.items(), key=lambda kv: kv[1][:3]):
            self.log(f"  - {course} / {section} / {name}\n      {url}\n      reason: {reason}")
            e = html.escape
            rows.append(f"<tr><td>{e(course)}</td><td>{e(section)}</td><td>{e(name)}</td>"
                        f"<td><a href=\"{e(url)}\">{e(url)}</a></td><td>{e(reason)}</td></tr>")
        report.write_text(
            "<!doctype html><meta charset=utf-8><title>Could not download</title>"
            "<style>body{font-family:Segoe UI,sans-serif;margin:24px}table{border-collapse:collapse}"
            "td,th{border:1px solid #ccc;padding:6px 8px;text-align:left;vertical-align:top}"
            "td:nth-child(4){word-break:break-all;max-width:420px}</style>"
            f"<h2>Could not download ({len(self.failures)})</h2>"
            f"<p>Last run: {time.strftime('%Y-%m-%d %H:%M')}. These are retried on every run.</p>"
            "<table><tr><th>Course</th><th>Section</th><th>Item</th><th>Link</th><th>Reason</th></tr>"
            + "".join(rows) + "</table>", encoding="utf-8")
        self.log(f"\nThe list is also saved in {report}")
