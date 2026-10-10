"""Settings file and Windows Credential Manager storage."""
import json
import os
from pathlib import Path

import keyring

APP_NAME = "EPFL Moodle Downloader"
SITE = os.environ.get("MOODLE_SITE", "https://moodle.epfl.ch").rstrip("/")
KEYRING_SERVICE = "epfl-moodle-downloader"
TOKEN_KEY = "__moodle_token__"


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "EPFLMoodleDownloader"
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_FILE = app_dir() / "config.json"


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def is_configured(cfg: dict) -> bool:
    return bool(cfg.get("username") and cfg.get("destination") and get_password(cfg["username"]))


def get_password(username: str):
    return keyring.get_password(KEYRING_SERVICE, username)


def set_password(username: str, password: str) -> None:
    keyring.set_password(KEYRING_SERVICE, username, password)


def get_token():
    return keyring.get_password(KEYRING_SERVICE, TOKEN_KEY)


def set_token(token: str) -> None:
    keyring.set_password(KEYRING_SERVICE, TOKEN_KEY, token)


def clear_token() -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, TOKEN_KEY)
    except keyring.errors.PasswordDeleteError:
        pass
