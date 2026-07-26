# -*- coding: utf-8 -*-
"""tests/test_api.py — интеграционные тесты API-эндпоинтов (СЛОЙ 4) и SIAR-интеграции.

Данные — синтетический, но реалистичный минимальный снапшот, засеянный
напрямую SQL-ом (без парсинга xlsx/pdf, чтобы тесты были быстрыми и не
зависели от реальных исходных файлов). Обоснования/рекомендации в фикстуре
считаются той же функцией siar.rules.evaluate(), что использует прод-загрузчик
— так тест одновременно проверяет архитектурный инвариант «API не порождает
и не переформулирует текст заново, а отдаёт то, что уже посчитал код».
"""
from __future__ import annotations

import datetime as dt

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from siar.rules import EntityKind, Zone, evaluate

pytestmark = pytest.mark.usefixtures("api_app")


# ---------------------------------------------------------------------------
# Засев данных: один прогон ml + siar_osf + siar_region + монитор.
# ---------------------------------------------------------------------------

OSF_ENTITY = "Федерация спортивной борьбы России"
OSF_MODEL_NAME = "Спортивная Борьба"
REGION_ENTITY = "Москва"


@pytest.fixture(scope="session")
def seeded(pg_dsn):
    conn = psycopg.connect(pg_dsn, row_factory=dict_row, autocommit=True)
    cur = conn.cursor()

    def new_run(kind, model_version=None):
        cur.execute(
            "INSERT INTO antidoping.runs (run_kind, model_version, rules_version) "
            "VALUES (%s, %s, 'v2') RETURNING run_id",
            (kind, model_version),
        )
        return cur.fetchone()["run_id"]

    def add_input(run_id, role, name="synthetic.xlsx", n=1):
        cur.execute(
            "INSERT INTO antidoping.run_inputs (run_id, file_role, file_name, sha256, row_count) "
            "VALUES (%s, %s, %s, %s, %s)",
            (run_id, role, name, "0" * 64, n),
        )

    # ── прогон 1 (более старый) — модель + два SIAR-снапшота ──
    ml_run_1 = new_run("ml", "test-v1")
    add_input(ml_run_1, "registry_xlsx")
    cur.execute(
        "INSERT INTO antidoping.predictions "
        "(run_id, sport, region, target_year, target_quarter, proba, zone, reason, "
        " lag_1q, lag_2q, rolling_mean_8q, rolling_sum_4q) VALUES "
        "(%s,%s,%s,2026,1,0.15,'RED','всплеск последних двух кварталов',0,1,0.1,1)",
        (ml_run_1, OSF_MODEL_NAME, REGION_ENTITY),
    )
    cur.execute("SELECT antidoping.publish_run(%s)", (ml_run_1,))

    a1 = evaluate(EntityKind.OSF, Zone.RED, 70, reason="всплеск последних двух кварталов",
                  unmet_criteria=("Стратегия",), object_name=OSF_ENTITY)
    siar_osf_1 = new_run("siar_osf", "test-v1")
    add_input(siar_osf_1, "osf_rating_pdf", n=1)
    cur.execute(
        "INSERT INTO antidoping.thresholds (run_id, scope, code, value, rules_version) VALUES "
        "(%s,'osf','high_threshold',80,'v2'), (%s,'osf','max_score',100,'v2')",
        (siar_osf_1, siar_osf_1),
    )
    cur.execute(
        "INSERT INTO antidoping.quadrant_results "
        "(run_id, kind, entity_name, matched_model_name, zone, proba, reason, state, priority, "
        " status, rating_score, rating_high, unmet_criteria, has_attention_zone, "
        " justification, recommendation, risk_rank, siar_version) VALUES "
        "(%s,'osf',%s,%s,'RED',0.15,'всплеск последних двух кварталов','A',1,NULL,"
        " 70,false,%s,false,%s,%s,1,'v2')",
        (siar_osf_1, OSF_ENTITY, OSF_MODEL_NAME, list(a1.unmet_criteria),
         a1.justification, a1.recommendation),
    )
    cur.execute(
        "INSERT INTO antidoping.rating_criteria "
        "(run_id, kind, entity_name, criterion_code, criterion_kind, value, is_met, sort_order) "
        "VALUES (%s,'osf',%s,'Стратегия','base',0,false,0)",
        (siar_osf_1, OSF_ENTITY),
    )
    cur.execute("SELECT antidoping.publish_run(%s)", (siar_osf_1,))

    b1 = evaluate(EntityKind.REGION, Zone.RED, 120, reason="всплеск последних двух кварталов",
                  unmet_criteria=("Блок 1",), object_name=REGION_ENTITY)
    siar_region_1 = new_run("siar_region", "test-v1")
    add_input(siar_region_1, "region_rating_xlsx", n=1)
    cur.execute(
        "INSERT INTO antidoping.thresholds (run_id, scope, code, value, rules_version) VALUES "
        "(%s,'region','high_threshold',130,'v2'), (%s,'region','max_score',190,'v2')",
        (siar_region_1, siar_region_1),
    )
    cur.execute(
        "INSERT INTO antidoping.quadrant_results "
        "(run_id, kind, entity_name, fo, matched_model_name, zone, proba, reason, state, "
        " priority, status, rating_score, rating_high, unmet_criteria, has_attention_zone, "
        " justification, recommendation, risk_rank, siar_version) VALUES "
        "(%s,'region',%s,'ЦФО',%s,'RED',0.15,'всплеск последних двух кварталов','A',1,NULL,"
        " 120,false,%s,false,%s,%s,1,'v2')",
        (siar_region_1, REGION_ENTITY, REGION_ENTITY, list(b1.unmet_criteria),
         b1.justification, b1.recommendation),
    )
    cur.execute("SELECT antidoping.publish_run(%s)", (siar_region_1,))

    # ── прогон 2 (более новый, другая версия модели) — динамика для истории ──
    ml_run_2 = new_run("ml", "test-v2")
    add_input(ml_run_2, "registry_xlsx")
    cur.execute(
        "INSERT INTO antidoping.predictions "
        "(run_id, sport, region, target_year, target_quarter, proba, zone, reason, "
        " lag_1q, lag_2q, rolling_mean_8q, rolling_sum_4q) VALUES "
        "(%s,%s,%s,2026,2,0.05,'GREEN',NULL,0,0,0.05,0)",
        (ml_run_2, OSF_MODEL_NAME, REGION_ENTITY),
    )
    cur.execute("SELECT antidoping.publish_run(%s)", (ml_run_2,))

    a2 = evaluate(EntityKind.OSF, Zone.GREEN, 85, object_name=OSF_ENTITY)
    siar_osf_2 = new_run("siar_osf", "test-v2")
    add_input(siar_osf_2, "osf_rating_pdf", n=1)
    cur.execute(
        "INSERT INTO antidoping.thresholds (run_id, scope, code, value, rules_version) VALUES "
        "(%s,'osf','high_threshold',80,'v2'), (%s,'osf','max_score',100,'v2')",
        (siar_osf_2, siar_osf_2),
    )
    cur.execute(
        "INSERT INTO antidoping.quadrant_results "
        "(run_id, kind, entity_name, matched_model_name, zone, proba, reason, state, priority, "
        " status, rating_score, rating_high, unmet_criteria, has_attention_zone, "
        " justification, recommendation, risk_rank, siar_version) VALUES "
        "(%s,'osf',%s,%s,'GREEN',0.05,NULL,'D',4,NULL,"
        " 85,true,'{}',false,%s,%s,1,'v2')",
        (siar_osf_2, OSF_ENTITY, OSF_MODEL_NAME, a2.justification, a2.recommendation),
    )
    cur.execute(
        "INSERT INTO antidoping.rating_criteria "
        "(run_id, kind, entity_name, criterion_code, criterion_kind, value, is_met, sort_order) "
        "VALUES (%s,'osf',%s,'Стратегия','base',1,true,0)",
        (siar_osf_2, OSF_ENTITY),
    )
    cur.execute("SELECT antidoping.publish_run(%s)", (siar_osf_2,))
    cur.execute(
        "INSERT INTO antidoping.unmatched (run_id, kind, side, name, reason) VALUES "
        "(%s,'osf','model',%s,%s)",
        (siar_osf_2, "Неизвестный Вид Спорта", "ни алиас, ни токены не дали соответствия"),
    )

    # ── АД-Монитор: два выпуска, оба потока ──
    monitor_run = new_run("monitor")
    today = dt.date.today()
    cur.execute(
        """
        INSERT INTO antidoping.flags
            (run_id, monitor_date, event_date, category, is_doping_event, scope,
             sport, country, is_ru, title, source_name, source_url,
             url_verified, confirmed, dedup_hash)
        VALUES
            (%(run_id)s, %(d)s, %(d)s, 'санкция', true, 'rf',
             %(sport)s, 'RU', true, 'Санкция РУСАДА', 'РУСАДА', 'https://rusada.ru/x',
             true, true, %(dedup)s)
        """,
        {"run_id": monitor_run, "d": today, "sport": OSF_MODEL_NAME, "dedup": "a" * 64},
    )
    cur.execute(
        """
        INSERT INTO antidoping.flags
            (run_id, monitor_date, event_date, category, is_doping_event, scope,
             country, is_ru, title, source_name, source_url,
             url_verified, confirmed, dedup_hash)
        VALUES
            (%(run_id)s, %(d)s, %(d)s, 'санкция', true, 'intl',
             'US', false, 'Санкция WADA', 'WADA', 'https://wada-ama.org/y',
             true, true, %(dedup)s)
        """,
        {"run_id": monitor_run, "d": today, "dedup": "b" * 64},
    )
    cur.execute(
        "INSERT INTO antidoping.flags (run_id, monitor_date, category, is_doping_event, "
        " scope, is_ru, title, source_url, url_verified, confirmed, expires_at, dedup_hash) "
        "VALUES (%s,%s,'неподтверждённый сигнал',false,'rf',false,'Слух','https://bad.example/z',"
        " false,false,%s,%s)",
        (monitor_run, today, today + dt.timedelta(days=2), "c" * 64),
    )
    cur.execute(
        "INSERT INTO antidoping.digest_narrative "
        "(run_id, monitor_date, window_from, window_to, scope, narrative, source_flag_ids) "
        "VALUES (%s,%s,%s,%s,'rf','Обзор российского потока за период.','{}')",
        (monitor_run, today, today, today),
    )

    conn.close()
    return {"osf_entity": OSF_ENTITY, "region_entity": REGION_ENTITY,
            "osf_expected_justification": a1.justification}


@pytest.fixture()
def client(api_app, seeded):
    with TestClient(api_app) as c:
        yield c


@pytest.fixture()
def auth_client(client):
    r = client.post("/api/v1/auth/login", json={"password": "test-only-password"})
    assert r.status_code == 200
    return client


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

def test_protected_route_requires_session(client):
    r = client.get("/api/v1/osf")
    assert r.status_code == 401


def test_login_wrong_password_rejected(client):
    r = client.post("/api/v1/auth/login", json={"password": "nope"})
    assert r.status_code == 401


def test_login_correct_password_grants_session(client):
    r = client.post("/api/v1/auth/login", json={"password": "test-only-password"})
    assert r.status_code == 200
    assert r.cookies.get("adp_session")
    status_r = client.get("/api/v1/auth/status")
    assert status_r.json() == {"authenticated": True}


def test_login_lockout_after_max_attempts(client, monkeypatch):
    import api.config as cfg
    monkeypatch.setattr(cfg, "LOGIN_MAX_ATTEMPTS", 3)
    for _ in range(3):
        client.post("/api/v1/auth/login", json={"password": "bad"})
    r = client.post("/api/v1/auth/login", json={"password": "bad"})
    assert r.status_code == 429


def test_health_does_not_require_session(client):
    assert client.get("/api/v1/health").status_code == 200


# ---------------------------------------------------------------------------
# osf / regions — карточки и списки
# ---------------------------------------------------------------------------

def test_osf_list_returns_current_run_only(auth_client):
    r = auth_client.get("/api/v1/osf")
    assert r.status_code == 200
    body = r.json()
    names = {item["entity_name"] for item in body["items"]}
    assert OSF_ENTITY in names
    # текущий прогон — GREEN/priority 4 (siar_osf_2), не RED/priority 1 (siar_osf_1)
    row = next(i for i in body["items"] if i["entity_name"] == OSF_ENTITY)
    assert row["zone"] == "GREEN"
    assert row["priority"] == 4


def test_osf_detail_justification_matches_rules_engine_verbatim(auth_client, seeded):
    r = auth_client.get(f"/api/v1/osf/{OSF_ENTITY}")
    assert r.status_code == 200
    body = r.json()
    # API не переформулирует текст — он идентичен siar.rules.evaluate() при тех же входах
    expected = evaluate(EntityKind.OSF, Zone.GREEN, 85, object_name=OSF_ENTITY)
    assert body["justification"] == expected.justification
    assert body["recommendation"] == expected.recommendation
    assert "{" not in body["justification"] and "}" not in body["justification"]


def test_osf_detail_404_for_unknown_entity(auth_client):
    r = auth_client.get("/api/v1/osf/Несуществующий Вид Спорта")
    assert r.status_code == 404


def test_osf_detail_includes_top_regions_drilldown(auth_client):
    r = auth_client.get(f"/api/v1/osf/{OSF_ENTITY}")
    body = r.json()
    assert isinstance(body["top_regions"], list)


def test_region_detail_includes_top_sports_drilldown(auth_client):
    r = auth_client.get(f"/api/v1/regions/{REGION_ENTITY}")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["top_sports"], list)


def test_osf_summary_shows_current_vs_previous(auth_client):
    r = auth_client.get("/api/v1/osf/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["current"]["4"] >= 1  # текущий прогон: siar_osf_2, GREEN/priority 4
    assert body["previous"]["1"] >= 1  # предыдущий прогон: siar_osf_1, RED/priority 1
    assert len(body["top5_priority1"]) >= 0


def test_regions_summary_available(auth_client):
    r = auth_client.get("/api/v1/regions/summary")
    assert r.status_code == 200
    assert r.json()["available"] is True


def test_region_list_filter_by_zone(auth_client):
    r = auth_client.get("/api/v1/regions", params={"zone": "RED"})
    assert r.status_code == 200
    assert all(i["zone"] == "RED" for i in r.json()["items"])


# ---------------------------------------------------------------------------
# history — архив по всем прогонам
# ---------------------------------------------------------------------------

def test_history_returns_both_runs_for_entity(auth_client):
    r = auth_client.get("/api/v1/history", params={"kind": "osf", "entity_name": OSF_ENTITY})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    zones = [row["zone"] for row in body["items"]]
    assert zones == ["RED", "GREEN"]  # хронологический порядок


def test_history_features_endpoint(auth_client):
    r = auth_client.get(
        "/api/v1/history/features", params={"kind": "osf", "entity_name": OSF_MODEL_NAME}
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2


# ---------------------------------------------------------------------------
# monitor — дайджест, лента, честные пробелы
# ---------------------------------------------------------------------------

def test_monitor_digest_splits_rf_and_intl(auth_client):
    r = auth_client.get("/api/v1/monitor/digest", params={"scope": "both"})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["narrative_rf"] == "Обзор российского потока за период."
    assert body["narrative_intl"] is None  # для intl narrative не засевали — честно пусто


def test_monitor_digest_unverified_and_source_unavailable_are_visible(auth_client):
    r = auth_client.get("/api/v1/monitor/digest")
    body = r.json()
    assert body["unverified_count"] >= 1
    assert body["source_unavailable_count"] >= 1


def test_monitor_unverified_endpoint_lists_gaps(auth_client):
    r = auth_client.get("/api/v1/monitor/unverified")
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_monitor_feed_scope_filter(auth_client):
    r = auth_client.get("/api/v1/monitor/feed", params={"scope": "rf"})
    assert r.status_code == 200
    assert all(i["scope"] == "rf" for i in r.json()["items"])


# ---------------------------------------------------------------------------
# feedback — пишет, но никогда не отдаёт обратно
# ---------------------------------------------------------------------------

def test_feedback_submit_returns_confirmation(auth_client):
    r = auth_client.post(
        "/api/v1/feedback", json={"section": "osf_card", "message": "Отличная карточка!"}
    )
    assert r.status_code == 201
    assert "записан" in r.json()["message"]


def test_feedback_has_no_read_endpoint(api_app):
    # Через OpenAPI-схему, а не app.routes напрямую — надёжно к внутренним
    # изменениям структуры роутинга между версиями FastAPI/Starlette.
    schema = api_app.openapi()
    feedback_paths = {p: ops for p, ops in schema["paths"].items() if p.startswith("/api/v1/feedback")}
    assert feedback_paths, "путь /api/v1/feedback не зарегистрирован"
    for path, operations in feedback_paths.items():
        assert "get" not in operations, f"{path} не должен поддерживать GET (пожелания не читаются обратно)"


# ---------------------------------------------------------------------------
# export — полные таблицы без предварительной фильтрации
# ---------------------------------------------------------------------------

def test_export_osf_csv_matches_list_count(auth_client):
    list_r = auth_client.get("/api/v1/osf")
    csv_r = auth_client.get("/api/v1/export/osf.csv")
    assert csv_r.status_code == 200
    assert csv_r.headers["content-type"].startswith("text/csv")
    lines = csv_r.text.strip().splitlines()
    assert len(lines) - 1 == list_r.json()["total"]  # минус строка заголовка


def test_export_bad_format_rejected(auth_client):
    r = auth_client.get("/api/v1/export/osf.json")
    assert r.status_code == 400


def test_export_unmatched_reflects_seeded_gap(auth_client):
    r = auth_client.get("/api/v1/export/unmatched.csv", params={"kind": "osf"})
    assert r.status_code == 200
    assert "Неизвестный Вид Спорта" in r.text


# ---------------------------------------------------------------------------
# unmatched — интерактивный JSON (не только выгрузка)
# ---------------------------------------------------------------------------

def test_unmatched_interactive_endpoint(auth_client):
    r = auth_client.get("/api/v1/unmatched", params={"kind": "osf"})
    assert r.status_code == 200
    body = r.json()
    names = [row["name"] for row in body["items"]]
    assert "Неизвестный Вид Спорта" in names
    assert all(row["side"] in ("model", "rating") for row in body["items"])


# ---------------------------------------------------------------------------
# history/criteria — разрез по критериям рейтинга по всем прогонам
# ---------------------------------------------------------------------------

def test_history_criteria_shows_change_across_runs(auth_client):
    r = auth_client.get(
        "/api/v1/history/criteria", params={"kind": "osf", "entity_name": OSF_ENTITY}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    is_met_values = [row["is_met"] for row in body["items"]]
    assert is_met_values == [False, True]  # хронологически: не выполнялся -> выполнился


# ---------------------------------------------------------------------------
# monitor_feed — точечный новостной контекст в карточке связки (не только счётчик)
# ---------------------------------------------------------------------------

def test_osf_detail_includes_monitor_feed_items(auth_client):
    r = auth_client.get(f"/api/v1/osf/{OSF_ENTITY}")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["monitor_feed"], list)
    assert len(body["monitor_feed"]) >= 1
    assert body["monitor_feed"][0]["source_url"].startswith("http")


def test_region_detail_monitor_feed_is_honestly_empty(auth_client):
    r = auth_client.get(f"/api/v1/regions/{REGION_ENTITY}")
    assert r.status_code == 200
    body = r.json()
    assert body["monitor_feed"] == []
    assert "monitor_feed_note" in body
