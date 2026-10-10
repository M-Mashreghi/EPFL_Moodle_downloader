"""Entry point: first-run setup, login, download, weekly schedule."""
import argparse
import getpass
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config
from .api import MoodleClient, InvalidToken
from .auth import LoginError, token_via_browser, token_via_password
from .downloader import Downloader

TASK_NAME = "EPFL Moodle Downloader"


class Logger:
    def __init__(self):
        self.file = None

    def open(self, dest: Path):
        d = dest / ".moodle-downloader"
        d.mkdir(parents=True, exist_ok=True)
        self.file = open(d / "log.txt", "a", encoding="utf-8")
        self.file.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")

    def __call__(self, msg=""):
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            print(msg.encode("ascii", "replace").decode(), flush=True)
        if self.file:
            self.file.write(msg + "\n")
            self.file.flush()


log = Logger()


def ask_folder(current=None) -> str:
    print("\nChoose the folder where your courses will be saved.")
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Where should Moodle files be saved?",
                                       initialdir=current or str(Path.home()))
        root.destroy()
        if path:
            print(f"Folder: {path}")
            return str(Path(path))
    except Exception:
        pass
    while True:
        path = input(f"Folder path{f' [{current}]' if current else ''}: ").strip().strip('"') or current
        if path:
            Path(path).mkdir(parents=True, exist_ok=True)
            return str(Path(path))


def setup(cfg: dict) -> dict:
    print(f"=== {config.APP_NAME}: setup ===")
    print("Your password is stored in Windows Credential Manager, never in a plain file.\n")
    default_user = cfg.get("username", "")
    username = input(f"EPFL username (e.g. jdoe){f' [{default_user}]' if default_user else ''}: ").strip() or default_user
    password = getpass.getpass("EPFL password (hidden while typing): ")
    cfg["username"] = username
    config.set_password(username, password)
    config.clear_token()
    cfg["destination"] = ask_folder(cfg.get("destination"))
    ans = input("\nDownload YouTube and other videos too? [Y/n]: ").strip().lower()
    cfg["videos"] = ans not in ("n", "no")
    config.save_config(cfg)
    return cfg


def get_client(cfg: dict, show_browser: bool = False) -> MoodleClient:
    token = config.get_token()
    if token:
        client = MoodleClient(token)
        try:
            client.site_info()
            return client
        except InvalidToken:
            log("Saved login expired, signing in again...")
            config.clear_token()

    username = cfg["username"]
    password = config.get_password(username)
    log("Signing in to EPFL Moodle...")
    token = token_via_password(username, password)
    if not token:
        try:
            token = token_via_browser(username, password, headless=not show_browser, log=log)
        except LoginError as e:
            if show_browser:
                raise
            log(f"Automatic sign-in did not work ({e}).")
            log("Opening a browser window: finish signing in there if it asks you anything.")
            token = token_via_browser(username, password, headless=False, timeout=300, log=log)
    client = MoodleClient(token)
    client.site_info()  # raises if the token is bad
    config.set_token(token)
    return client


def install_schedule(day: str = "MON", at: str = "12:00") -> None:
    exe = sys.executable
    args = "--auto"
    if not getattr(sys, "frozen", False):
        args = "-m moodle_downloader --auto"
    if getattr(sys, "frozen", False):
        workdir = str(Path(sys.executable).parent)
    else:
        workdir = str(Path(__file__).resolve().parent.parent)
    days = {"MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday", "THU": "Thursday",
            "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday"}
    start = time.strftime("%Y-%m-%d") + f"T{at}:00"
    # StartWhenAvailable: if the PC was off at that time, run at next start-up.
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Weekly download of new EPFL Moodle files</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek><DaysOfWeek><{days[day]} /></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT12H</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{exe}</Command><Arguments>{args}</Arguments><WorkingDirectory>{workdir}</WorkingDirectory></Exec>
  </Actions>
</Task>"""
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as f:
        f.write(xml)
        xml_path = f.name
    result = subprocess.run(["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/XML", xml_path],
                            capture_output=True, text=True)
    Path(xml_path).unlink(missing_ok=True)
    if result.returncode == 0:
        print(f"Scheduled: runs every {days[day]} at {at} "
              "(or at the next start-up if the PC was off).")
    else:
        print("Could not create the weekly task:", (result.stderr or result.stdout).strip())


def remove_schedule() -> None:
    r = subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME], capture_output=True, text=True)
    print("Weekly task removed." if r.returncode == 0 else (r.stderr or r.stdout).strip())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="EPFL-Moodle-Downloader",
                                description="Download all files and videos from your EPFL Moodle courses.")
    p.add_argument("--setup", action="store_true", help="change username, password or folder")
    p.add_argument("--auto", action="store_true", help="run without questions (used by the weekly task)")
    p.add_argument("--schedule", nargs="?", const="MON", metavar="DAY",
                   help="run automatically every week (MON..SUN, default MON)")
    p.add_argument("--at", default="12:00", help="time for --schedule, e.g. 18:30")
    p.add_argument("--unschedule", action="store_true", help="remove the weekly task")
    p.add_argument("--course", action="append", help="only courses whose name contains this text")
    p.add_argument("--no-videos", action="store_true", help="skip YouTube and other videos")
    p.add_argument("--show-browser", action="store_true", help="show the login browser window")
    args = p.parse_args(argv)

    interactive = not args.auto
    cfg = config.load_config()

    try:
        if args.unschedule:
            remove_schedule()
            return 0
        if args.schedule:
            install_schedule(args.schedule.upper()[:3], args.at)
            return 0

        first_run = not config.is_configured(cfg)
        if args.setup or first_run:
            if not interactive:
                print("Not set up yet. Run the program once by double-clicking it.")
                return 2
            cfg = setup(cfg)

        dest = Path(cfg["destination"])
        dest.mkdir(parents=True, exist_ok=True)
        log.open(dest)
        client = get_client(cfg, show_browser=args.show_browser)

        if first_run and interactive:
            ans = input("\nRun automatically every week (Monday 12:00)? [Y/n]: ").strip().lower()
            if ans not in ("n", "no"):
                install_schedule()
            print()

        videos = cfg.get("videos", True) and not args.no_videos
        stats = Downloader(client, dest, log=log, videos=videos).run(only=args.course)
        log(f"\nDone: {stats['new']} new files, {stats['updated']} updated, "
            f"{stats['videos']} videos, {stats['links']} links, {stats['failed']} failed.")
        log(f"Saved in {dest}")
        return 0 if stats["failed"] == 0 else 1
    except KeyboardInterrupt:
        log("\nStopped.")
        return 130
    except Exception as e:
        log(f"\nError: {e}")
        return 1
    finally:
        if interactive and getattr(sys, "frozen", False):
            input("\nPress Enter to close...")
