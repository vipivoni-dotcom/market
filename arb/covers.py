"""Бот сам рисует недостающую 3D-обложку: открывает arb/covers3d в Chrome без окна.

Страница строит обложку по ключу товара (?key=google_play:1500TRY) и присылает PNG
обратно локальному серверу, который кладёт его в папку обложек.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
import shutil
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger(__name__)

HERE = Path(__file__).parent / "covers3d"
# Chrome первым: Edge в режиме без окна на этом компьютере сразу закрывается, ничего не открыв.
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
# Несколько отрисовок сразу (каждая — отдельный Chrome без окна); одну и ту же обложку дважды не рисуем.
_slots: asyncio.Semaphore | None = None
_key_locks: dict[str, asyncio.Lock] = {}


def _handler_class():
    spec = importlib.util.spec_from_file_location("covers3d_serve", HERE / "serve.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Handler


def find_browser(configured: str | None = None) -> str | None:
    for path in ([configured] if configured else []) + BROWSERS:
        if path and Path(path).exists():
            return path
    return shutil.which("msedge") or shutil.which("chrome")


async def render_cover(key: str, out_dir: Path, browser: str | None = None, timeout: float = 300,
                       parallel: int = 3) -> Path:
    """Нарисовать обложку товара и вернуть путь к PNG. Ошибки — исключением с понятным текстом."""
    exe = find_browser(browser)
    if not exe:
        raise RuntimeError("не найден Chrome или Edge для отрисовки обложки")
    global _slots
    if _slots is None:
        # На VPS WebGL программный: три Chrome забирали почти всю память и CPU.
        _slots = asyncio.Semaphore(1 if sys.platform == "linux" else max(1, parallel))
    async with _key_locks.setdefault(key, asyncio.Lock()), _slots:
        base = _handler_class()
        handler = type("CoverHandler", (base,), {"out": Path(out_dir), "saved": [], "failed": []})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        profile = tempfile.mkdtemp(prefix="covers3d-")
        url = f"http://127.0.0.1:{server.server_port}/index.html?key={quote(key)}"
        proc = await asyncio.create_subprocess_exec(
            exe, "--headless=new", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader",
            "--window-size=1300,1000", "--remote-debugging-port=0", url,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while not handler.saved and not handler.failed:
                if loop.time() > deadline:
                    raise RuntimeError(f"обложка {key} не отрисовалась за {timeout:.0f} с")
                if proc.returncode is not None:
                    raise RuntimeError(f"браузер закрылся, не отрисовав обложку {key}")
                await asyncio.sleep(1)
            if handler.failed:
                raise RuntimeError(f"обложка {key}: {handler.failed[0]}")
            path = Path(out_dir) / f"{handler.saved[0]}.png"
            log.info("обложка %s отрисована: %s", key, path.name)
            return path
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            server.shutdown()
            server.server_close()
            await asyncio.sleep(0.5)
            shutil.rmtree(profile, ignore_errors=True)
