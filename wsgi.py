"""Hosted adapter for PythonAnywhere; uses the same endpoints as app.py."""
import io
import json
import logging
import os
from email.message import Message
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from app import RequestHandler, ROOT
from database import initialize


class WSGIRequest(RequestHandler):
    def __init__(self, environ, runtime):
        self.server = runtime
        self.path = environ.get("PATH_INFO", "/")
        self.headers = Message()
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                self.headers[key[5:].replace("_", "-")] = value
        for key in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            if environ.get(key):
                self.headers[key.replace("_", "-")] = environ[key]
        self.rfile = environ.get("wsgi.input", io.BytesIO())
        self.status = 500
        self.body = b""
        self.response_headers = []

    def send(self, body, status=200, content_type="application/json; charset=utf-8", headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.status = status
        self.body = body
        self.response_headers = [
            ("Content-Type", content_type), ("Content-Length", str(len(body))),
            ("X-Content-Type-Options", "nosniff"), ("Cache-Control", "no-store"),
            ("Referrer-Policy", "same-origin"),
            ("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"),
            *(headers or {}).items(),
        ]


def create_application(db_path, public_origin, *, demo=True):
    """Build a WSGI app without opening a socket or launching a browser."""
    parsed = urlsplit(public_origin)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.path
            or parsed.query or parsed.fragment or "*" in public_origin):
        raise ValueError("Укажите точный адрес сайта без пути: https://имя.pythonanywhere.com")
    public_origin = f"{parsed.scheme}://{parsed.netloc.lower()}"
    initialize(db_path, demo=demo)
    runtime = SimpleNamespace(db_path=str(db_path), public_origin=public_origin)

    def application(environ, start_response):
        request = WSGIRequest(environ, runtime)
        method = environ.get("REQUEST_METHOD", "GET")
        try:
            if method in ("GET", "HEAD"):
                request.do_GET()
            elif method in ("POST", "PATCH"):
                request.mutate(method)
            else:
                request.send({"error": "Метод не поддерживается."}, 405,
                             headers={"Allow": "GET, HEAD, POST, PATCH"})
        except Exception:
            logging.exception("Admin Assist request failed")
            request.send({"error": "Не удалось обработать запрос. Повторите попытку."}, 500)
        start_response(f"{request.status} {HTTPStatus(request.status).phrase}", request.response_headers)
        return [b"" if method == "HEAD" else request.body]

    return application


def from_environment():
    """Explicit host; separate hosted database, never the local working database."""
    host = os.environ.get("ADMIN_ASSIST_HOST", "").strip().lower()
    if not host or any(char in host for char in "/:@?# "):
        raise ValueError("Задайте ADMIN_ASSIST_HOST: имя.pythonanywhere.com")
    db_path = Path(os.environ.get("ADMIN_ASSIST_DB_PATH", ROOT / "data" / "hosted.sqlite3"))
    return create_application(db_path, f"https://{host}")
