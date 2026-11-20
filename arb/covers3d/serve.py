"""Страница 3D-обложек: отдаёт файлы этой папки и сохраняет готовые PNG в data/cards3d."""

from __future__ import annotations

import re
import os
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE.parent.parent / "data" / "cards3d"


def save_cover(out: Path, name: str, body: bytes) -> bool:
    """Готовый кэш не заменяем, даже если рендер стартовал до его установки."""
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=out, prefix='.render-', suffix='.tmp', delete=False) as stream:
        staging = Path(stream.name)
        stream.write(body)
    try:
        staging.chmod(0o644)
        try:
            os.link(staging, out / f'{name}.png')
        except FileExistsError:
            return False
        return True
    finally:
        staging.unlink(missing_ok=True)


class Handler(SimpleHTTPRequestHandler):
    out = OUT
    saved: list[str] = []    # имена сохранённых PNG — по ним бот понимает, что отрисовка готова
    failed: list[str] = []   # ошибки страницы

    def log_message(self, *args):
        pass

    def __init__(self, *args, **kw):
        super().__init__(*args, directory=str(HERE), **kw)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def translate_path(self, path):
        name = path.split("?")[0]
        if name.startswith("/cards/"):
            return str(self.out / re.sub(r"[^\w.-]", "_", name.rsplit("/", 1)[-1]))
        return super().translate_path(path)

    def do_OPTIONS(self):
        # Браузер спрашивает разрешение, прежде чем пустить публичный сайт на локальный адрес.
        self.send_response(204)
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Methods", "GET")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.startswith("/fail/"):
            type(self).failed.append(body.decode("utf-8", "replace")[:500])
        else:
            name = re.sub(r"[^\w.-]", "_", self.path.rsplit("/", 1)[-1])
            save_cover(self.out, name, body)
            type(self).saved.append(name)
        self.send_response(204)
        self.end_headers()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8091), Handler).serve_forever()
