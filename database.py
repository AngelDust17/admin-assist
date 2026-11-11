import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from domain import analyze

DEFAULT_ARTICLES = [
    {"title": "Восстановление доступа к учётной записи", "category": "access", "summary": "Проверка блокировки, срока действия пароля и прав пользователя.", "keywords": ["пароль", "войти", "учетная запись", "вход", "доступ"], "steps": ["Уточнить имя пользователя, время ошибки и текст сообщения. Не запрашивать пароль.", "Проверить состояние учётной записи и срок действия пароля в консоли администратора.", "Проверить назначенные роли и журнал неудачных входов.", "После подтверждения личности применить штатную процедуру восстановления доступа.", "Попросить пользователя проверить вход и записать результат в инцидент."]},
    {"title": "Диагностика недоступного сервиса", "category": "application", "summary": "Локализация сбоя приложения по состоянию сервиса и журналам ошибок.", "keywords": ["недоступен", "500", "502", "503", "сбой", "приложение"], "steps": ["Уточнить масштаб недоступности и время начала сбоя.", "Проверить состояние сервиса и его зависимостей.", "Просмотреть журналы приложения за время возникновения ошибки.", "Сопоставить сбой с последними изменениями конфигурации или обновлениями.", "Выбрать согласованный способ восстановления; после выполнения проверить доступность."]},
    {"title": "Проверка подключения к базе данных", "category": "database", "summary": "Диагностика ошибок подключения, блокировок и исчерпания соединений.", "keywords": ["база данных", "postgres", "sql", "транзакция", "mysql"], "steps": ["Проверить доступность сервера СУБД и наличие ошибки в журнале приложения.", "Проверить параметры подключения и права сервисной учётной записи, не раскрывая секреты.", "Проверить число активных соединений, длительные запросы и блокировки.", "Проверить свободное место и состояние резервного копирования.", "Согласовать корректирующее действие и проверить выполнение контрольного запроса."]},
    {"title": "Проверка сетевого соединения", "category": "network", "summary": "Проверка DNS, маршрута и доступности внутреннего ресурса.", "keywords": ["сеть", "dns", "vpn", "интернет", "соединение"], "steps": ["Определить, затронут ли один компьютер или целый сегмент сети.", "Проверить подключение и параметры IP на затронутом устройстве.", "Проверить разрешение имени сервиса через DNS.", "Проверить доступность нужного узла и порта разрешёнными средствами диагностики.", "При необходимости передать результаты сетевому администратору."]},
    {"title": "Анализ снижения производительности", "category": "performance", "summary": "Поиск узкого места по нагрузке и времени ответа системы.", "keywords": ["медленно", "память", "диск", "нагрузка", "тормозит"], "steps": ["Зафиксировать операцию, время ответа и период возникновения проблемы.", "Проверить загрузку процессора, использование памяти и диска.", "Сопоставить нагрузку с количеством пользователей и фоновыми заданиями.", "Изучить длительные запросы и ошибки в журналах.", "Согласовать изменение и сравнить время ответа до и после него."]},
    {"title": "Первичная обработка события безопасности", "category": "security", "summary": "Фиксация признаков инцидента и передача ответственному за безопасность.", "keywords": ["вирус", "фишинг", "взлом", "подозрительный", "утечка"], "steps": ["Зафиксировать источник, время и признаки события, сохранив доступные журналы.", "Уведомить ответственного за информационную безопасность по принятому регламенту.", "По согласованной процедуре ограничить распространение угрозы.", "Не удалять потенциальные доказательства и не запускать подозрительные файлы.", "Документировать принятые меры и результаты проверки."]},
]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def articles(db):
    return [{**dict(row), "keywords": json.loads(row["keywords"]), "steps": json.loads(row["steps"])}
            for row in db.execute("SELECT * FROM articles ORDER BY id")]


def incident_dict(row):
    return {**dict(row), "analysis": json.loads(row["analysis"])}


def create_incident(db, data, demo=False, created_at=None):
    analysis = analyze(data, articles(db))
    stamp = created_at or now()
    cursor = db.execute("""INSERT INTO incidents(title, description, service, impact, urgency, status,
        category, priority, analysis, created_at, updated_at, is_demo) VALUES(?,?,?,?,?,'new',?,?,?,?,?,?)""",
        (data["title"], data["description"], data["service"], data["impact"], data["urgency"],
         analysis["category"], analysis["priority"], json.dumps(analysis, ensure_ascii=False), stamp, stamp, int(demo)))
    incident_id = cursor.lastrowid
    db.execute("INSERT INTO events(incident_id, kind, text, created_at) VALUES(?,?,?,?)",
               (incident_id, "created", "Инцидент зарегистрирован. Выполнен анализ по правилам.", stamp))
    return incident_id


def initialize(path, demo=True):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
          summary TEXT NOT NULL, keywords TEXT NOT NULL, steps TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
          service TEXT NOT NULL, impact TEXT NOT NULL, urgency TEXT NOT NULL, status TEXT NOT NULL,
          category TEXT NOT NULL, priority TEXT NOT NULL, analysis TEXT NOT NULL, resolution TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, resolved_at TEXT, is_demo INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, incident_id INTEGER NOT NULL REFERENCES incidents(id),
          kind TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS incidents_status_idx ON incidents(status);
        CREATE TABLE IF NOT EXISTS investigations(incident_id INTEGER PRIMARY KEY REFERENCES incidents(id),
          scenario TEXT NOT NULL, scenario_version INTEGER NOT NULL, revision INTEGER NOT NULL,
          answers TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        """)
        if db.execute("SELECT value FROM metadata WHERE key='initialized'").fetchone():
            return
        for article in DEFAULT_ARTICLES:
            db.execute("INSERT INTO articles(title, category, summary, keywords, steps) VALUES(?,?,?,?,?)",
                       (article["title"], article["category"], article["summary"], json.dumps(article["keywords"], ensure_ascii=False), json.dumps(article["steps"], ensure_ascii=False)))
        if demo:
            samples = [
                ("Корпоративный портал недоступен", "Все сотрудники получают ошибку 503 при открытии портала. Работа остановлена.", "Корпоративный портал", "all", "high", "in_progress"),
                ("Не удаётся войти в систему", "После смены пароля пользователь не может войти в учётную запись.", "Система документооборота", "single", "medium", "new"),
                ("Медленная загрузка отчётов", "Отчёты отдела продаж открываются медленно, наблюдается высокая нагрузка на процессор.", "CRM", "team", "medium", "in_progress"),
                ("Ошибка подключения к PostgreSQL", "Приложение не устанавливает соединение с базой данных PostgreSQL.", "Учётная система", "team", "high", "new"),
                ("Подозрительное письмо сотруднику", "Пользователь сообщил о фишинге: письмо запрашивает пароль от корпоративной почты.", "Корпоративная почта", "single", "low", "new"),
                ("Нет подключения через VPN", "Пользователь не мог подключиться к внутреннему ресурсу через VPN.", "Удалённый доступ", "single", "medium", "resolved"),
                ("Заблокирована учётная запись", "Пользователь сообщил о блокировке учётной записи после нескольких попыток входа.", "Система документооборота", "single", "low", "resolved"),
            ]
            base = datetime.now(timezone.utc)
            for index, (title, description, service, impact, urgency, status) in enumerate(samples):
                created = (base - timedelta(hours=(index + 1) * 5)).isoformat(timespec="seconds")
                incident_id = create_incident(db, dict(title=title, description=description, service=service, impact=impact, urgency=urgency), True, created)
                if status != "new":
                    updated = (base - timedelta(hours=index + 1)).isoformat(timespec="seconds")
                    resolution = "Параметры подключения проверены и исправлены. Пользователь подтвердил восстановление работы." if status == "resolved" else ""
                    db.execute("UPDATE incidents SET status=?, resolution=?, updated_at=?, resolved_at=? WHERE id=?", (status, resolution, updated, updated if status == "resolved" else None, incident_id))
                    db.execute("INSERT INTO events(incident_id, kind, text, created_at) VALUES(?,?,?,?)", (incident_id, "status", "Демонстрация: инцидент решён." if status == "resolved" else "Инцидент взят в работу.", updated))
        db.execute("INSERT INTO metadata(key,value) VALUES('initialized','1')")
