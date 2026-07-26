# -*- coding: utf-8 -*-
"""siar/rules.py — ЕДИНСТВЕННОЕ место правил SIAR v2.

Источник истины:
  * LOGIC.md §3 — утверждённые формулировки (менять только здесь и только
    по решению владельца проекта);
  * LOGIC.md §2 — правила зон модели (порядок RED → ORANGE → GREEN) и
    «наихудший сигнал» для агрегации по регионам;
  * LOGIC.md §4 — цвета зон/приоритетов и палитра;
  * LOGIC.md §5 — инварианты (продублированы как pytest в tests/test_rules.py).

Правила проекта (STRUCTURE.md «Правила для агента-кодера», п. 3):
  * пороги и шаблоны формулировок живут ТОЛЬКО в этом модуле; другие модули
    (ml/predict.py, siar/osf_report.py, siar/region_report.py, api, frontend)
    их импортируют, дублирование запрещено;
  * формулировки не генерируются «на лету»: одинаковые входы дают одинаковую
    фразу (evaluate() детерминирован).

Терминология входов (§3):
  RED/ORANGE  = «систематичность»
  GREEN       = «нет систематичности»
  NO_DATA     = «нет данных модели» (по приоритету ведёт себя как GREEN,
                но с особыми формулировками в состояниях C и D)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from numbers import Real
from typing import Iterable, Optional, Sequence, Union

__all__ = [
    "SIAR_VERSION",
    "Zone", "SYSTEMATIC_ZONES", "ZONE_SEVERITY", "worst_zone",
    "EntityKind", "RatingScale", "RATING_SCALES", "REGION_LOW_BAND",
    "RegionScoreBand", "region_score_band",
    "OSF_CRITERIA", "CRITERION_MET_MIN", "is_criterion_met",
    "ORANGE_ROLLING_MEAN_8Q_MIN", "ORANGE_ROLLING_SUM_4Q_MIN",
    "ZONE_REASONS", "assign_zone",
    "State", "STATE_PRIORITY", "PRIORITY_STATE", "STATUS_POTENTIAL_RISK",
    "JUSTIFICATION_A", "RECOMMENDATION_A",
    "JUSTIFICATION_B", "RECOMMENDATION_B",
    "JUSTIFICATION_C", "JUSTIFICATION_C_NO_DATA", "RECOMMENDATION_C",
    "JUSTIFICATION_D", "NO_DATA_NOTE", "RECOMMENDATION_D",
    "ATTENTION_ZONE_TEMPLATE",
    "MONITOR_SIGNALS_30D_TEMPLATE", "MONITOR_WINDOWS_DAYS",
    "format_monitor_signals",
    "ZONE_COLORS", "QUADRANT_COLORS", "PALETTE", "FONT_FAMILY",
    "PRIORITY_LABEL_TEMPLATE", "PRIORITY_SHORT_LABELS",
    "FORBIDDEN_HUMAN_TEXT_TOKENS", "assert_human_text_clean",
    "format_score", "format_criteria",
    "is_high_rating", "validate_score", "classify",
    "SiarAssessment", "evaluate",
]

SIAR_VERSION = "v2"


# ---------------------------------------------------------------------------
# Зоны модели (LOGIC.md §2, §3)
# ---------------------------------------------------------------------------

class Zone(str, Enum):
    """Зона риска модели. Зону задаёт ТОЛЬКО модель (LOGIC.md §1)."""

    RED = "RED"
    ORANGE = "ORANGE"
    GREEN = "GREEN"
    NO_DATA = "NO_DATA"

    @classmethod
    def coerce(cls, value: Union["Zone", str]) -> "Zone":
        if isinstance(value, cls):
            return value
        return cls(str(value).strip().upper())


#: RED/ORANGE = «систематичность» (§3)
SYSTEMATIC_ZONES = frozenset({Zone.RED, Zone.ORANGE})

#: Порядок «наихудшего сигнала» (§2): sort RED → ORANGE → GREEN, NO_DATA — последним.
ZONE_SEVERITY = {Zone.RED: 0, Zone.ORANGE: 1, Zone.GREEN: 2, Zone.NO_DATA: 3}


def worst_zone(zones: Iterable[Union[Zone, str]]) -> Zone:
    """Наихудший сигнал по набору зон (агрегация региона, LOGIC.md §2).

    Полный рецепт region_risks.csv: sort RED→ORANGE→GREEN, внутри зоны по
    proba по убыванию, groupby(Регион).first(). Сортировку по proba выполняет
    вызывающий код (region_report) — здесь только порядок зон.
    Пустой набор => NO_DATA.
    """
    coerced = [Zone.coerce(z) for z in zones]
    if not coerced:
        return Zone.NO_DATA
    return min(coerced, key=lambda z: ZONE_SEVERITY[z])


# ---------------------------------------------------------------------------
# Объекты оценки и пороги рейтингов РУСАДА (STRUCTURE.md: 80/100 ОСФ, 95/130/190 регионы)
# ---------------------------------------------------------------------------

class EntityKind(str, Enum):
    OSF = "osf"        # общероссийские спортивные федерации (рейтинг ОСФ)
    REGION = "region"  # субъекты РФ (рейтинг регионов)

    @classmethod
    def coerce(cls, value: Union["EntityKind", str]) -> "EntityKind":
        if isinstance(value, cls):
            return value
        return cls(str(value).strip().lower())


@dataclass(frozen=True)
class RatingScale:
    max_score: int        # максимум шкалы
    high_threshold: int   # порог высокого рейтинга: score >= high_threshold => «рейтинг высокий»


RATING_SCALES = {
    EntityKind.OSF: RatingScale(max_score=100, high_threshold=80),
    EntityKind.REGION: RatingScale(max_score=190, high_threshold=130),
}

#: Историческая нижняя граница баллов регионов (одноосевая логика v4: <95 / 95–129 / ≥130).
#: Одноосевая логика УПРАЗДНЕНА (LOGIC.md §2) — приоритет полоса НЕ определяет.
#: Сохранена для сверки парсинга рейтинга с эталоном 34/14/41 и для сводок по баллам.
REGION_LOW_BAND = 95


class RegionScoreBand(str, Enum):
    LOW = "<95"
    MID = "95–129"
    HIGH = "≥130"


def region_score_band(score: Real) -> RegionScoreBand:
    """Полоса балла рейтинга регионов — только для сверок/сводок, не для приоритета."""
    validate_score(score, EntityKind.REGION)
    if score < REGION_LOW_BAND:
        return RegionScoreBand.LOW
    if score < RATING_SCALES[EntityKind.REGION].high_threshold:
        return RegionScoreBand.MID
    return RegionScoreBand.HIGH


#: Критерии рейтинга ОСФ (LOGIC.md §2: 9 критериев, сумма до 100).
OSF_CRITERIA = (
    "Стратегия", "План-график", "Регионы", "Сайт", "Семинар",
    "Соглашение", "Допуск", "Мониторинг", "Инфо",
)

#: Критерий выполнен при значении >= 1 (LOGIC.md §2).
CRITERION_MET_MIN = 1


def is_criterion_met(value: Real) -> bool:
    return value >= CRITERION_MET_MIN


# ---------------------------------------------------------------------------
# Правила зон модели (LOGIC.md §2). Используются в ml/predict.py — импорт отсюда,
# чтобы пороги не дублировались. Порядок проверки RED → ORANGE → GREEN, ровно одна зона.
# ---------------------------------------------------------------------------

ORANGE_ROLLING_MEAN_8Q_MIN = 0.25
ORANGE_ROLLING_SUM_4Q_MIN = 2

#: Человекочитаемая {причина} зоны — из глосс LOGIC.md §2 (служебный жаргон
#: lag/rolling в тексты для людей не выносится, §3 «Запреты формулировок»).
ZONE_REASONS = {
    Zone.RED: "всплеск последних двух кварталов",
    Zone.ORANGE: "историческая повторяемость",
}


def assign_zone(
    lag_1q: Real,
    lag_2q: Real,
    rolling_mean_8q: Real,
    rolling_sum_4q: Real,
) -> tuple[Zone, Optional[str]]:
    """Зона модели по сработавшим правилам + её {причина}.

    RED    — lag_1q + lag_2q > 0 (всплеск последних двух кварталов);
    ORANGE — rolling_mean_8q >= 0.25 ИЛИ rolling_sum_4q >= 2 (историческая повторяемость);
    GREEN  — всё остальное (причина не нужна: GREEN в шаблон «Рисковый по модели» не попадает).
    """
    if lag_1q + lag_2q > 0:
        return Zone.RED, ZONE_REASONS[Zone.RED]
    if (rolling_mean_8q >= ORANGE_ROLLING_MEAN_8Q_MIN
            or rolling_sum_4q >= ORANGE_ROLLING_SUM_4Q_MIN):
        return Zone.ORANGE, ZONE_REASONS[Zone.ORANGE]
    return Zone.GREEN, None


# ---------------------------------------------------------------------------
# Состояния SIAR v2 и приоритеты (LOGIC.md §3)
# ---------------------------------------------------------------------------

class State(str, Enum):
    A = "A"  # систематичность + рейтинг ниже порога      -> Приоритет 1
    B = "B"  # систематичность + рейтинг высокий          -> Приоритет 2
    C = "C"  # нет систематичности + рейтинг ниже порога  -> Приоритет 3, «потенциальный риск»
    D = "D"  # нет систематичности + рейтинг высокий      -> Приоритет 4


STATE_PRIORITY = {State.A: 1, State.B: 2, State.C: 3, State.D: 4}
PRIORITY_STATE = {p: s for s, p in STATE_PRIORITY.items()}

#: Статус состояния C — единый маркер на всех экранах (LOGIC.md §3, §4).
STATUS_POTENTIAL_RISK = "потенциальный риск"


# ---------------------------------------------------------------------------
# УТВЕРЖДЁННЫЕ ФОРМУЛИРОВКИ — дословно LOGIC.md §3. МЕНЯТЬ ЗАПРЕЩЕНО
# без решения владельца проекта. Подстановки: {причина} — из модели,
# {критерии} — перечень невыполненных, {баллы} — балл рейтинга,
# {вид спорта/регион} — название объекта.
# ---------------------------------------------------------------------------

JUSTIFICATION_A = (
    "Рисковый по модели: {причина}. Усугубляется невыполнением критериев "
    "рейтинга РУСАДА: {критерии}"
)
RECOMMENDATION_A = (
    "Приоритизировать работу по невыполненным критериям рейтинга; "
    "выстроить системную антидопинговую работу совместно с федерацией/регионом"
)

JUSTIFICATION_B = (
    "Рисковый по модели: {причина}; при этом антидопинговая работа по "
    "рейтингу РУСАДА на высоком уровне ({баллы})"
)
RECOMMENDATION_B = (
    "Усилить антидопинговое образование: семинары и вебинары для "
    "спортсменов и персонала; адресные информационные кампании в виде "
    "спорта / регионе; беседы с заинтересованными сторонами; совместный "
    "план профилактики с федерацией; усиленный мониторинг ситуации"
)

JUSTIFICATION_C = (
    "По истории нарушений {вид спорта/регион} рисковым не является, однако "
    "из-за невыполнения критериев рейтинга РУСАДА ({критерии}) может стать "
    "рисковым — антидопинговая работа не проводится или проводится недостаточно"
)
#: Вариант C для NO_DATA: начало обоснования заменяется на «Данных модели нет,
#: однако…», далее так же (LOGIC.md §3).
JUSTIFICATION_C_NO_DATA = (
    "Данных модели нет, однако из-за невыполнения критериев рейтинга РУСАДА "
    "({критерии}) может стать рисковым — антидопинговая работа не проводится "
    "или проводится недостаточно"
)
RECOMMENDATION_C = (
    "Приоритизировать работу по невыполненным критериям рейтинга; "
    "превентивная работа с федерацией и регионом"
)

JUSTIFICATION_D = (
    "По истории нарушений рисковым не является; антидопинговая работа по "
    "рейтингу РУСАДА на высоком уровне ({баллы})"
)
#: Оговорка для D при NO_DATA — добавляется к обоснованию (LOGIC.md §3).
NO_DATA_NOTE = "данных модели нет"
RECOMMENDATION_D = "Поддерживать текущий уровень; плановый мониторинг ситуации"

#: Рейтинг высокий, но есть невыполненные критерии — добавляется к обоснованию
#: B/D; приоритет НЕ меняет (LOGIC.md §3).
ATTENTION_ZONE_TEMPLATE = "Зона внимания: {критерии}"

#: Доп-критерий из мониторинга: зону и приоритет НЕ меняет, считает код, не LLM.
#: Отображение в карточках и ховерах (LOGIC.md §3).
MONITOR_SIGNALS_30D_TEMPLATE = "Сигналы мониторинга: {N} за 30 дней"
MONITOR_WINDOWS_DAYS = (30, 90)

# Технические соединители при сборке составных обоснований (не являются
# утверждёнными фразами; сами фрагменты §3 не изменяются).
_SENTENCE_JOIN = ". "
_CLAUSE_JOIN = "; "


def format_monitor_signals(n_30d: int) -> str:
    """«Сигналы мониторинга: N за 30 дней» — для карточек и ховеров."""
    return _fill(MONITOR_SIGNALS_30D_TEMPLATE, {"N": str(int(n_30d))})


# ---------------------------------------------------------------------------
# Представление (LOGIC.md §4): цвета и палитра — единый визуальный язык
# от Excel до веб-платформы. Scatter/квадранты красятся по приоритетам,
# бары и Excel — по зонам; не смешивать.
# ---------------------------------------------------------------------------

ZONE_COLORS = {
    Zone.RED: "#DC2626",
    Zone.ORANGE: "#F59E0B",
    Zone.GREEN: "#10B981",
    Zone.NO_DATA: "#94A3B8",
}

QUADRANT_COLORS = {1: "#DC2626", 2: "#F59E0B", 3: "#3B82F6", 4: "#10B981"}

PALETTE = {"INK": "#0F2D52", "SUB": "#7C8DA6", "GRID": "#EEF2F7"}
FONT_FAMILY = "Inter"

PRIORITY_LABEL_TEMPLATE = "Приоритет {n}"
PRIORITY_SHORT_LABELS = {1: "П1", 2: "П2", 3: "П3", 4: "П4"}


# ---------------------------------------------------------------------------
# Запреты формулировок (LOGIC.md §3): не упоминать тестирование в рекомендациях,
# не использовать служебный жаргон в текстах для людей.
# ---------------------------------------------------------------------------

FORBIDDEN_HUMAN_TEXT_TOKENS = ("тестирован", "ml_feed", "siar", "пайплайн", "proba")


def assert_human_text_clean(text: str) -> None:
    """Гард текстов для людей; используется тестами и может — отчётами."""
    lowered = text.lower()
    for token in FORBIDDEN_HUMAN_TEXT_TOKENS:
        if token in lowered:
            raise ValueError(
                f"Запрещённый токен «{token}» в тексте для людей: {text!r}"
            )


# ---------------------------------------------------------------------------
# Подстановка и форматирование
# ---------------------------------------------------------------------------

_KNOWN_PLACEHOLDERS = ("{причина}", "{критерии}", "{баллы}", "{вид спорта/регион}", "{N}")


def _fill(template: str, mapping: dict) -> str:
    """Детерминированная подстановка в утверждённый шаблон.

    str.replace вместо str.format — плейсхолдер «{вид спорта/регион}»
    не является валидным именем поля format(). После подстановки не должно
    остаться ни одного известного плейсхолдера.
    """
    result = template
    for key, value in mapping.items():
        result = result.replace("{" + key + "}", value)
    for placeholder in _KNOWN_PLACEHOLDERS:
        if placeholder in result:
            raise RuntimeError(
                f"Незаполненный плейсхолдер {placeholder} в шаблоне: {template!r}"
            )
    return result


def format_score(score: Real) -> str:
    """Значение {баллы}: целые без дробной части (80.0 -> «80»)."""
    if isinstance(score, Real) and float(score).is_integer():
        return str(int(score))
    return f"{float(score):g}"


def format_criteria(criteria: Sequence[str]) -> str:
    """Значение {критерии}: перечень невыполненных через запятую."""
    cleaned = [str(c).strip() for c in criteria if str(c).strip()]
    if not cleaned:
        raise ValueError("Список критериев для подстановки {критерии} пуст")
    return ", ".join(cleaned)


# ---------------------------------------------------------------------------
# Классификация и оценка
# ---------------------------------------------------------------------------

def validate_score(score: Real, kind: Union[EntityKind, str]) -> None:
    kind = EntityKind.coerce(kind)
    scale = RATING_SCALES[kind]
    if score is None or not isinstance(score, Real) or isinstance(score, bool):
        raise ValueError(f"Балл рейтинга обязателен и должен быть числом, получено: {score!r}")
    if not (0 <= float(score) <= scale.max_score):
        raise ValueError(
            f"Балл {score!r} вне шкалы 0..{scale.max_score} ({kind.value})"
        )


def is_high_rating(score: Real, kind: Union[EntityKind, str]) -> bool:
    """«Рейтинг высокий» = score >= порога (инвариант §5.5: >= порога — П2/П4)."""
    kind = EntityKind.coerce(kind)
    validate_score(score, kind)
    return float(score) >= RATING_SCALES[kind].high_threshold


def classify(zone: Union[Zone, str], score: Real, kind: Union[EntityKind, str]) -> State:
    """Состояние A/B/C/D по зоне модели и баллу рейтинга (LOGIC.md §3).

    NO_DATA по приоритету ведёт себя как «нет систематичности» (C/D)
    с особыми формулировками — их собирает evaluate().
    """
    zone = Zone.coerce(zone)
    high = is_high_rating(score, kind)
    if zone in SYSTEMATIC_ZONES:
        return State.B if high else State.A
    return State.D if high else State.C


@dataclass(frozen=True)
class SiarAssessment:
    """Результат SIAR v2 для одной строки (машиночитаемый: БД/API/отчёты)."""

    kind: EntityKind
    zone: Zone
    score: float
    state: State
    priority: int
    status: Optional[str]           # «потенциальный риск» только в C
    justification: str              # обоснование — человеческий текст
    recommendation: str             # рекомендация — человеческий текст
    reason: Optional[str]           # {причина} из модели (RED/ORANGE)
    unmet_criteria: tuple = field(default_factory=tuple)
    has_attention_zone: bool = False  # «Зона внимания» добавлена к B/D

    @property
    def priority_label(self) -> str:
        return PRIORITY_LABEL_TEMPLATE.replace("{n}", str(self.priority))

    @property
    def priority_short(self) -> str:
        return PRIORITY_SHORT_LABELS[self.priority]

    def as_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "zone": self.zone.value,
            "score": self.score,
            "state": self.state.value,
            "priority": self.priority,
            "priority_label": self.priority_label,
            "status": self.status,
            "justification": self.justification,
            "recommendation": self.recommendation,
            "reason": self.reason,
            "unmet_criteria": list(self.unmet_criteria),
            "has_attention_zone": self.has_attention_zone,
            "siar_version": SIAR_VERSION,
        }


def evaluate(
    kind: Union[EntityKind, str],
    zone: Union[Zone, str],
    score: Real,
    *,
    reason: Optional[str] = None,
    unmet_criteria: Sequence[str] = (),
    object_name: Optional[str] = None,
) -> SiarAssessment:
    """Единая точка вынесения приоритета, обоснования и рекомендации.

    Аргументы:
      kind          — EntityKind.OSF | EntityKind.REGION;
      zone          — зона модели (задаёт только модель, LOGIC.md §1);
      score         — балл рейтинга РУСАДА (порог: ОСФ 80, регионы 130);
      reason        — {причина} из модели; ОБЯЗАТЕЛЬНА для RED/ORANGE;
      unmet_criteria— невыполненные критерии рейтинга; ОБЯЗАТЕЛЬНЫ для
                      состояний A и C (шаблоны требуют {критерии});
      object_name   — {вид спорта/регион}; ОБЯЗАТЕЛЕН для C при zone=GREEN
                      (в C-варианте NO_DATA плейсхолдер объекта отсутствует).

    Детерминированность: одинаковые входы -> идентичные строки (LOGIC.md §1).
    """
    kind = EntityKind.coerce(kind)
    zone = Zone.coerce(zone)
    validate_score(score, kind)

    unmet = tuple(str(c).strip() for c in unmet_criteria if str(c).strip())
    state = classify(zone, score, kind)
    score_str = format_score(score)

    if state in (State.A, State.B):
        if not reason or not str(reason).strip():
            raise ValueError(
                "Для зон RED/ORANGE обязательна {причина} из модели (LOGIC.md §3)"
            )
        reason = str(reason).strip()

    if state in (State.A, State.C) and not unmet:
        raise ValueError(
            f"Состояние {state.value}: рейтинг ниже порога, шаблон требует "
            "{критерии} — передайте невыполненные критерии"
        )

    criteria_str = format_criteria(unmet) if unmet else None

    if state is State.A:
        justification = _fill(
            JUSTIFICATION_A, {"причина": reason, "критерии": criteria_str}
        )
        recommendation = RECOMMENDATION_A

    elif state is State.B:
        justification = _fill(JUSTIFICATION_B, {"причина": reason, "баллы": score_str})
        recommendation = RECOMMENDATION_B

    elif state is State.C:
        if zone is Zone.NO_DATA:
            justification = _fill(JUSTIFICATION_C_NO_DATA, {"критерии": criteria_str})
        else:
            if not object_name or not str(object_name).strip():
                raise ValueError(
                    "Состояние C: шаблон требует {вид спорта/регион} — "
                    "передайте object_name"
                )
            justification = _fill(
                JUSTIFICATION_C,
                {"вид спорта/регион": str(object_name).strip(), "критерии": criteria_str},
            )
        recommendation = RECOMMENDATION_C

    else:  # State.D
        justification = _fill(JUSTIFICATION_D, {"баллы": score_str})
        if zone is Zone.NO_DATA:
            justification = justification + _CLAUSE_JOIN + NO_DATA_NOTE
        recommendation = RECOMMENDATION_D

    has_attention = state in (State.B, State.D) and bool(unmet)
    if has_attention:
        justification = (
            justification
            + _SENTENCE_JOIN
            + _fill(ATTENTION_ZONE_TEMPLATE, {"критерии": criteria_str})
        )

    return SiarAssessment(
        kind=kind,
        zone=zone,
        score=float(score),
        state=state,
        priority=STATE_PRIORITY[state],
        status=STATUS_POTENTIAL_RISK if state is State.C else None,
        justification=justification,
        recommendation=recommendation,
        reason=reason if state in (State.A, State.B) else (reason or None),
        unmet_criteria=unmet,
        has_attention_zone=has_attention,
    )
