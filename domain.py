"""Explainable incident classification and priority rules; no external services."""
import re

IMPACTS = {"single": "Один пользователь", "team": "Отдел / группа", "all": "Вся организация"}
URGENCIES = {"low": "Работа может подождать", "medium": "Работа затруднена", "high": "Работа остановлена"}
STATUSES = {"new": "Новое", "in_progress": "В работе", "resolved": "Решено"}
PRIORITIES = {"critical": "Критический", "high": "Высокий", "medium": "Средний", "low": "Низкий"}
PRIORITY_MATRIX = {
    "single": {"low": "low", "medium": "medium", "high": "high"},
    "team": {"low": "medium", "medium": "high", "high": "high"},
    "all": {"low": "medium", "medium": "high", "high": "critical"},
}
CATEGORIES = [
    ("security", "Безопасность", [(r"взлом\w*|вирус\w*|фишинг\w*|шифровальщик\w*|утечк\w*|несанкционирован\w*|подозрительн\w*", 3)]),
    ("access", "Доступ и учётные записи", [(r"парол\w*|авторизац\w*|аутентификац\w*|уч[её]тн\w*|заблокирован\w*", 3), (r"войти|вход\w*|доступ\w*", 1)]),
    ("database", "Базы данных", [(r"баз[аыуе]\s+данных|postgres\w*|mysql\w*|sqlite\w*|sql\b|субд", 4), (r"транзакц\w*|дедлок\w*|deadlock", 2)]),
    ("network", "Сеть и соединения", [(r"сет[ьи]\w*|сетев\w*|интернет\w*|dns\b|vpn\b|маршрутизатор\w*|соединени\w*", 3), (r"таймаут\w*|timeout", 1)]),
    ("performance", "Производительность", [(r"медлен\w*|тормоз\w*|производительност\w*|завис\w*|нагрузк\w*|памят\w*|процессор\w*|диск\w*", 3)]),
    ("application", "Ошибки приложения", [(r"ошибк\w*|сбой\w*|недоступ\w*|исключени\w*|500\b|502\b|503\b|приложени\w*", 2)]),
]


def analyze(payload, articles):
    title = str(payload.get("title", ""))
    description = str(payload.get("description", ""))
    source = f"{title} {description}".lower().replace("ё", "е")
    scores = []
    for category, label, patterns in CATEGORIES:
        terms, score = [], 0
        for pattern, weight in patterns:
            found = re.findall(pattern, source, re.IGNORECASE)
            if found:
                score += weight
                terms.extend(found)
        if score:
            scores.append((score, category, label, list(dict.fromkeys(terms))))
    scores.sort(key=lambda item: item[0], reverse=True)
    if scores:
        score, category, label, terms = scores[0]
        classification_reason = f"Найдены признаки: {', '.join(terms[:5])}."
        ambiguous = len(scores) > 1 and scores[1][0] == score
        confidence = "Требует проверки" if ambiguous else "Совпадение по правилам"
    else:
        category, label = "general", "Прочие обращения"
        classification_reason = "Специфические признаки не найдены. Категория требует проверки администратором."
        confidence = "Недостаточно признаков"
    impact = payload.get("impact", "single")
    urgency = payload.get("urgency", "medium")
    if impact not in IMPACTS or urgency not in URGENCIES:
        raise ValueError("Выберите корректные влияние и срочность.")
    priority = PRIORITY_MATRIX[impact][urgency]
    priority_reason = f"Влияние: {IMPACTS[impact].lower()}. Срочность: {URGENCIES[urgency].lower()}. По матрице 3 × 3 — {PRIORITIES[priority].lower()} приоритет."
    if category == "security" and priority in ("low", "medium"):
        priority = "high"
        priority_reason += " Правило безопасности повышает приоритет до высокого."
    ranked = []
    for article in articles:
        hits = [kw for kw in article["keywords"] if kw.lower() in source]
        relevance = (5 if article["category"] == category else 0) + len(hits)
        if relevance:
            ranked.append({**article, "relevance": relevance, "matched_keywords": hits,
                           "match_reason": "Совпала категория" if article["category"] == category else "Совпали ключевые слова"})
    ranked.sort(key=lambda a: a["relevance"], reverse=True)
    return {"category": category, "category_label": label, "classification_reason": classification_reason,
            "confidence": confidence, "priority": priority, "priority_label": PRIORITIES[priority],
            "priority_reason": priority_reason, "recommendations": ranked[:3],
            "engine": "Правила классификации + матрица приоритетов + поиск в базе знаний"}


def validate_incident(data):
    result = {}
    for key, label, minimum, maximum in [("title", "Название", 5, 160), ("description", "Описание", 10, 5000), ("service", "Сервис", 2, 100)]:
        value = data.get(key)
        if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
            raise ValueError(f"{label}: укажите от {minimum} до {maximum} символов.")
        result[key] = value.strip()
    for key, allowed in [("impact", IMPACTS), ("urgency", URGENCIES)]:
        if not isinstance(data.get(key), str) or data[key] not in allowed:
            raise ValueError("Выберите влияние и срочность.")
        result[key] = data[key]
    return result


def validate_article(data):
    result = {}
    for key, minimum, maximum in [("title", 5, 160), ("summary", 10, 500)]:
        value = data.get(key)
        if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
            raise ValueError("Проверьте название и описание инструкции.")
        result[key] = value.strip()
    valid_categories = {item[0] for item in CATEGORIES} | {"general"}
    if not isinstance(data.get("category"), str) or data["category"] not in valid_categories:
        raise ValueError("Выберите категорию инструкции.")
    result["category"] = data["category"]
    for key, maximum in [("keywords", 20), ("steps", 12)]:
        values = data.get(key)
        if not isinstance(values, list) or not 1 <= len(values) <= maximum:
            raise ValueError("Добавьте ключевые слова и шаги решения.")
        if any(not isinstance(v, str) or not 1 <= len(v.strip()) <= 500 for v in values):
            raise ValueError("Пункты инструкции должны содержать от 1 до 500 символов.")
        result[key] = list(dict.fromkeys(v.strip() for v in values))
    return result
