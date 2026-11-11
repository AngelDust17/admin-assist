"""Hosted transport, persistence, and same-origin checks with isolated databases."""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen
from wsgiref.simple_server import make_server, WSGIRequestHandler
from wsgiref.util import setup_testing_defaults
from wsgiref.validate import validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wsgi import create_application, from_environment
from database import connect


class HostedTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / "data" / "test-runs"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.path = Path(self.temp.name) / "hosted.sqlite3"
        self.origin = "https://course-demo.pythonanywhere.com"
        self.application = create_application(self.path, self.origin, demo=False)

    def tearDown(self):
        self.temp.cleanup()

    def request(self, path, method="GET", data=None, *, host=None, origin=None,
                raw=None, content_type="application/json", length=None):
        body = raw if raw is not None else (json.dumps(data).encode() if data is not None else b"")
        environ = {}
        setup_testing_defaults(environ)
        environ.update(REQUEST_METHOD=method, PATH_INFO=path, QUERY_STRING="",
                       HTTP_HOST=host or "course-demo.pythonanywhere.com",
                       CONTENT_TYPE=content_type,
                       CONTENT_LENGTH=str(len(body)) if length is None else length)
        environ["wsgi.url_scheme"] = "https"
        environ["wsgi.input"] = io.BytesIO(body)
        if origin is not None:
            environ["HTTP_ORIGIN"] = origin
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured.update(status=int(status.split()[0]), headers=dict(headers))

        result = validator(self.application)(environ, start_response)
        try:
            content = b"".join(result)
        finally:
            result.close()
        captured["body"] = (json.loads(content) if content and
                            "application/json" in captured["headers"]["Content-Type"] else content)
        return captured

    @staticmethod
    def incident():
        return dict(title="Не удаётся войти в систему", description="Пользователь забыл пароль от учётной записи.",
                    service="Портал", impact="single", urgency="medium")

    def create_case(self):
        result = self.request("/api/incidents", "POST", self.incident(), origin=self.origin)
        self.assertEqual(result["status"], 201)
        return result["body"]["id"]

    def test_workflow_and_cyrillic_export(self):
        preview = self.request("/api/analyze", "POST", self.incident())
        self.assertEqual(preview["body"]["category"], "access")
        self.assertEqual(self.request("/api/bootstrap")["body"]["incidents"], [])
        case = f"/api/incidents/{self.create_case()}"
        self.assertEqual(self.request(case, "PATCH", {"status": "in_progress"})["status"], 200)
        self.assertEqual(self.request(case, "PATCH", {"status": "resolved", "resolution": "Восстановлен доступ к порталу"})["status"], 200)
        detail = self.request(case)["body"]
        self.assertEqual(detail["incident"]["status"], "resolved")
        self.assertEqual(len(detail["events"]), 3)
        exported = self.request("/api/export")
        self.assertEqual(exported["status"], 200)
        self.assertIn("Не удаётся войти", exported["body"].decode("utf-8-sig"))
        self.assertIn("attachment", exported["headers"]["Content-Disposition"])

    def test_investigation_and_new_worker_keep_state(self):
        case = f"/api/incidents/{self.create_case()}"
        endpoint = case + "/investigation"
        commands = [dict(action="start", revision=0, scenario="access"),
                    dict(action="answer", revision=1, question_id="other_login", answer="yes"),
                    dict(action="answer", revision=2, question_id="account_blocked", answer="yes")]
        for command in commands:
            self.assertEqual(self.request(endpoint, "POST", command)["status"], 200)
        self.application = create_application(self.path, self.origin)
        bootstrap = self.request("/api/bootstrap")["body"]
        self.assertEqual(len(bootstrap["incidents"]), 1)
        self.assertTrue(bootstrap["environment"]["public"])
        investigation = self.request(case)["body"]["investigation"]
        self.assertEqual(investigation["phase"], "supported")
        self.assertEqual(investigation["revision"], 3)
        self.assertEqual(self.request(endpoint, "POST", commands[-1])["status"], 409)

    def test_wrong_host_and_cross_site_requests_cannot_write(self):
        for origin in ("https://evil.example", "null", "http://course-demo.pythonanywhere.com"):
            self.assertEqual(self.request("/api/incidents", "POST", self.incident(), origin=origin)["status"], 403)
        self.assertEqual(self.request("/api/incidents", "POST", self.incident(), host="evil.example")["status"], 403)
        self.assertEqual(self.request("/api/bootstrap")["body"]["incidents"], [])

    def test_bad_json_and_size_do_not_write(self):
        for raw, content_type, length in ((b"broken", "application/json", None),
                (b"[]", "application/json", None), (b"{}", "text/plain", None),
                (b"{}", "application/json", "65537")):
            self.assertEqual(self.request("/api/incidents", "POST", raw=raw,
                content_type=content_type, length=length)["status"], 400)
        self.assertEqual(self.request("/api/bootstrap")["body"]["incidents"], [])

    def test_static_head_methods_and_private_files(self):
        for path in ("/", "/app.js", "/investigation.js", "/style.css", "/favicon.svg"):
            result = self.request(path)
            self.assertEqual(result["status"], 200)
            self.assertEqual(result["headers"]["X-Content-Type-Options"], "nosniff")
            self.assertIn("frame-ancestors 'none'", result["headers"]["Content-Security-Policy"])
        for path in ("/app.py", "/data/hosted.sqlite3", "/../database.py", "/.env", "/.git/config"):
            self.assertEqual(self.request(path)["status"], 404)
        head = self.request("/", "HEAD")
        self.assertEqual(head["status"], 200)
        self.assertEqual(head["body"], b"")
        self.assertGreater(int(head["headers"]["Content-Length"]), 0)
        self.assertEqual(self.request("/", "DELETE")["status"], 405)

    def test_environment_configuration_and_isolated_seed(self):
        other_path = Path(self.temp.name) / "public" / "stand.sqlite3"
        with patch.dict(os.environ, {"ADMIN_ASSIST_HOST": "COURSE-DEMO.pythonanywhere.com",
                                    "ADMIN_ASSIST_DB_PATH": str(other_path)}):
            self.application = from_environment()
        self.assertEqual(len(self.request("/api/bootstrap")["body"]["incidents"]), 7)
        self.assertEqual(self.request("/api/bootstrap", host="COURSE-DEMO.pythonanywhere.com")["status"], 200)
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM incidents").fetchone()[0], 0)
        for bad in ("", "*.pythonanywhere.com", "https://demo.example/path", "https://user:pass@demo.example"):
            with self.assertRaises(ValueError):
                create_application(self.path, bad)

    def test_real_wsgi_server_serves_application(self):
        class QuietHandler(WSGIRequestHandler):
            def log_message(self, *args):
                pass
        with make_server("127.0.0.1", 0, self.application, handler_class=QuietHandler) as server:
            origin = f"http://127.0.0.1:{server.server_port}"
            server.set_app(create_application(self.path, origin, demo=False))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(origin + "/api/bootstrap") as response:
                    self.assertEqual(response.status, 200)
                    self.assertTrue(json.load(response)["environment"]["public"])
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main()
