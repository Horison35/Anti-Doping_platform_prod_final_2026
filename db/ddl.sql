-- ============================================================================
-- db/ddl.sql — схема antidoping · Антидопинговая платформа поддержки решений
-- ============================================================================
-- Источник истины:
--   * STRUCTURE.md (СЛОЙ 3): состав таблиц — runs, registry_agg, predictions,
--     rating_criteria (длинная таблица), thresholds, quadrant_results,
--     matching_audit, unmatched, flags;
--   * LOGIC.md §2 — потоки и модель, §3 — SIAR v2, §5 — инварианты,
--     §7 — эксплуатация; siar/rules.py — словарь зон/состояний/приоритетов.
--
-- Правила проекта, соблюдённые в этой схеме:
--   * Пороги (80/130, 0.25/2 и т.д.) НЕ зашиты в DDL (STRUCTURE.md, п. 3:
--     правила живут только в siar/rules.py). Численные значения порогов
--     снапшотятся загрузчиком в таблицу thresholds на каждый прогон и
--     проверяются функцией validate_run(). В констрейнтах — только
--     структурный словарь (зоны, состояния, приоритеты) из rules.py;
--     при изменении словаря синхронизировать с rules.py.
--   * Инварианты LOGIC.md §5 существуют и на уровне БД: построчные — как
--     CHECK-констрейнты (имена ck_inv_*), межтабличные — в validate_run().
--     Публикация прогона (publish_run) невозможна при нарушении инварианта —
--     «выдача отчёта с нарушенным инвариантом запрещена кодом»
--     (STRUCTURE.md, п. 4).
--   * ФИО в БД не попадают (STRUCTURE.md, п. 8) — только агрегаты
--     вид спорта × регион; пофамильный уровень остаётся в исходных xlsx.
--   * Каждый прогон — снапшот: run_id + sha256 входных файлов + версия
--     модели (STRUCTURE.md, п. 9; LOGIC.md §5.8) — таблицы runs/run_inputs.
--
-- Требования: PostgreSQL 14+ (docker-compose: официальный образ postgres).
-- Скрипт идемпотентен: повторный запуск на существующей базе безопасен.
-- Выполнять целиком: psql "$DATABASE_URL" -f db/ddl.sql
-- ============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS antidoping;
SET LOCAL search_path = antidoping, public;

-- ----------------------------------------------------------------------------
-- Домены — структурный словарь из siar/rules.py (Zone, State, EntityKind).
-- Это машиночитаемый контракт (rules.SiarAssessment.as_dict), а не пороги.
-- ----------------------------------------------------------------------------

DO $$ BEGIN
    CREATE DOMAIN antidoping.sha256_hex AS text
        CHECK (VALUE ~ '^[0-9a-f]{64}$');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    -- rules.Zone: RED/ORANGE = «систематичность», GREEN — нет, NO_DATA — нет данных
    CREATE DOMAIN antidoping.zone_code AS text
        CHECK (VALUE IN ('RED', 'ORANGE', 'GREEN', 'NO_DATA'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    -- rules.State: A/B/C/D (LOGIC.md §3)
    CREATE DOMAIN antidoping.siar_state AS text
        CHECK (VALUE IN ('A', 'B', 'C', 'D'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    -- rules.EntityKind: osf | region
    CREATE DOMAIN antidoping.entity_kind AS text
        CHECK (VALUE IN ('osf', 'region'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE DOMAIN antidoping.priority_1_4 AS smallint
        CHECK (VALUE BETWEEN 1 AND 4);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE DOMAIN antidoping.proba_01 AS double precision
        CHECK (VALUE >= 0 AND VALUE <= 1);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- 1. runs — снапшоты прогонов (LOGIC.md §1 «Воспроизводимость», §5.8)
-- ============================================================================

CREATE TABLE IF NOT EXISTS runs (
    run_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_kind      text        NOT NULL,             -- 'ml' | 'siar_osf' | 'siar_region' |
                                                    -- 'registry_load' | 'monitor' | 'watcher' | 'full'
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    status        text        NOT NULL DEFAULT 'running'
                  CONSTRAINT ck_runs_status CHECK (status IN ('running', 'success', 'failed')),
    model_version text,                             -- версия ансамбля из ml/artifacts/meta.json
    rules_version text,                             -- rules.SIAR_VERSION ('v2')
    published_at  timestamptz,                      -- ставится ТОЛЬКО через publish_run()
    notes         text,
    CONSTRAINT ck_runs_finished CHECK (finished_at IS NULL OR finished_at >= started_at),
    CONSTRAINT ck_runs_publish_success CHECK (published_at IS NULL OR status = 'success')
);

COMMENT ON TABLE  runs IS
    'Снапшоты прогонов: каждый вывод платформы проверяем по входным данным (LOGIC.md §1). Витрины читают только published-прогоны.';
COMMENT ON COLUMN runs.model_version IS
    'Версия ансамбля CatBoost (ml/artifacts/meta.json). Обязательна для прогонов с predictions/quadrant_results — проверяет validate_run() (§5.8).';
COMMENT ON COLUMN runs.published_at IS
    'Момент публикации. Заполняется исключительно publish_run() после validate_run(): нарушен инвариант → публикации нет.';

-- ----------------------------------------------------------------------------
-- 1a. run_inputs — версии входных файлов прогона (run_id + sha256, §5.8)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS run_inputs (
    input_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       bigint      NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    file_role    text        NOT NULL,   -- 'registry_xlsx' | 'osf_rating_pdf' |
                                         -- 'region_rating_xlsx' | 'model_risks_csv' |
                                         -- 'region_risks_csv' | ...
    file_name    text        NOT NULL,
    sha256       antidoping.sha256_hex NOT NULL,
    edition_year smallint,               -- редакция рейтинга (watcher выбирает свежую по году)
    row_count    integer     CHECK (row_count IS NULL OR row_count >= 0),
    received_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ux_run_inputs_role UNIQUE (run_id, file_role)
);

COMMENT ON TABLE  run_inputs IS
    'Входные файлы прогона: file_role + sha256 (rusada_rating_watcher версионирует скачивания). Для рейтингов row_count = N источника — база инварианта полноты §5.1.';
COMMENT ON COLUMN run_inputs.row_count IS
    'Число содержательных строк источника (строки-заголовки уже отфильтрованы загрузчиком). Для osf_rating_pdf / region_rating_xlsx участвует в проверке §5.1.';

-- ============================================================================
-- 2. thresholds — снапшот порогов из siar/rules.py на прогон
-- ============================================================================
-- Значения НЕ задаются в DDL и НЕ имеют дефолтов: загрузчик копирует их из
-- rules.py (RATING_SCALES, REGION_LOW_BAND, ORANGE_*). Так пороги существуют
-- в одном месте кода, а в БД — только их аудиторский след по прогонам.

CREATE TABLE IF NOT EXISTS thresholds (
    run_id        bigint  NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    scope         text    NOT NULL,   -- 'osf' | 'region' | 'model' | 'monitor'
    code          text    NOT NULL,   -- 'high_threshold' | 'max_score' | 'low_band'
                                      -- | 'orange_rolling_mean_8q_min'
                                      -- | 'orange_rolling_sum_4q_min' | 'window_days_short' | ...
    value         numeric NOT NULL,
    source        text    NOT NULL DEFAULT 'siar/rules.py',
    rules_version text,
    PRIMARY KEY (run_id, scope, code)
);

COMMENT ON TABLE thresholds IS
    'Пороги, действовавшие в прогоне (копия констант siar/rules.py). validate_run() сверяет quadrant_results с high_threshold/max_score своего run_id — численные пороги не дублируются в констрейнтах.';

-- ============================================================================
-- 3. registry_agg — база дисквалификаций, агрегированная до сетки модели
-- ============================================================================
-- ВНИМАНИЕ: ФИО и любые персональные данные в эту таблицу не пишутся
-- (STRUCTURE.md, п. 8). Только агрегаты вид спорта × субъект РФ × квартал.

CREATE TABLE IF NOT EXISTS registry_agg (
    run_id       bigint   NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    sport        text     NOT NULL,   -- канонический вид спорта (после очистки как в ноутбуке модели)
    region       text     NOT NULL,   -- канонический субъект РФ
    year         smallint NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    quarter      smallint NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    violations   integer  NOT NULL CHECK (violations >= 0),
    period_start date GENERATED ALWAYS AS (make_date(year, (quarter - 1) * 3 + 1, 1)) STORED,
    PRIMARY KEY (run_id, sport, region, year, quarter)
);

COMMENT ON TABLE  registry_agg IS
    'Агрегат базы дисквалификаций (~2,3 тыс. записей с 2004 г.) по сетке вид × регион × квартал. «База — истина» (LOGIC.md §1); ФИО вычищены на входе.';
COMMENT ON COLUMN registry_agg.violations IS 'Число нарушений в ячейке сетки за квартал.';

-- ============================================================================
-- 4. predictions — прогон модели: связки вид × регион (LOGIC.md §2)
-- ============================================================================

CREATE TABLE IF NOT EXISTS predictions (
    run_id          bigint   NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    sport           text     NOT NULL,
    region          text     NOT NULL,
    target_year     smallint NOT NULL CHECK (target_year BETWEEN 2000 AND 2100),
    target_quarter  smallint NOT NULL CHECK (target_quarter BETWEEN 1 AND 4),
    proba           antidoping.proba_01 NOT NULL,  -- ансамблевая, НЕ калибрована (§2):
                                                   -- в интерфейсах — перцентили и зоны
    zone            antidoping.zone_code NOT NULL
                    CONSTRAINT ck_pred_zone_model CHECK (zone <> 'NO_DATA'),
    reason          text,                          -- {причина} зоны из rules.ZONE_REASONS
    -- сработавшие сигналы правил зон — для аудита и backtest.py (значения признаков):
    lag_1q          numeric,
    lag_2q          numeric,
    rolling_mean_8q numeric,
    rolling_sum_4q  numeric,
    PRIMARY KEY (run_id, sport, region, target_year, target_quarter),
    -- rules.assign_zone: у RED/ORANGE причина обязательна, у GREEN её нет
    CONSTRAINT ck_pred_reason CHECK (
        (zone IN ('RED', 'ORANGE')) = (reason IS NOT NULL)
    )
);

COMMENT ON TABLE  predictions IS
    'Выход ml/predict.py по связкам вид × регион на следующий квартал. NO_DATA в таблице не хранится — это отсутствие строки. Агрегаты model_risks/region_risks выводятся правилом «наихудший сигнал» (rules.worst_zone) и фиксируются в quadrant_results.';
COMMENT ON COLUMN predictions.proba IS
    'Сырая proba: показывать аналитику по клику; в интерфейсах — ранги/перцентили (LOGIC.md §2, §4). Метрика качества — Lift@K.';

-- ============================================================================
-- 5. rating_criteria — критерии рейтингов РУСАДА, длинная таблица
-- ============================================================================
-- Длинный формат (одна строка = один критерий одного объекта) переживает
-- пересмотр состава критериев БЕЗ миграций (STRUCTURE.md): новые критерии —
-- это новые значения criterion_code, а не новые колонки.

CREATE TABLE IF NOT EXISTS rating_criteria (
    run_id         bigint  NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    kind           antidoping.entity_kind NOT NULL,
    entity_name    text    NOT NULL,     -- ОСФ или субъект РФ (канонично, как в рейтинге)
    fo             text,                 -- федеральный округ (только kind='region')
    criterion_code text    NOT NULL,     -- ОСФ: 'Стратегия'…'Инфо' (rules.OSF_CRITERIA);
                                         -- регионы: '1.1 Ответственные/сайт' … '3.4 …'
    block          text,                 -- блок критериев регионов ('1'|'2'|'3'); у ОСФ NULL
    criterion_kind text    NOT NULL DEFAULT 'base'
                   CONSTRAINT ck_crit_kind CHECK (criterion_kind IN ('base', 'bonus', 'penalty')),
    value          numeric NOT NULL,
    is_met         boolean,              -- rules.is_criterion_met(value) для base; bonus/penalty — NULL
    sort_order     smallint,
    PRIMARY KEY (run_id, kind, entity_name, criterion_code),
    CONSTRAINT ck_crit_fo   CHECK (kind = 'region' OR fo IS NULL),
    CONSTRAINT ck_crit_met  CHECK ((criterion_kind = 'base') = (is_met IS NOT NULL))
);

COMMENT ON TABLE  rating_criteria IS
    'Разложенные критерии рейтингов РУСАДА по объектам (ОСФ: 9 критериев, сумма до 100; регионы: 3 блока, максимум 190 — LOGIC.md §2). bonus/penalty в «невыполненные» не входят (см. region_report).';
COMMENT ON COLUMN rating_criteria.is_met IS
    'Выполнен ли базовый критерий (заполняет загрузчик через rules.is_criterion_met; порог выполнения в DDL не дублируется).';

-- ============================================================================
-- 6. quadrant_results — итог SIAR v2 (машиночитаемый слой отчётов и API)
-- ============================================================================
-- Зеркало rules.SiarAssessment.as_dict() + колонок листов «Итог» /
-- «Матрица регионов». Формулировки justification/recommendation собирает
-- ТОЛЬКО код через rules.evaluate() — БД их хранит, но не порождает.

CREATE TABLE IF NOT EXISTS quadrant_results (
    result_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id              bigint  NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    kind                antidoping.entity_kind NOT NULL,
    entity_name         text    NOT NULL,           -- «Вид спорта (ОСФ)» / «Регион»
    fo                  text,                       -- только для регионов
    matched_model_name  text,                       -- имя со стороны модели (из аудита матчинга)

    zone                antidoping.zone_code NOT NULL,
    proba               antidoping.proba_01,        -- NULL при NO_DATA
    reason              text,                       -- {причина} модели (RED/ORANGE)

    state               antidoping.siar_state NOT NULL,
    priority            antidoping.priority_1_4 NOT NULL,
    status              text,                       -- rules.STATUS_POTENTIAL_RISK, только в C

    rating_score        numeric NOT NULL CHECK (rating_score >= 0),
    rating_high         boolean NOT NULL,           -- rules.is_high_rating(score, kind);
                                                    -- сверку с порогом прогона делает validate_run()
    rating_place        integer,

    unmet_criteria      text[],                     -- невыполненные критерии (перечень)
    has_attention_zone  boolean NOT NULL DEFAULT false,

    justification       text NOT NULL,              -- человеческий текст из rules.evaluate()
    recommendation      text NOT NULL,

    monitor_signals_30d integer CHECK (monitor_signals_30d >= 0),  -- доп-критерий §3,
    monitor_signals_90d integer CHECK (monitor_signals_90d >= 0),  -- считает код, не LLM

    risk_rank           integer CHECK (risk_rank >= 1),            -- «№» в итоговой таблице
    siar_version        text NOT NULL,              -- rules.SIAR_VERSION

    -- §5.3: ровно одна зона и ровно один приоритет на объект прогона
    CONSTRAINT ux_quadrant_entity UNIQUE (run_id, kind, entity_name),

    -- §3: состояние ↔ приоритет (A→1, B→2, C→3, D→4)
    CONSTRAINT ck_inv_state_priority CHECK (
        (state = 'A' AND priority = 1) OR (state = 'B' AND priority = 2) OR
        (state = 'C' AND priority = 3) OR (state = 'D' AND priority = 4)
    ),
    -- §3 + §5.4: систематичность (RED/ORANGE) ↔ A/B; GREEN/NO_DATA ↔ C/D.
    -- Вместе с ck_inv_state_priority исключает RED/ORANGE в П3–4 и GREEN в П1–2.
    CONSTRAINT ck_inv_zone_state CHECK (
        ((zone IN ('RED', 'ORANGE')) AND state IN ('A', 'B')) OR
        ((zone IN ('GREEN', 'NO_DATA')) AND state IN ('C', 'D'))
    ),
    -- §5.5 (структурно): высокий рейтинг ↔ П2/П4, ниже порога ↔ П1/П3.
    -- Численный порог не дублируется: rating_high считает rules.is_high_rating,
    -- совпадение с thresholds прогона контролирует validate_run().
    CONSTRAINT ck_inv_high_priority CHECK (
        (rating_high AND priority IN (2, 4)) OR (NOT rating_high AND priority IN (1, 3))
    ),
    -- §3: статус «потенциальный риск» — тогда и только тогда в состоянии C
    CONSTRAINT ck_status_only_c CHECK (
        (state = 'C') = (status IS NOT NULL)
    ),
    CONSTRAINT ck_status_value CHECK (status IS NULL OR status = 'потенциальный риск'),
    -- rules.evaluate: для RED/ORANGE обязательна {причина}; NO_DATA без proba
    CONSTRAINT ck_reason_systematic CHECK (zone NOT IN ('RED', 'ORANGE') OR reason IS NOT NULL),
    CONSTRAINT ck_proba_no_data     CHECK (zone <> 'NO_DATA' OR proba IS NULL),
    -- rules.evaluate: состояния A и C требуют непустой список {критерии}
    CONSTRAINT ck_criteria_low CHECK (
        state NOT IN ('A', 'C')
        OR (unmet_criteria IS NOT NULL AND cardinality(unmet_criteria) > 0)
    ),
    -- «Зона внимания» существует только при высоком рейтинге и непустых критериях (B/D)
    CONSTRAINT ck_attention CHECK (
        NOT has_attention_zone
        OR (rating_high AND unmet_criteria IS NOT NULL AND cardinality(unmet_criteria) > 0)
    ),
    -- ФО обязателен для регионов (парсер принимает строки только с ФО из FO_SET)
    -- и отсутствует у ОСФ; сигналы мониторинга ведутся по видам спорта (ОСФ)
    CONSTRAINT ck_fo_region_only CHECK ((kind = 'region') = (fo IS NOT NULL)),
    CONSTRAINT ck_monitor_osf_only CHECK (
        kind = 'osf' OR (monitor_signals_30d IS NULL AND monitor_signals_90d IS NULL)
    )
);

COMMENT ON TABLE quadrant_results IS
    'Итог SIAR v2 на прогон: одна строка = один ОСФ/регион. Построчные инварианты LOGIC.md §5 — CHECK-констрейнты ck_inv_*; межтабличные (§5.1, §5.5 численно, §5.8) — validate_run(). Обоснование целиком уходит в ховеры дашбордов (§4).';
COMMENT ON COLUMN quadrant_results.rating_high IS
    'True = «рейтинг высокий» (score ≥ порога своего kind). Значение считает код по rules.py; соответствие порогу, снапшоченному в thresholds, проверяет validate_run().';

CREATE UNIQUE INDEX IF NOT EXISTS ux_quadrant_rank
    ON quadrant_results (run_id, kind, risk_rank)
    WHERE risk_rank IS NOT NULL;

-- ============================================================================
-- 7. matching_audit — аудит матчинга модель ↔ рейтинг (§5.6)
-- ============================================================================

CREATE TABLE IF NOT EXISTS matching_audit (
    audit_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id      bigint NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    kind        antidoping.entity_kind NOT NULL,
    model_name  text   NOT NULL,          -- «Вид спорта (модель)» / «Регион (модель)»
    rating_name text,                     -- сопоставленное имя в рейтинге; NULL = не найден
    match_type  text   NOT NULL,          -- 'точный' | 'алиас' | 'морфологический' | 'токены' | 'нет' …
    confidence  numeric CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    zone        antidoping.zone_code,
    proba       antidoping.proba_01,
    note        text
);

COMMENT ON TABLE matching_audit IS
    'Каждый матч — в аудит с типом и уверенностью (LOGIC.md §5.6). Подстрочные совпадения запрещены логикой матчинга («бокс» ≠ «кикбоксинг»), морфология обязательна («плавание» ≈ «плавания») — это проверяют tests/, аудит даёт разбор по парам.';

-- ============================================================================
-- 8. unmatched — несопоставленные записи (лист «Не сопоставлено», §5.1)
-- ============================================================================

CREATE TABLE IF NOT EXISTS unmatched (
    unmatched_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       bigint NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    kind         antidoping.entity_kind NOT NULL,
    side         text   NOT NULL
                 CONSTRAINT ck_unmatched_side CHECK (side IN ('model', 'rating')),
    name         text   NOT NULL,
    reason       text   NOT NULL
);

COMMENT ON TABLE unmatched IS
    'Потери строк только явные, через аудит (LOGIC.md §1). side: «модель» отчётов → ''model'', «рейтинг» → ''rating''. Лист «Не сопоставлено» пишется даже пустым.';

-- ============================================================================
-- 9. flags — сигналы АД-Монитора (LOGIC.md §3 «доп-критерий», §5.7, §6)
-- ============================================================================
-- Хранится только то, что прошло верификацию кодом: первичный source_url
-- обязателен; сторонние агентские данные без первичного подтверждения
-- не публикуются вовсе (§5.7). Во признаки модели флаги НЕ входят (§2).

CREATE TABLE IF NOT EXISTS flags (
    flag_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          bigint REFERENCES runs(run_id) ON DELETE SET NULL,  -- прогон монитора
    monitor_date    date NOT NULL,                  -- дата выпуска мониторинга
    event_date      date,                           -- дата события (в окне выпуска, §5.7)
    category        text NOT NULL,                  -- 'санкция' | 'отстранение' | 'расследование' | …
    is_doping_event boolean NOT NULL DEFAULT false, -- считается в доп-критерий (санкции/отстранения/расследования)
    scope           text CHECK (scope IS NULL OR scope IN ('rf', 'intl')),  -- контракт v15: поток выпуска
    sport           text,                           -- канонический вид спорта (для связи с ОСФ)
    region          text,
    country         text,
    is_ru           boolean NOT NULL DEFAULT false, -- относится к российскому спорту
    title           text NOT NULL,
    summary         text,
    source_name     text,
    source_url      text NOT NULL
                    CONSTRAINT ck_flags_url CHECK (source_url ~* '^https?://'),
    url_verified    boolean NOT NULL DEFAULT false, -- source_url проверен кодом (§5.7)
    url_checked_at  timestamptz,
    confirmed       boolean NOT NULL DEFAULT false, -- подтверждено первичным источником
    expires_at      date,                           -- неподтверждённое снимается за два выпуска (§6)
    dedup_hash      antidoping.sha256_hex,
    payload         jsonb,                          -- полная запись контракта монитора (v15)
    created_at      timestamptz NOT NULL DEFAULT now(),
    -- подтверждённое обязано иметь проверенный первичный источник
    CONSTRAINT ck_flags_confirmed_verified CHECK (NOT confirmed OR url_verified),
    -- неподтверждённый сигнал живёт ограниченно; у подтверждённого срока нет
    CONSTRAINT ck_flags_expiry CHECK (confirmed OR expires_at IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_flags_dedup
    ON flags (dedup_hash) WHERE dedup_hash IS NOT NULL;

COMMENT ON TABLE  flags IS
    'Лента АД-Монитора: ранний сигнал до подтверждения базой (LOGIC.md §1). Витрина — v_flags_public (только url_verified и не истёкшие). Счётчики по видам спорта пишет код в quadrant_results.monitor_signals_*.';
COMMENT ON COLUMN flags.is_doping_event IS
    'True для событий, входящих в доп-критерий §3 (санкции, отстранения, расследования). Проставляет run_monitor.py по контракту, не БД.';
COMMENT ON COLUMN flags.scope IS
    'Поток выпуска по контракту ad_monitor_prompt_v15.md: rf — российский, intl — международный. NULL у старых/unverified записей без явного поля. Используется дашбордом для явного разделения двух потоков — не путать с is_ru (гражданство фигуранта).';

-- ============================================================================
-- Индексы под запросы API (фильтры зона/ФО/приоритет, срезы по видам/регионам)
-- ============================================================================

CREATE INDEX IF NOT EXISTS ix_quadrant_run_kind_priority
    ON quadrant_results (run_id, kind, priority);
CREATE INDEX IF NOT EXISTS ix_quadrant_run_kind_zone
    ON quadrant_results (run_id, kind, zone);
CREATE INDEX IF NOT EXISTS ix_quadrant_fo
    ON quadrant_results (run_id, fo) WHERE fo IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_predictions_sport  ON predictions (run_id, sport);
CREATE INDEX IF NOT EXISTS ix_predictions_region ON predictions (run_id, region);

CREATE INDEX IF NOT EXISTS ix_registry_sport_region
    ON registry_agg (sport, region, year, quarter);

CREATE INDEX IF NOT EXISTS ix_criteria_entity
    ON rating_criteria (run_id, kind, entity_name);

CREATE INDEX IF NOT EXISTS ix_audit_run_kind ON matching_audit (run_id, kind);
CREATE INDEX IF NOT EXISTS ix_unmatched_run  ON unmatched (run_id, kind);

CREATE INDEX IF NOT EXISTS ix_flags_sport_date ON flags (sport, event_date);
CREATE INDEX IF NOT EXISTS ix_flags_monitor    ON flags (monitor_date);

-- ============================================================================
-- Витрины для FastAPI (контракт dashboard.v1): всегда последний
-- ОПУБЛИКОВАННЫЙ прогон соответствующего среза + переключатель снапшотов.
-- ============================================================================

-- /api/v1/snapshots — переключатель снапшотов на дашбордах (LOGIC.md §4)
CREATE OR REPLACE VIEW v_snapshots AS
SELECT r.run_id,
       r.run_kind,
       r.started_at,
       r.finished_at,
       r.published_at,
       r.model_version,
       r.rules_version,
       (SELECT count(*) FROM quadrant_results q
         WHERE q.run_id = r.run_id AND q.kind = 'osf')    AS n_osf,
       (SELECT count(*) FROM quadrant_results q
         WHERE q.run_id = r.run_id AND q.kind = 'region') AS n_regions,
       (SELECT count(*) FROM run_inputs i
         WHERE i.run_id = r.run_id)                       AS n_inputs
FROM runs r
WHERE r.published_at IS NOT NULL
ORDER BY r.run_id DESC;

-- Индекс риска = перцентиль proba в текущем прогнозе, 0–100 (LOGIC.md §4).
-- NO_DATA (proba IS NULL) индекса не имеет.
CREATE OR REPLACE VIEW v_osf_current AS
WITH cur AS (
    SELECT max(r.run_id) AS run_id
    FROM runs r
    WHERE r.published_at IS NOT NULL
      AND EXISTS (SELECT 1 FROM quadrant_results q
                   WHERE q.run_id = r.run_id AND q.kind = 'osf')
),
q AS (
    SELECT qr.* FROM quadrant_results qr JOIN cur ON qr.run_id = cur.run_id
    WHERE qr.kind = 'osf'
),
p AS (
    SELECT result_id,
           round(100 * percent_rank() OVER (ORDER BY proba))::smallint AS risk_index
    FROM q WHERE proba IS NOT NULL
)
SELECT q.*, p.risk_index
FROM q LEFT JOIN p USING (result_id);

CREATE OR REPLACE VIEW v_regions_current AS
WITH cur AS (
    SELECT max(r.run_id) AS run_id
    FROM runs r
    WHERE r.published_at IS NOT NULL
      AND EXISTS (SELECT 1 FROM quadrant_results q
                   WHERE q.run_id = r.run_id AND q.kind = 'region')
),
q AS (
    SELECT qr.* FROM quadrant_results qr JOIN cur ON qr.run_id = cur.run_id
    WHERE qr.kind = 'region'
),
p AS (
    SELECT result_id,
           round(100 * percent_rank() OVER (ORDER BY proba))::smallint AS risk_index
    FROM q WHERE proba IS NOT NULL
)
SELECT q.*, p.risk_index
FROM q LEFT JOIN p USING (result_id);

-- «Сводка по ФО» (лист region_report): регионов, средний балл, приоритеты
CREATE OR REPLACE VIEW v_fo_summary AS
SELECT run_id,
       fo,
       count(*)                                   AS regions,
       round(avg(rating_score))::int              AS avg_score,
       count(*) FILTER (WHERE priority = 1)       AS p1,
       count(*) FILTER (WHERE priority = 2)       AS p2,
       count(*) FILTER (WHERE priority = 3)       AS p3,
       count(*) FILTER (WHERE priority = 4)       AS p4,
       count(*) FILTER (WHERE zone = 'RED')       AS zone_red,
       count(*) FILTER (WHERE zone = 'ORANGE')    AS zone_orange,
       count(*) FILTER (WHERE zone = 'GREEN')     AS zone_green,
       count(*) FILTER (WHERE zone = 'NO_DATA')   AS zone_no_data
FROM quadrant_results
WHERE kind = 'region'
GROUP BY run_id, fo;

-- /api/v1/flags — публикуемая лента: только верифицированные и не истёкшие
CREATE OR REPLACE VIEW v_flags_public AS
SELECT *
FROM flags
WHERE url_verified
  AND (confirmed OR expires_at IS NULL OR expires_at >= current_date);

-- Счётчики «Сигналы мониторинга: N за 30 дней» по видам спорта.
-- Окна 30/90 = rules.MONITOR_WINDOWS_DAYS; при изменении констант в rules.py
-- синхронизировать здесь. Первичное хранение счётчиков на момент прогона —
-- quadrant_results.monitor_signals_*, эта витрина — «живое» значение для ленты.
-- GROUP BY lower(sport): АД-Монитор пишет вид спорта обычным словом («хоккей»),
-- а связки ОСФ сопоставляются со своим регистром («Хоккей») — без lower() с
-- обеих сторон (см. api/routers/osf.py) одна и та же дисциплина, записанная
-- в разных прогонах с разным регистром, расползлась бы на несколько строк
-- и часть сигналов молча терялась бы при поиске по точному регистру.
CREATE OR REPLACE VIEW v_monitor_signals AS
SELECT lower(sport) AS sport,
       count(*) FILTER (WHERE event_date >= current_date - 30) AS signals_30d,
       count(*) FILTER (WHERE event_date >= current_date - 90) AS signals_90d
FROM flags
WHERE confirmed
  AND is_doping_event
  AND is_ru
  AND sport IS NOT NULL
GROUP BY lower(sport);

-- ============================================================================
-- Инварианты уровня прогона: validate_run() + публикация через publish_run()
-- ============================================================================

CREATE OR REPLACE FUNCTION validate_run(p_run_id bigint)
RETURNS void
LANGUAGE plpgsql
SET search_path = antidoping, pg_temp
AS $fn$
DECLARE
    v_run       runs%ROWTYPE;
    v_problems  text[] := '{}';
    v_kind      text;
    v_cnt       bigint;
    v_expected  integer;
    v_bad       bigint;
BEGIN
    SELECT * INTO v_run FROM runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'validate_run: прогон % не найден', p_run_id;
    END IF;

    -- §5.8: прогон привязан к снапшоту входных файлов (sha256)…
    IF NOT EXISTS (SELECT 1 FROM run_inputs WHERE run_id = p_run_id) THEN
        v_problems := v_problems ||
            '§5.8: нет ни одного входного файла в run_inputs (sha256 обязателен)';
    END IF;

    -- …и к версии модели, если в прогоне есть выход модели/SIAR
    IF v_run.model_version IS NULL AND (
           EXISTS (SELECT 1 FROM predictions       WHERE run_id = p_run_id)
        OR EXISTS (SELECT 1 FROM quadrant_results  WHERE run_id = p_run_id)
    ) THEN
        v_problems := v_problems ||
            '§5.8: runs.model_version пуст при наличии predictions/quadrant_results';
    END IF;

    FOR v_kind IN
        SELECT DISTINCT kind FROM quadrant_results WHERE run_id = p_run_id
    LOOP
        -- Пороги прогона обязаны быть снапшочены (источник — siar/rules.py)
        IF NOT EXISTS (SELECT 1 FROM thresholds
                        WHERE run_id = p_run_id AND scope = v_kind
                          AND code = 'high_threshold')
           OR NOT EXISTS (SELECT 1 FROM thresholds
                        WHERE run_id = p_run_id AND scope = v_kind
                          AND code = 'max_score')
        THEN
            v_problems := v_problems || format(
                'thresholds: для scope=%s нет high_threshold/max_score — '
                'загрузчик обязан снапшотить пороги из rules.py', v_kind);
            CONTINUE;
        END IF;

        -- Балл в шкале 0..max_score прогона (rules.validate_score)
        SELECT count(*) INTO v_bad
        FROM quadrant_results q
        JOIN thresholds t ON t.run_id = q.run_id AND t.scope = q.kind
                         AND t.code = 'max_score'
        WHERE q.run_id = p_run_id AND q.kind = v_kind
          AND q.rating_score > t.value;
        IF v_bad > 0 THEN
            v_problems := v_problems || format(
                'шкала: %s строк (%s) с rating_score выше max_score прогона',
                v_bad, v_kind);
        END IF;

        -- §5.5 (численно): rating_high строго = (score >= high_threshold прогона)
        SELECT count(*) INTO v_bad
        FROM quadrant_results q
        JOIN thresholds t ON t.run_id = q.run_id AND t.scope = q.kind
                         AND t.code = 'high_threshold'
        WHERE q.run_id = p_run_id AND q.kind = v_kind
          AND q.rating_high <> (q.rating_score >= t.value);
        IF v_bad > 0 THEN
            v_problems := v_problems || format(
                '§5.5: %s строк (%s), где rating_high не совпадает с порогом прогона',
                v_bad, v_kind);
        END IF;

        -- §5.1: строки итога = N источника рейтинга (если row_count зафиксирован).
        -- Несопоставленное со стороны модели учтено в unmatched — потери явные.
        SELECT i.row_count INTO v_expected
        FROM run_inputs i
        WHERE i.run_id = p_run_id
          AND i.file_role = CASE v_kind
                              WHEN 'osf'    THEN 'osf_rating_pdf'
                              WHEN 'region' THEN 'region_rating_xlsx'
                            END;
        IF v_expected IS NOT NULL THEN
            SELECT count(*) INTO v_cnt
            FROM quadrant_results
            WHERE run_id = p_run_id AND kind = v_kind;
            IF v_cnt <> v_expected THEN
                v_problems := v_problems || format(
                    '§5.1: строк итога (%s, %s) ≠ N источника рейтинга (%s)',
                    v_cnt, v_kind, v_expected);
            END IF;
        END IF;
    END LOOP;

    IF cardinality(v_problems) > 0 THEN
        RAISE EXCEPTION E'validate_run(%): нарушены инварианты — выдача запрещена:\n%',
            p_run_id, array_to_string(v_problems, E'\n');
    END IF;
END;
$fn$;

COMMENT ON FUNCTION validate_run(bigint) IS
    'Межтабличные инварианты LOGIC.md §5 (§5.1, §5.5 численно, §5.8) для прогона. Построчные §5.2–§5.4 гарантированы CHECK-констрейнтами quadrant_results. Ошибка = исключение, публикация невозможна.';

CREATE OR REPLACE FUNCTION publish_run(p_run_id bigint)
RETURNS void
LANGUAGE plpgsql
SET search_path = antidoping, pg_temp
AS $fn$
BEGIN
    PERFORM validate_run(p_run_id);

    UPDATE runs
       SET published_at = now(),
           status       = 'success',
           finished_at  = COALESCE(finished_at, now())
     WHERE run_id = p_run_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'publish_run: прогон % не найден', p_run_id;
    END IF;
END;
$fn$;

COMMENT ON FUNCTION publish_run(bigint) IS
    'Единственный путь публикации снапшота: сначала validate_run(), затем published_at. Витрины v_* читают только опубликованные прогоны (STRUCTURE.md, п. 4).';

COMMIT;

-- ============================================================================
-- РАСШИРЕНИЕ · веб-платформа (промышленный контур, СЛОЙ 4/5)
-- ============================================================================
-- Аддитивная миграция поверх утверждённой схемы выше: новые таблицы для
-- формы пожеланий, письменной аналитики АД-Монитора, blue/green-реестра
-- моделей и журнала автопереобучения + витрины истории на все опубликованные
-- прогоны (раздел «История рисковости»). Ничего из схемы выше не меняется —
-- только новые CREATE TABLE IF NOT EXISTS / CREATE OR REPLACE VIEW.
-- ============================================================================

BEGIN;
SET LOCAL search_path = antidoping, public;

-- ----------------------------------------------------------------------------
-- feedback — форма пожеланий. НИКОГДА не читается интерфейсом обратно
-- (ни автору, ни другим, ни в виде ленты/счётчика) — только запись с датой
-- и разделом; читает исключительно разработчик напрямую из БД.
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    section      text NOT NULL,            -- откуда отправлено: экран/раздел платформы
    message      text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE feedback IS
    'Пожелания/комментарии пользователей платформы. API отдаёт только 201 Created
     при отправке — ни один эндпоинт не читает эту таблицу обратно в интерфейс.';

CREATE INDEX IF NOT EXISTS ix_feedback_created ON feedback (created_at DESC);

-- ----------------------------------------------------------------------------
-- digest_narrative — письменная аналитика АД-Монитора (LOGIC.md §1: LLM только
-- собирает и резюмирует). Отдельный шаг ПОСЛЕ load_digest.py — контракт
-- ad_monitor_prompt_v15.md (только JSON, без прозы) не меняется этим полем.
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS digest_narrative (
    narrative_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          bigint REFERENCES runs(run_id) ON DELETE SET NULL,
    monitor_date    date NOT NULL,
    window_from     date NOT NULL,
    window_to       date NOT NULL,
    scope           text NOT NULL CHECK (scope IN ('rf', 'intl')),
    narrative       text NOT NULL,
    source_flag_ids bigint[] NOT NULL DEFAULT '{}',   -- аудит: какие flags легли в основу текста
    generated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ux_digest_narrative UNIQUE (monitor_date, scope)
);

COMMENT ON TABLE digest_narrative IS
    'Связный текст обзора периода — пересказ ТОЛЬКО подтверждённых flags
     (source_flag_ids), без оценок риска и без придуманных фактов. Формирует
     monitor/summarize_digest.py. Пусто = дайджест без письменной части (не блокирует показ графиков/таблиц).';

CREATE INDEX IF NOT EXISTS ix_digest_narrative_date ON digest_narrative (monitor_date DESC);

-- ----------------------------------------------------------------------------
-- model_artifacts — blue/green реестр версий модели. Ровно одна активная
-- версия одновременно; ml/predict.py читает её через symlink ml/artifacts/current,
-- который переключает исключительно ml/retrain.py при успешном промоушене.
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS model_artifacts (
    artifact_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version         text NOT NULL UNIQUE,        -- напр. '20260702_2203'
    model_path      text NOT NULL,
    meta_path       text NOT NULL,
    sha256          antidoping.sha256_hex NOT NULL,
    trained_at      timestamptz NOT NULL DEFAULT now(),
    status          text NOT NULL DEFAULT 'candidate'
                    CONSTRAINT ck_artifact_status
                    CHECK (status IN ('candidate', 'active', 'retired', 'rejected')),
    backtest_run_id bigint REFERENCES runs(run_id) ON DELETE SET NULL,
    promoted_at     timestamptz,
    retired_at      timestamptz,
    notes           text
);

COMMENT ON TABLE model_artifacts IS
    'Реестр версий ансамбля — источник истины для ml/retrain.py (читает
     status=active напрямую отсюда). Промоушен — только через
     promote_model_artifact() ниже (атомарно: старая active → retired, новая
     candidate → active), никогда прямым UPDATE из приложения.
     ml/artifacts/current/ на диске — лишь удобное зеркало активной версии
     для ручных вызовов/простых cron (DEPLOY.md), не читается retrain.py.';

-- «Не более одной активной версии» — уникальный индекс по значению status,
-- ограниченный строками status=''active''; т.к. значение одно и то же (active)
-- у всех индексируемых строк, вторая такая строка нарушит уникальность.
CREATE UNIQUE INDEX IF NOT EXISTS ux_artifact_one_active
    ON model_artifacts (status) WHERE status = 'active';

CREATE OR REPLACE FUNCTION promote_model_artifact(p_artifact_id bigint)
RETURNS void
LANGUAGE plpgsql
SET search_path = antidoping, pg_temp
AS $fn$
BEGIN
    UPDATE model_artifacts SET status = 'retired', retired_at = now()
     WHERE status = 'active';

    UPDATE model_artifacts SET status = 'active', promoted_at = now()
     WHERE artifact_id = p_artifact_id AND status = 'candidate';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'promote_model_artifact: % не найден или не в статусе candidate', p_artifact_id;
    END IF;
END;
$fn$;

COMMENT ON FUNCTION promote_model_artifact(bigint) IS
    'Единственный путь смены активной версии модели (blue/green). Вызывается
     ml/retrain.py после успешного backtest-гейта (кандидат не хуже действующей
     версии по Lift@K, LOGIC.md §2).';

-- ----------------------------------------------------------------------------
-- retrain_runs — журнал автопереобучения: файл-триггер → решение промоушена.
-- Отклонённые/провалившиеся попытки НЕ удаляются — история дрейфа сохраняется.
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS retrain_runs (
    retrain_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                bigint NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    trigger               text NOT NULL CHECK (trigger IN ('file_watch', 'manual', 'scheduled')),
    triggering_file       text,
    triggering_sha256     antidoping.sha256_hex,
    candidate_artifact_id bigint REFERENCES model_artifacts(artifact_id) ON DELETE SET NULL,
    baseline_artifact_id  bigint REFERENCES model_artifacts(artifact_id) ON DELETE SET NULL,
    metric_name           text NOT NULL DEFAULT 'lift_at_20',
    candidate_metric      double precision,
    baseline_metric       double precision,
    decision              text NOT NULL DEFAULT 'pending'
                          CONSTRAINT ck_retrain_decision
                          CHECK (decision IN ('pending', 'promoted', 'rejected', 'failed')),
    decision_reason       text,
    started_at            timestamptz NOT NULL DEFAULT now(),
    finished_at           timestamptz
);

COMMENT ON TABLE retrain_runs IS
    'Один файл-триггер (новая таблица дисквалификаций) = одна строка. failed —
     файл не прошёл валидацию/обучение (см. decision_reason), сервис на
     действующей версии модели не останавливается.';

CREATE INDEX IF NOT EXISTS ix_retrain_started ON retrain_runs (started_at DESC);

-- ----------------------------------------------------------------------------
-- Витрины «История рисковости» — по ВСЕМ опубликованным прогонам (не только
-- последнему, в отличие от v_osf_current/v_regions_current выше).
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_quadrant_history AS
SELECT q.*,
       r.started_at   AS run_started_at,
       r.published_at AS run_published_at,
       r.model_version,
       r.rules_version
FROM quadrant_results q
JOIN runs r ON r.run_id = q.run_id
WHERE r.published_at IS NOT NULL;

COMMENT ON VIEW v_quadrant_history IS
    'Раздел «История рисковости»: зона/приоритет/критерии по каждой связке на
     каждый опубликованный прогон — материал для динамики по кварталам.';

CREATE OR REPLACE VIEW v_predictions_history AS
SELECT p.*,
       r.started_at   AS run_started_at,
       r.published_at AS run_published_at,
       r.model_version
FROM predictions p
JOIN runs r ON r.run_id = p.run_id
WHERE r.published_at IS NOT NULL;

COMMENT ON VIEW v_predictions_history IS
    'Сырые признаки модели (lag/rolling) по всем опубликованным прогонам —
     разрез «по каждому критерию» в разделе истории.';

COMMIT;

-- ============================================================================
-- Заметки по эксплуатации (не выполняются):
--   * Доступ по ролям (LOGIC.md §7) — выдать приложению минимум:
--       -- CREATE ROLE antidoping_api LOGIN PASSWORD '…';  -- пароль только из .env
--       -- GRANT USAGE ON SCHEMA antidoping TO antidoping_api;
--       -- GRANT SELECT ON ALL TABLES IN SCHEMA antidoping TO antidoping_api;
--       -- GRANT INSERT ON antidoping.flags TO antidoping_api;  -- при необходимости
--   * Бэкапы PostgreSQL — ежедневно (LOGIC.md §7), например pg_dump в cron
--     docker-compose; строка подключения — только из .env (STRUCTURE.md, п. 6).
--   * Загрузчики (db/loaders, parsers/registry_loader.py) пишут в порядке:
--     runs → run_inputs → thresholds → данные → publish_run(run_id).
-- ============================================================================
