# -*- coding: utf-8 -*-
"""Тесты siar/rules.py.

Покрывают:
  * дословность утверждённых формулировок LOGIC.md §3 (эталонные строки
    НАМЕРЕННО продублированы здесь: тесты фиксируют соответствие rules.py
    документу; запрет дублирования касается production-модулей);
  * инварианты LOGIC.md §5 (п. 3, 4, 5) — нарушение = красная сборка;
  * правила зон модели §2 (порядок RED → ORANGE → GREEN, ровно одна зона);
  * NO_DATA-варианты, «Зона внимания», статус «потенциальный риск»;
  * запреты формулировок §3 и детерминированность (§1).

Запуск: `pytest tests/` или автономно `python tests/test_rules.py`.
"""

import itertools
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # автономный запуск

from siar import rules as r
from siar.rules import EntityKind, State, Zone


@contextmanager
def raises(exc_type):
    """Мини-аналог pytest.raises (в контейнере сборки pytest может отсутствовать)."""
    try:
        yield
    except exc_type:
        return
    raise AssertionError(f"ожидалось исключение {exc_type.__name__}")


# ---------------------------------------------------------------------------
# Вспомогательные данные
# ---------------------------------------------------------------------------

REASON = r.ZONE_REASONS[Zone.ORANGE]
CRIT_OSF = ("Сайт", "Семинар")
CRIT_REGION = ("Блок 1. Организационные меры",)

KIND_FIXTURES = {
    EntityKind.OSF: dict(threshold=80, max_score=100, criteria=CRIT_OSF,
                         object_name="Плавание"),
    EntityKind.REGION: dict(threshold=130, max_score=190, criteria=CRIT_REGION,
                            object_name="Республика Татарстан"),
}


def _evaluate(kind, zone, score, unmet=None, object_name=None):
    fx = KIND_FIXTURES[kind]
    below = score < fx["threshold"]
    if unmet is None:
        unmet = fx["criteria"] if below else ()
    return r.evaluate(
        kind, zone, score,
        reason=REASON,
        unmet_criteria=unmet,
        object_name=object_name or fx["object_name"],
    )


# ---------------------------------------------------------------------------
# §3 — дословность утверждённых формулировок
# ---------------------------------------------------------------------------

def test_templates_verbatim_logic_md_p3():
    assert r.JUSTIFICATION_A == (
        "Рисковый по модели: {причина}. Усугубляется невыполнением критериев "
        "рейтинга РУСАДА: {критерии}"
    )
    assert r.RECOMMENDATION_A == (
        "Приоритизировать работу по невыполненным критериям рейтинга; "
        "выстроить системную антидопинговую работу совместно с федерацией/регионом"
    )
    assert r.JUSTIFICATION_B == (
        "Рисковый по модели: {причина}; при этом антидопинговая работа по "
        "рейтингу РУСАДА на высоком уровне ({баллы})"
    )
    assert r.RECOMMENDATION_B == (
        "Усилить антидопинговое образование: семинары и вебинары для "
        "спортсменов и персонала; адресные информационные кампании в виде "
        "спорта / регионе; беседы с заинтересованными сторонами; совместный "
        "план профилактики с федерацией; усиленный мониторинг ситуации"
    )
    assert r.JUSTIFICATION_C == (
        "По истории нарушений {вид спорта/регион} рисковым не является, однако "
        "из-за невыполнения критериев рейтинга РУСАДА ({критерии}) может стать "
        "рисковым — антидопинговая работа не проводится или проводится недостаточно"
    )
    assert r.JUSTIFICATION_C_NO_DATA == (
        "Данных модели нет, однако из-за невыполнения критериев рейтинга РУСАДА "
        "({критерии}) может стать рисковым — антидопинговая работа не проводится "
        "или проводится недостаточно"
    )
    assert r.RECOMMENDATION_C == (
        "Приоритизировать работу по невыполненным критериям рейтинга; "
        "превентивная работа с федерацией и регионом"
    )
    assert r.JUSTIFICATION_D == (
        "По истории нарушений рисковым не является; антидопинговая работа по "
        "рейтингу РУСАДА на высоком уровне ({баллы})"
    )
    assert r.RECOMMENDATION_D == "Поддерживать текущий уровень; плановый мониторинг ситуации"
    assert r.NO_DATA_NOTE == "данных модели нет"
    assert r.ATTENTION_ZONE_TEMPLATE == "Зона внимания: {критерии}"
    assert r.MONITOR_SIGNALS_30D_TEMPLATE == "Сигналы мониторинга: {N} за 30 дней"
    assert r.STATUS_POTENTIAL_RISK == "потенциальный риск"


def test_state_priority_mapping():
    assert r.STATE_PRIORITY == {State.A: 1, State.B: 2, State.C: 3, State.D: 4}
    assert r.PRIORITY_STATE[1] is State.A and r.PRIORITY_STATE[4] is State.D


# ---------------------------------------------------------------------------
# Пороги и шкалы (STRUCTURE.md: 80/100 ОСФ, 95/130/190 регионы)
# ---------------------------------------------------------------------------

def test_rating_scales():
    assert r.RATING_SCALES[EntityKind.OSF].max_score == 100
    assert r.RATING_SCALES[EntityKind.OSF].high_threshold == 80
    assert r.RATING_SCALES[EntityKind.REGION].max_score == 190
    assert r.RATING_SCALES[EntityKind.REGION].high_threshold == 130
    assert r.REGION_LOW_BAND == 95


def test_osf_criteria_list():
    assert r.OSF_CRITERIA == (
        "Стратегия", "План-график", "Регионы", "Сайт", "Семинар",
        "Соглашение", "Допуск", "Мониторинг", "Инфо",
    )
    assert len(r.OSF_CRITERIA) == 9
    assert r.CRITERION_MET_MIN == 1
    assert r.is_criterion_met(1) and r.is_criterion_met(2)
    assert not r.is_criterion_met(0)


def test_region_score_bands():
    # Полосы баллов v4 — для сверки с эталоном 34/14/41, приоритет не задают.
    assert r.region_score_band(0) is r.RegionScoreBand.LOW
    assert r.region_score_band(94) is r.RegionScoreBand.LOW
    assert r.region_score_band(95) is r.RegionScoreBand.MID
    assert r.region_score_band(129) is r.RegionScoreBand.MID
    assert r.region_score_band(130) is r.RegionScoreBand.HIGH
    assert r.region_score_band(190) is r.RegionScoreBand.HIGH


# ---------------------------------------------------------------------------
# §2 — правила зон модели: порядок RED → ORANGE → GREEN, ровно одна зона
# ---------------------------------------------------------------------------

def test_assign_zone_rules():
    assert r.assign_zone(1, 0, 0, 0) == (Zone.RED, "всплеск последних двух кварталов")
    assert r.assign_zone(0, 2, 0, 0)[0] is Zone.RED
    assert r.assign_zone(0, 0, 0.25, 0) == (Zone.ORANGE, "историческая повторяемость")
    assert r.assign_zone(0, 0, 0, 2)[0] is Zone.ORANGE
    assert r.assign_zone(0, 0, 0.24, 1) == (Zone.GREEN, None)
    assert r.assign_zone(0, 0, 0, 0) == (Zone.GREEN, None)
    # приоритет проверки: RED раньше ORANGE даже при сработавших rolling-правилах
    assert r.assign_zone(1, 1, 0.9, 5)[0] is Zone.RED


def test_worst_zone_ordering():
    assert r.worst_zone([Zone.GREEN, Zone.ORANGE, Zone.GREEN]) is Zone.ORANGE
    assert r.worst_zone(["green", "RED"]) is Zone.RED
    assert r.worst_zone([Zone.NO_DATA, Zone.GREEN]) is Zone.GREEN
    assert r.worst_zone([]) is Zone.NO_DATA
    assert r.ZONE_SEVERITY[Zone.RED] < r.ZONE_SEVERITY[Zone.ORANGE] \
        < r.ZONE_SEVERITY[Zone.GREEN] < r.ZONE_SEVERITY[Zone.NO_DATA]


# ---------------------------------------------------------------------------
# §5 — инварианты 3, 4, 5 на сетке входов
# ---------------------------------------------------------------------------

def _grid(kind):
    fx = KIND_FIXTURES[kind]
    t, mx = fx["threshold"], fx["max_score"]
    scores = [0, t // 2, t - 1, t, t + 1, mx]
    return itertools.product(list(Zone), scores)


def test_invariants_5_3_5_4_5_5():
    for kind in EntityKind:
        t = KIND_FIXTURES[kind]["threshold"]
        for zone, score in _grid(kind):
            a = _evaluate(kind, zone, score)
            # 5.3 — ровно одна зона и ровно один приоритет
            assert a.zone in Zone and a.state in State
            assert a.priority in (1, 2, 3, 4)
            assert a.priority == r.STATE_PRIORITY[a.state]
            # 5.4 — нет RED/ORANGE в П3–П4; нет GREEN (и NO_DATA) в П1–П2
            if a.priority in (3, 4):
                assert a.zone not in r.SYSTEMATIC_ZONES
            if a.priority in (1, 2):
                assert a.zone in r.SYSTEMATIC_ZONES
            # 5.5 — нет рейтинга >= порога в П1/П3; нет рейтинга < порога в П2/П4
            if a.priority in (1, 3):
                assert score < t
            if a.priority in (2, 4):
                assert score >= t
            # статус «потенциальный риск» — только состояние C
            assert (a.status == r.STATUS_POTENTIAL_RISK) == (a.state is State.C)
            # незаполненных плейсхолдеров не осталось
            assert "{" not in a.justification and "}" not in a.justification
            assert "{" not in a.recommendation and "}" not in a.recommendation


def test_boundary_score_equals_threshold_is_high():
    a = _evaluate(EntityKind.OSF, Zone.RED, 80)
    assert a.state is State.B and a.priority == 2
    b = _evaluate(EntityKind.REGION, Zone.GREEN, 130)
    assert b.state is State.D and b.priority == 4


def test_determinism_same_inputs_same_phrase():
    kw = dict(reason=REASON, unmet_criteria=CRIT_OSF, object_name="Плавание")
    a1 = r.evaluate(EntityKind.OSF, Zone.ORANGE, 55, **kw)
    a2 = r.evaluate(EntityKind.OSF, Zone.ORANGE, 55, **kw)
    assert a1 == a2 and a1.justification == a2.justification


# ---------------------------------------------------------------------------
# §3 — сборка текстов по состояниям
# ---------------------------------------------------------------------------

def test_state_A_full_text():
    a = r.evaluate(
        EntityKind.OSF, Zone.RED, 40,
        reason="всплеск последних двух кварталов",
        unmet_criteria=("Стратегия", "Сайт"),
    )
    assert a.state is State.A and a.priority == 1
    assert a.justification == (
        "Рисковый по модели: всплеск последних двух кварталов. Усугубляется "
        "невыполнением критериев рейтинга РУСАДА: Стратегия, Сайт"
    )
    assert a.recommendation == r.RECOMMENDATION_A
    assert a.status is None


def test_state_B_text_and_attention_zone():
    base = r.evaluate(EntityKind.OSF, Zone.ORANGE, 85, reason=REASON)
    assert base.state is State.B and base.priority == 2
    assert base.justification == (
        "Рисковый по модели: историческая повторяемость; при этом антидопинговая "
        "работа по рейтингу РУСАДА на высоком уровне (85)"
    )
    assert not base.has_attention_zone

    with_att = r.evaluate(
        EntityKind.OSF, Zone.ORANGE, 85, reason=REASON, unmet_criteria=("Сайт",)
    )
    assert with_att.priority == 2  # «Зона внимания» приоритет не меняет
    assert with_att.has_attention_zone
    assert with_att.justification.endswith(". Зона внимания: Сайт")


def test_state_C_text_and_status():
    a = r.evaluate(
        EntityKind.REGION, Zone.GREEN, 100,
        unmet_criteria=CRIT_REGION, object_name="Республика Татарстан",
    )
    assert a.state is State.C and a.priority == 3
    assert a.status == "потенциальный риск"
    assert a.justification == (
        "По истории нарушений Республика Татарстан рисковым не является, однако "
        "из-за невыполнения критериев рейтинга РУСАДА "
        "(Блок 1. Организационные меры) может стать рисковым — антидопинговая "
        "работа не проводится или проводится недостаточно"
    )
    assert a.recommendation == r.RECOMMENDATION_C


def test_state_C_no_data_replaces_beginning():
    a = r.evaluate(EntityKind.REGION, Zone.NO_DATA, 100, unmet_criteria=CRIT_REGION)
    assert a.state is State.C and a.priority == 3
    assert a.status == "потенциальный риск"
    assert a.justification.startswith("Данных модели нет, однако ")
    assert "{вид спорта/регион}" not in a.justification
    assert "По истории нарушений" not in a.justification


def test_state_D_text_no_data_and_attention():
    a = r.evaluate(EntityKind.REGION, Zone.GREEN, 150)
    assert a.state is State.D and a.priority == 4
    assert a.justification == (
        "По истории нарушений рисковым не является; антидопинговая работа по "
        "рейтингу РУСАДА на высоком уровне (150)"
    )
    nd = r.evaluate(EntityKind.REGION, Zone.NO_DATA, 150)
    assert nd.justification == a.justification + "; данных модели нет"

    nd_att = r.evaluate(
        EntityKind.REGION, Zone.NO_DATA, 150, unmet_criteria=("Блок 3",)
    )
    assert nd_att.priority == 4
    assert nd_att.justification == (
        a.justification + "; данных модели нет. Зона внимания: Блок 3"
    )


# ---------------------------------------------------------------------------
# Валидация входов
# ---------------------------------------------------------------------------

def test_reason_required_for_systematic_zones():
    with raises(ValueError):
        r.evaluate(EntityKind.OSF, Zone.RED, 40, unmet_criteria=CRIT_OSF)


def test_criteria_required_below_threshold():
    with raises(ValueError):
        r.evaluate(EntityKind.OSF, Zone.RED, 40, reason=REASON)  # A без критериев
    with raises(ValueError):
        r.evaluate(EntityKind.OSF, Zone.GREEN, 40, object_name="Бокс")  # C без критериев


def test_object_name_required_for_C_green():
    with raises(ValueError):
        r.evaluate(EntityKind.OSF, Zone.GREEN, 40, unmet_criteria=CRIT_OSF)


def test_score_validation():
    for bad in (None, -1, 101, "80"):
        with raises(ValueError):
            r.evaluate(EntityKind.OSF, Zone.GREEN, bad,
                       unmet_criteria=CRIT_OSF, object_name="Бокс")
    with raises(ValueError):
        r.evaluate(EntityKind.REGION, Zone.GREEN, 191,
                   unmet_criteria=CRIT_REGION, object_name="Регион")


# ---------------------------------------------------------------------------
# Форматтеры, запреты, представление (§3, §4)
# ---------------------------------------------------------------------------

def test_format_helpers():
    assert r.format_score(80) == "80"
    assert r.format_score(80.0) == "80"
    assert r.format_score(87.5) == "87.5"
    assert r.format_criteria((" Сайт ", "Семинар")) == "Сайт, Семинар"
    with raises(ValueError):
        r.format_criteria(("", "  "))
    assert r.format_monitor_signals(3) == "Сигналы мониторинга: 3 за 30 дней"
    assert r.MONITOR_WINDOWS_DAYS == (30, 90)


def test_forbidden_tokens_absent_in_human_texts():
    # «не упоминать тестирование в рекомендациях; не использовать служебный жаргон»
    for kind in EntityKind:
        for zone, score in _grid(kind):
            a = _evaluate(kind, zone, score)
            r.assert_human_text_clean(a.justification)
            r.assert_human_text_clean(a.recommendation)
    with raises(ValueError):
        r.assert_human_text_clean("усилить тестирование")
    with raises(ValueError):
        r.assert_human_text_clean("значение proba выросло")


def test_colors_and_palette():
    assert r.ZONE_COLORS == {
        Zone.RED: "#DC2626", Zone.ORANGE: "#F59E0B",
        Zone.GREEN: "#10B981", Zone.NO_DATA: "#94A3B8",
    }
    assert r.QUADRANT_COLORS == {1: "#DC2626", 2: "#F59E0B", 3: "#3B82F6", 4: "#10B981"}
    assert r.PALETTE == {"INK": "#0F2D52", "SUB": "#7C8DA6", "GRID": "#EEF2F7"}
    assert r.FONT_FAMILY == "Inter"
    assert r.PRIORITY_SHORT_LABELS == {1: "П1", 2: "П2", 3: "П3", 4: "П4"}


def test_as_dict_machine_readable():
    a = _evaluate(EntityKind.OSF, Zone.RED, 40)
    d = a.as_dict()
    assert d["zone"] == "RED" and d["priority"] == 1 and d["state"] == "A"
    assert d["priority_label"] == "Приоритет 1"
    assert d["siar_version"] == "v2"
    assert isinstance(d["unmet_criteria"], list)


# ---------------------------------------------------------------------------
# Автономный запуск (в контейнере сборки pytest может отсутствовать)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    total = len(tests)
    print(f"\n{total - failed}/{total} passed")
    sys.exit(1 if failed else 0)
