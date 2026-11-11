"""Admin Assist HTTP API and local server. Python 3.10+, standard library only."""
import argparse
import csv
import io
import json
import mimetypes
import sqlite3
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from database import connect, initialize, articles, incident_dict, create_incident, now
from domain import analyze, validate_incident, validate_article, STATUSES, PRIORITIES, IMPACTS, URGENCIES, CATEGORIES
from investigation import view as investigation_view, mutate as investigation_mutate, InvestigationError

ROOT = Path(__file__).resolve().parent


class ApplicationServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, db_path):
        self.db_path = db_path
        super().__init__(address, Handler)


class RequestHandler:
    """Application endpoints shared by the local HTTP and hosted WSGI adapters."""
    def log_message(self, fmt, *args):
        pass

    def send(self, body, status=200, content_type="application/json; charset=utf-8", headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Ожидается запрос JSON.")
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 65536:
            raise ValueError("Недопустимый размер запроса.")
        try:
            data = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Не удалось прочитать данные запроса.")
        if not isinstance(data, dict):
            raise ValueError("Ожидается объект с полями.")
        return data

    def allowed(self):
        host = self.headers.get("Host", "").lower()
        public_origin = getattr(self.server, "public_origin", None)
        if public_origin:
            hosts = (urlsplit(public_origin).netloc.lower(),)
            origins = (public_origin,)
        else:
            hosts = (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")
            origins = tuple(f"http://{name}" for name in hosts)
        if host not in hosts:
            self.send({"error": "Недопустимый адрес сайта."}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in origins:
            self.send({"error": "Запрос с другого сайта отклонён."}, 403)
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        path = urlsplit(self.path).path
        try:
            with connect(self.server.db_path) as db:
                if path == "/api/bootstrap":
                    incidents = [incident_dict(row) for row in db.execute("SELECT * FROM incidents ORDER BY created_at DESC, id DESC")]
                    self.send({"incidents": incidents, "articles": articles(db), "statuses": STATUSES, "priorities": PRIORITIES,
                               "impacts": IMPACTS, "urgencies": URGENCIES, "categories": {**{c[0]: c[1] for c in CATEGORIES}, "general": "Прочие обращения"},
                               "environment": {"public": bool(getattr(self.server, "public_origin", None))}})
                elif path.startswith("/api/incidents/"):
                    incident_id = self.get_id(path)
                    row = db.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
                    if not row:
                        self.send({"error": "Инцидент не найден."}, 404)
                        return
                    self.send({"incident": incident_dict(row), "events": [dict(r) for r in db.execute("SELECT * FROM events WHERE incident_id=? ORDER BY id", (incident_id,))], "investigation": investigation_view(db, row)})
                elif path == "/api/export":
                    output = io.StringIO(newline="")
                    writer = csv.writer(output, delimiter=";")
                    writer.writerow(["Номер", "Название", "Описание", "Сервис", "Статус", "Приоритет", "Категория", "Влияние", "Срочность", "Создан", "Решён", "Решение", "Демо"])
                    for row in db.execute("SELECT * FROM incidents ORDER BY id"):
                        values = [row["id"], row["title"], row["description"], row["service"], STATUSES[row["status"]], PRIORITIES[row["priority"]], json.loads(row["analysis"])["category_label"], IMPACTS[row["impact"]], URGENCIES[row["urgency"]], row["created_at"], row["resolved_at"] or "", row["resolution"], "Да" if row["is_demo"] else "Нет"]
                        writer.writerow(["'" + str(v) if str(v).lstrip().startswith(("=", "+", "-", "@")) else v for v in values])
                    self.send(output.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="incidents.csv"'})
                elif path.startswith("/api/"):
                    self.send({"error": "Адрес не найден."}, 404)
                else:
                    files = {"/": "index.html", "/app.js": "app.js", "/investigation.js": "investigation.js", "/style.css": "style.css", "/favicon.svg": "favicon.svg"}
                    if path not in files:
                        self.send({"error": "Страница не найдена."}, 404)
                        return
                    file = ROOT / "web" / files[path]
                    mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                    self.send(file.read_bytes(), content_type=mime + ("; charset=utf-8" if mime.startswith("text/") or "javascript" in mime else ""))
        except ValueError as exc:
            self.send({"error": str(exc)}, 400)
        except sqlite3.Error:
            self.send({"error": "Не удалось прочитать данные. Повторите запрос."}, 500)

    @staticmethod
    def get_id(path):
        try:
            return int(path.rsplit("/", 1)[-1])
        except ValueError:
            raise ValueError("Некорректный номер инцидента.")

    def do_POST(self):
        self.mutate("POST")

    def do_PATCH(self):
        self.mutate("PATCH")

    def mutate(self, method):
        if not self.allowed():
            return
        path = urlsplit(self.path).path
        try:
            data = self.read_json()
            with connect(self.server.db_path) as db:
                if path.startswith("/api/incidents/") and path.endswith("/investigation") and method == "POST":
                    parts = path.strip('/').split('/')
                    if len(parts) != 4:
                        raise ValueError("Некорректный адрес расследования.")
                    incident_id = self.get_id('/' + parts[2])
                    result = investigation_mutate(db, incident_id, data)
                    db.commit()
                    self.send({"investigation": result})
                elif path == "/api/analyze" and method == "POST":
                    validated = validate_incident(data)
                    self.send(analyze(validated, articles(db)))
                elif path == "/api/incidents" and method == "POST":
                    validated = validate_incident(data)
                    incident_id = create_incident(db, validated)
                    db.commit()
                    self.send({"id": incident_id}, 201)
                elif path == "/api/articles" and method == "POST":
                    item = validate_article(data)
                    cursor = db.execute("INSERT INTO articles(title, category, summary, keywords, steps) VALUES(?,?,?,?,?)", (item["title"], item["category"], item["summary"], json.dumps(item["keywords"], ensure_ascii=False), json.dumps(item["steps"], ensure_ascii=False)))
                    db.commit()
                    self.send({"id": cursor.lastrowid}, 201)
                elif path.startswith("/api/incidents/") and method == "PATCH":
                    incident_id = self.get_id(path)
                    row = db.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
                    if not row:
                        self.send({"error": "Инцидент не найден."}, 404)
                        return
                    status = data.get("status")
                    transitions = {"new": {"in_progress"}, "in_progress": {"resolved"}, "resolved": {"in_progress"}}
                    if not isinstance(status, str) or status not in transitions[row["status"]]:
                        raise ValueError("Недопустимый переход статуса. Новое обращение сначала нужно взять в работу.")
                    resolution = data.get("resolution", "")
                    if not isinstance(resolution, str) or len(resolution.strip()) > 5000:
                        raise ValueError("Описание решения должно содержать не более 5000 символов.")
                    resolution = resolution.strip()
                    if status == "resolved" and len(resolution) < 10:
                        raise ValueError("Опишите решение: не менее 10 символов.")
                    stamp = now()
                    db.execute("UPDATE incidents SET status=?, resolution=?, updated_at=?, resolved_at=? WHERE id=?", (status, resolution if status == "resolved" else row["resolution"], stamp, stamp if status == "resolved" else None, incident_id))
                    message = f"Статус: {STATUSES[row['status']]} → {STATUSES[status]}." + (f" Решение: {resolution}" if status == "resolved" else "")
                    db.execute("INSERT INTO events(incident_id, kind, text, created_at) VALUES(?,?,?,?)", (incident_id, "status", message, stamp))
                    db.commit()
                    self.send({"id": incident_id, "status": status})
                else:
                    self.send({"error": "Адрес или действие не найдено."}, 404)
        except InvestigationError as exc:
            self.send({"error": str(exc)}, exc.status)
        except ValueError as exc:
            self.send({"error": str(exc)}, 400)
        except sqlite3.Error:
            self.send({"error": "Не удалось сохранить данные. Повторите запрос."}, 500)


class Handler(RequestHandler, BaseHTTPRequestHandler):
    """Local socket transport; the hosted adapter lives in wsgi.py."""


def main():
    parser = argparse.ArgumentParser(description="Admin Assist — локальный помощник администратора ИС")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=str(ROOT / "data" / "admin-assist.sqlite3"))
    parser.add_argument("--empty", action="store_true", help="Не создавать демонстрационные инциденты в новой базе")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    initialize(args.db, demo=not args.empty)
    try:
        server = ApplicationServer(("127.0.0.1", args.port), args.db)
    except OSError as exc:
        print(f"Не удалось запустить приложение на порту {args.port}: {exc}")
        print("Если приложение уже запущено, откройте его адрес в браузере. Другой порт: python app.py --port 8766")
        raise SystemExit(1)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Admin Assist: {url}\nБаза данных: {args.db}\nДля остановки нажмите Ctrl+C.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
