import csv
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ApplicationServer
from database import initialize, connect, articles
from domain import analyze


class RulesTests(unittest.TestCase):
    def test_priority_matrix_all_nine_combinations(self):
        expected = {"single": ["low", "medium", "high"], "team": ["medium", "high", "high"], "all": ["medium", "high", "critical"]}
        for impact, row in expected.items():
            for urgency, priority in zip(["low", "medium", "high"], row):
                with self.subTest(impact=impact, urgency=urgency):
                    self.assertEqual(analyze(dict(impact=impact, urgency=urgency), [])["priority"], priority)

    def test_security_rule_and_explanation(self):
        result = analyze(dict(title="Подозрительное письмо: фишинг", impact="single", urgency="low"), [])
        self.assertEqual(result["category"], "security")
        self.assertEqual(result["priority"], "high")
        self.assertIn("безопасности", result["priority_reason"])

    def test_database_more_specific_than_connection(self):
        self.assertEqual(analyze(dict(title="Ошибка соединения с PostgreSQL", impact="single", urgency="medium"), [])["category"], "database")

    def test_unknown_is_not_claimed_as_recognized(self):
        result = analyze(dict(title="Нужна консультация специалиста", impact="single", urgency="low"), [])
        self.assertEqual(result["category"], "general")
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["confidence"], "Недостаточно признаков")


class APITests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / "data" / "test-runs"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.path = str(Path(self.temp.name) / "test.sqlite3")
        initialize(self.path, demo=False)
        self.server = ApplicationServer(("127.0.0.1", 0), self.path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, method="GET", data=None, headers=None):
        headers = {"Content-Type": "application/json", **(headers or {})}
        body = json.dumps(data).encode() if data is not None else None
        req = Request(self.base + path, data=body, method=method, headers=headers)
        try:
            with urlopen(req) as response:
                raw = response.read()
                return response.status, json.loads(raw) if "json" in response.headers.get("Content-Type", "") else raw
        except HTTPError as response:
            return response.code, json.loads(response.read())

    def payload(self, **changes):
        return dict(title="Не удаётся войти в систему", description="Пользователь забыл пароль от учётной записи.", service="Портал", impact="single", urgency="medium", **changes)

    def test_create_analyze_persist_and_recommend(self):
        status, result = self.request("/api/incidents", "POST", self.payload())
        self.assertEqual(status, 201)
        status, result = self.request(f"/api/incidents/{result['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(result["incident"]["category"], "access")
        self.assertEqual(result["incident"]["analysis"]["recommendations"][0]["category"], "access")
        self.assertEqual(len(result["events"]), 1)
        self.assertFalse(result["incident"]["is_demo"])
        initialize(self.path, demo=True)
        self.assertEqual(len(self.request("/api/bootstrap")[1]["incidents"]), 1)

    def test_preview_does_not_save(self):
        self.assertEqual(self.request("/api/analyze", "POST", self.payload())[0], 200)
        self.assertEqual(self.request("/api/bootstrap")[1]["incidents"], [])

    def test_workflow_resolution_reopen_history(self):
        incident_id = self.request("/api/incidents", "POST", self.payload())[1]["id"]
        path = f"/api/incidents/{incident_id}"
        self.assertEqual(self.request(path, "PATCH", dict(status="resolved", resolution="Проверено и исправлено"))[0], 400)
        self.assertEqual(self.request(path, "PATCH", dict(status="in_progress"))[0], 200)
        self.assertEqual(self.request(path, "PATCH", dict(status="resolved", resolution=""))[0], 400)
        self.assertEqual(self.request(path, "PATCH", dict(status="resolved", resolution="Доступ восстановлен по регламенту"))[0], 200)
        self.assertIsNotNone(self.request(path)[1]["incident"]["resolved_at"])
        self.assertEqual(self.request(path, "PATCH", dict(status="in_progress"))[0], 200)
        result = self.request(path)[1]
        self.assertIsNone(result["incident"]["resolved_at"])
        self.assertIn("восстановлен", result["incident"]["resolution"])
        self.assertEqual(len(result["events"]), 4)

    def test_invalid_requests_are_rejected_without_writes(self):
        for data in [[], {}, {**self.payload(), "impact": []}, {**self.payload(), "title": "x"}, {**self.payload(), "urgency": "invalid"}]:
            self.assertEqual(self.request("/api/incidents", "POST", data)[0], 400)
        self.assertEqual(self.request("/api/bootstrap")[1]["incidents"], [])

    def test_new_article_used_in_new_incident(self):
        data = dict(title="Восстановление входа в портал", category="access", summary="Инструкция по работе с доступом в портал.", keywords=["портал", "пароль", "войти"], steps=["Выполнить проверку записи", "Подтвердить восстановление"])
        self.assertEqual(self.request("/api/articles", "POST", data)[0], 201)
        result = self.request("/api/analyze", "POST", self.payload())[1]
        self.assertTrue(any(r["title"] == data["title"] for r in result["recommendations"]))

    def test_reject_external_origin(self):
        status, _ = self.request("/api/incidents", "POST", self.payload(), {"Origin": "https://example.com"})
        self.assertEqual(status, 403)

    def test_export_russian_and_formula_protection(self):
        data = self.payload()
        data["title"] = "=HYPERLINK(опасная формула)"
        self.request("/api/incidents", "POST", data)
        status, output = self.request("/api/export")
        self.assertEqual(status, 200)
        rows = list(csv.reader(io.StringIO(output.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(rows[0][1], "Название")
        self.assertTrue(rows[1][1].startswith("'="))

    def test_demo_seed_only_once(self):
        demo_path = str(Path(self.temp.name) / "demo.sqlite3")
        initialize(demo_path)
        initialize(demo_path)
        with connect(demo_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM incidents").fetchone()[0], 7)
            self.assertEqual(len(articles(db)), 6)

    def test_missing_and_static_paths(self):
        self.assertEqual(self.request("/")[0], 200)
        self.assertEqual(self.request("/api/incidents/999")[0], 404)
        self.assertEqual(self.request("/api/incidents/wrong")[0], 400)
        self.assertEqual(self.request("/../app.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
