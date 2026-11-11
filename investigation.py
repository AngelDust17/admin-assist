"""Small, versioned expert system. Conclusions describe evidence, not probabilities."""
import json
from datetime import datetime, timezone

ANSWER_LABELS = {"yes": "Да", "no": "Нет", "unknown": "Не удалось проверить"}


def question(key, title, how, why):
    return dict(id=key, title=title, how=how, why=why)


def hypothesis(key, title, conditions, advice):
    return dict(id=key, title=title, conditions=conditions, advice=advice)


SCENARIOS = {
    "access": {
        "title": "Не удаётся войти", "category": "access",
        "description": "Блокировка записи, отклонение учётных данных или общий отказ авторизации.",
        "questions": [
            question("other_login", "Другой пользователь успешно входит в этот же сервис?", "Проверьте контрольный вход другой действующей учётной записью в тот же период. Не запрашивайте чужой пароль.", "Успешный вход исключает полный отказ авторизации для всех пользователей."),
            question("account_blocked", "Учётная запись отмечена как заблокированная?", "Посмотрите состояние именно этой записи в штатной консоли администрирования.", "Прямая проверка состояния позволяет подтвердить или исключить блокировку."),
            question("auth_health", "Контрольный вход в службу авторизации проходит успешно?", "Проверьте контрольную авторизацию и журнал службы. Доступность страницы сама по себе не подтверждает работу входа.", "Это отличает общий отказ авторизации от проблемы отдельной записи."),
            question("credential_error", "В журнале есть явный отказ из-за неверных или истёкших учётных данных?", "Найдите запись с подходящим временем и именем пользователя. Зафиксируйте текст ошибки без пароля и других секретов.", "Явная ошибка учётных данных служит основанием для этой версии."),
        ],
        "hypotheses": [
            hypothesis("auth_failure", "Общий отказ службы авторизации", {"other_login": "no", "auth_health": "no"}, ["Изучить ошибки службы авторизации и состояние её зависимостей.", "Согласовать восстановление службы по действующему регламенту.", "После восстановления проверить контрольный вход нескольких пользователей."]),
            hypothesis("locked", "Блокировка учётной записи", {"account_blocked": "yes"}, ["Установить причину блокировки по журналу входов.", "После подтверждения личности применить штатную процедуру разблокировки.", "Проверить повторный вход и отсутствие новой блокировки."]),
            hypothesis("credentials", "Отклонение учётных данных", {"account_blocked": "no", "credential_error": "yes"}, ["Проверить срок действия пароля и правильность имени пользователя.", "При необходимости выполнить штатное восстановление доступа после проверки личности.", "Попросить пользователя проверить вход; пароль в обращении не сохранять."]),
        ],
    },
    "application": {
        "title": "Приложение недоступно", "category": "application",
        "description": "Остановка приложения, отказ зависимости БД или проблема разрешения имени.",
        "questions": [
            question("service_running", "Процесс приложения запущен?", "Проверьте состояние службы или процесса на сервере приложения. Доступность базы данных проверяется отдельно.", "Остановленный процесс объясняет недоступность приложения. Запущенный процесс ещё не подтверждает работу его зависимостей."),
            question("db_error", "В журнале приложения есть ошибки подключения к базе данных?", "Сопоставьте время сбоя с явными сообщениями об ошибках соединения с БД.", "Совпадающая по времени ошибка указывает на зависимость, которую нужно проверить."),
            question("db_check", "Контрольное подключение к БД с сервера приложения успешно?", "Используйте согласованный способ проверки с теми же параметрами подключения, не раскрывая секреты.", "Неудачный контрольный запрос вместе с ошибкой приложения поддерживает версию отказа зависимости."),
            question("direct_access", "Сервис доступен по разрешённому прямому адресу в обход DNS?", "Проверьте прямой адрес разрешённым средством с учётом настройки виртуальных хостов. Если такая проверка некорректна, выберите «Не удалось проверить».", "Работа по прямому адресу позволяет отдельно проверить разрешение имени."),
            question("dns_resolves", "Имя сервиса разрешается в ожидаемый адрес?", "Сравните результат разрешения имени на затронутом устройстве с актуальной конфигурацией сервиса.", "Неверный адрес при успешном прямом доступе поддерживает версию проблемы DNS."),
        ],
        "hypotheses": [
            hypothesis("stopped", "Процесс приложения остановлен", {"service_running": "no"}, ["Проверить журнал запуска и состояние процесса приложения.", "Сопоставить ошибку с конфигурацией и последними изменениями.", "Согласовать восстановление и повторить локальную и пользовательскую проверки."]),
            hypothesis("db_dependency", "Недоступна зависимость базы данных", {"service_running": "yes", "db_error": "yes", "db_check": "no"}, ["Проверить доступность и состояние БД с сервера приложения.", "Проверить параметры соединения и журнал СУБД.", "После восстановления зависимости проверить работу приложения."]),
            hypothesis("dns", "Проблема разрешения имени сервиса", {"service_running": "yes", "direct_access": "yes", "dns_resolves": "no"}, ["Проверить настройки DNS и актуальность записи сервиса.", "Согласовать исправление неверной записи или конфигурации клиента.", "Проверить доступ по имени с затронутого устройства."]),
        ],
    },
    "database": {
        "title": "Нет подключения к БД", "category": "database",
        "description": "Состояние СУБД, сетевой доступ, аутентификация и лимит соединений.",
        "questions": [
            question("db_running", "Служба СУБД запущена?", "Проверьте состояние службы или процесса СУБД на её сервере. Ошибку входа под отдельной записью не считайте остановкой службы.", "Состояние службы позволяет отделить её остановку от проблем сети и аутентификации."),
            question("db_port", "Нужный сетевой порт БД доступен с сервера приложения?", "Проверьте согласованный адрес и порт именно с того сервера, где работает приложение.", "Это позволяет отделить сетевую недоступность от отказа на уровне учётной записи."),
            question("db_auth_error", "СУБД явно отклоняет аутентификацию сервисной учётной записи?", "Проверьте журнал СУБД на сообщения об отказе аутентификации. Не копируйте пароль в заметку.", "Явный отказ аутентификации при работающем соединении поддерживает версию проблемы учётной записи."),
            question("connection_limit", "Журнал СУБД сообщает об исчерпании соединений?", "Проверьте явное сообщение о лимите и фактическое число активных соединений.", "Эта версия требует наблюдения лимита, а не только общей ошибки подключения."),
        ],
        "hypotheses": [
            hypothesis("db_down", "Служба СУБД остановлена", {"db_running": "no"}, ["Изучить журнал СУБД и причину неуспешного запуска или проверки.", "Проверить ресурсы сервера и свободное место.", "Восстановить работу по регламенту и повторить контрольный запрос."]),
            hypothesis("network", "Сетевая недоступность БД", {"db_running": "yes", "db_port": "no"}, ["Проверить адрес, порт и маршрут между приложением и СУБД.", "Сверить разрешённые сетевые подключения с конфигурацией.", "После согласованного исправления повторить подключение с сервера приложения."]),
            hypothesis("db_credentials", "СУБД отклоняет сервисную учётную запись", {"db_running": "yes", "db_port": "yes", "db_auth_error": "yes"}, ["Проверить состояние записи и параметры аутентификации.", "Согласовать исправление параметров или прав сервисной записи.", "Проверить контрольное подключение и работу приложения."]),
            hypothesis("limits", "Исчерпан лимит соединений", {"db_running": "yes", "db_port": "yes", "connection_limit": "yes"}, ["Изучить активные соединения и настройки пула приложения.", "Установить причину накопления соединений.", "Согласовать изменение и проверить, что ошибка больше не возникает."]),
        ],
    },
}


class InvestigationError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def catalog():
    return [dict(id=key, title=value["title"], description=value["description"]) for key, value in SCENARIOS.items()]


def derive(scenario_id, answers):
    spec = SCENARIOS[scenario_id]
    facts = {a["question_id"]: a["answer"] for a in answers}
    questions = {q["id"]: q for q in spec["questions"]}
    hypotheses = []
    for h in spec["hypotheses"]:
        evidence, contradictions, remaining = [], [], []
        for key, expected in h["conditions"].items():
            observed = facts.get(key)
            if observed in (None, "unknown"):
                remaining.append(key)
            else:
                item = dict(question_id=key, question=questions[key]["title"], answer=observed, answer_label=ANSWER_LABELS[observed])
                (evidence if observed == expected else contradictions).append(item)
        status = "ruled_out" if contradictions else "supported" if not remaining else "possible"
        hypotheses.append(dict(id=h["id"], title=h["title"], status=status,
                               status_label={"ruled_out": "Исключена", "supported": "Подтверждается", "possible": "Нужна проверка"}[status],
                               evidence=evidence, contradictions=contradictions, remaining=remaining,
                               advice=h["advice"] if status == "supported" else []))
    unanswered = [q for q in spec["questions"] if q["id"] not in facts]
    pending = [h for h in hypotheses if h["status"] == "possible"]
    # Prefer checks which separate versions, then checks which finish a partially tested version.
    candidates = []
    for order, q in enumerate(unanswered):
        relevant = [h for h in pending if q["id"] in h["remaining"]]
        if not relevant:
            continue
        conditions = [h["conditions"][q["id"]] for h in spec["hypotheses"] if any(r["id"] == h["id"] for r in relevant)]
        score = 4 * conditions.count("yes") * conditions.count("no") + sum(1 + 2 * len(h["evidence"]) for h in relevant)
        candidates.append((score, -order, q))
    next_question = max(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else None
    # Establish scope first; a failed shared login leads to checking the authentication service.
    if scenario_id == "access":
        if "other_login" not in facts:
            next_question = questions["other_login"]
        elif facts["other_login"] == "no" and "auth_health" not in facts:
            next_question = questions["auth_health"]
    elif not answers:
        next_question = spec["questions"][0]
    supported = [h for h in hypotheses if h["status"] == "supported"]
    if supported:
        phase = "supported"
        summary = "Наблюдения поддерживают: " + "; ".join(h["title"].lower() for h in supported) + ". Проверьте рекомендацию и результат восстановления."
    elif next_question:
        phase, summary = "checking", "Причина ещё не установлена. Следующая проверка поможет различить оставшиеся версии."
    else:
        phase, summary = "inconclusive", "Данных недостаточно либо причина выходит за рамки этого сценария. Подтверждённой версии нет; зафиксируйте наблюдения и продолжите диагностику."
    history = [{**a, "question": questions[a["question_id"]]["title"], "answer_label": ANSWER_LABELS[a["answer"]]} for a in answers]
    return dict(hypotheses=hypotheses, next_question=next_question, phase=phase, summary=summary,
                answers=history, answered_count=len(answers), unknown_count=sum(a["answer"] == "unknown" for a in answers))


def view(db, incident):
    session = db.execute("SELECT * FROM investigations WHERE incident_id=?", (incident["id"],)).fetchone()
    common = dict(scenarios=catalog(), suggested_scenario=incident["category"] if incident["category"] in SCENARIOS else None,
                  read_only=incident["status"] == "resolved")
    if not session:
        return dict(common, started=False, revision=0)
    return dict(common, started=True, revision=session["revision"], scenario=session["scenario"],
                scenario_title=SCENARIOS[session["scenario"]]["title"], scenario_version=session["scenario_version"],
                updated_at=session["updated_at"], **derive(session["scenario"], json.loads(session["answers"])))


def mutate(db, incident_id, data):
    db.execute("BEGIN IMMEDIATE")
    incident = db.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
    if not incident:
        raise InvestigationError("Обращение не найдено.", 404)
    if incident["status"] == "resolved":
        raise InvestigationError("Обращение решено. Для продолжения расследования верните его в работу.", 409)
    session = db.execute("SELECT * FROM investigations WHERE incident_id=?", (incident_id,)).fetchone()
    revision = session["revision"] if session else 0
    expected = data.get("revision")
    if type(expected) is not int or expected < 0:
        raise InvestigationError("Нужно передать актуальную версию расследования.")
    if expected != revision:
        raise InvestigationError("Расследование изменилось в другой вкладке. Обновите обращение перед ответом.", 409)
    action = data.get("action")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if action in ("start", "restart"):
        scenario = data.get("scenario")
        if not isinstance(scenario, str) or scenario not in SCENARIOS:
            raise InvestigationError("Выберите доступный сценарий расследования.")
        if action == "start" and session:
            raise InvestigationError("Расследование уже начато. Обновите обращение.", 409)
        if action == "restart" and not session:
            raise InvestigationError("Расследование ещё не начато.")
        answers = []
        previous = ""
        if session:
            previous = " Предыдущие ответы: " + json.dumps(derive(session["scenario"], json.loads(session["answers"]))["answers"], ensure_ascii=False)
        message = f"{'Начато' if action == 'start' else 'Начато заново'} расследование: {SCENARIOS[scenario]['title']}." + previous
    elif action in ("answer", "revise"):
        if not session:
            raise InvestigationError("Сначала начните расследование.")
        scenario = session["scenario"]
        answers = json.loads(session["answers"])
        answer, key = data.get("answer"), data.get("question_id")
        note = data.get("note", "")
        if not isinstance(answer, str) or answer not in ANSWER_LABELS or not isinstance(key, str):
            raise InvestigationError("Выберите один из предложенных результатов проверки.")
        if not isinstance(note, str) or len(note.strip()) > 1000:
            raise InvestigationError("Заметка должна содержать не более 1000 символов.")
        dropped = []
        if action == "answer":
            current = derive(scenario, answers)["next_question"]
            if not current or key != current["id"]:
                raise InvestigationError("Эта проверка сейчас неактуальна. Обновите обращение.", 409)
        else:
            index = next((i for i, a in enumerate(answers) if a["question_id"] == key), None)
            if index is None:
                raise InvestigationError("Ответ для изменения не найден.")
            dropped = answers[index:]
            answers = answers[:index]
        item = dict(question_id=key, answer=answer, note=note.strip(), answered_at=stamp)
        answers.append(item)
        title = next(q["title"] for q in SCENARIOS[scenario]["questions"] if q["id"] == key)
        message = f"{'Проверка' if action == 'answer' else 'Ответ исправлен'}: {title} — {ANSWER_LABELS[answer]}."
        if note.strip():
            message += " Наблюдение: " + note.strip()
        if dropped:
            message += " Предыдущее состояние снятых ответов: " + json.dumps(dropped, ensure_ascii=False)
    else:
        raise InvestigationError("Неизвестное действие расследования.")
    db.execute("""INSERT INTO investigations(incident_id,scenario,scenario_version,revision,answers,created_at,updated_at)
        VALUES(?,?,1,?,?,?,?) ON CONFLICT(incident_id) DO UPDATE SET scenario=excluded.scenario,
        revision=excluded.revision,answers=excluded.answers,updated_at=excluded.updated_at""",
        (incident_id, scenario, revision + 1, json.dumps(answers, ensure_ascii=False), stamp, stamp))
    db.execute("INSERT INTO events(incident_id,kind,text,created_at) VALUES(?,?,?,?)", (incident_id, "investigation", message, stamp))
    return view(db, incident)
