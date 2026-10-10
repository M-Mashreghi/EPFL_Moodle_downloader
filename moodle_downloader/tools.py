"""Helpers the video downloader needs: ffmpeg and a JavaScript runtime.

ffmpeg ships inside the .exe (imageio-ffmpeg). YouTube now needs a
JavaScript runtime to unlock most formats; we use Deno, Node or Bun if one is
installed, otherwise download Deno once into the app folder.
"""
import io
import os
import shutil
import sys
import zipfile

import requests

from .config import app_dir

DENO_ZIP = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"

_ffmpeg = None
_runtimes = None


def ffmpeg_path():
    global _ffmpeg
    if _ffmpeg is None:
        try:
            import imageio_ffmpeg
            _ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            _ffmpeg = shutil.which("ffmpeg") or ""
    return _ffmpeg or None


def js_runtimes(log=print) -> dict:
    global _runtimes
    if _runtimes is not None:
        return _runtimes
    found = {}
    for name in ("deno", "node", "bun"):
        path = shutil.which(name)
        if path:
            found[name] = {"path": path}
    local_deno = app_dir() / ("deno.exe" if os.name == "nt" else "deno")
    if not found and local_deno.exists():
        found["deno"] = {"path": str(local_deno)}
    if not found and sys.platform == "win32":
        try:
            log("    (one-time setup: downloading Deno, which YouTube downloads need...)")
            r = requests.get(DENO_ZIP, timeout=300)
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                with z.open("deno.exe") as src, open(local_deno, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            found["deno"] = {"path": str(local_deno)}
        except Exception as e:
            log(f"    ! could not set up Deno ({e}); some YouTube videos may fail.")
    _runtimes = found
    return found
