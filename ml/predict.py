#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ml/predict.py — прогон прогнозной модели (перенос из 2_predict.ipynb, код тела не менялся).
Автогенерация: тело ноутбука вставлено как есть; отключены только .show() графиков,
пути вынесены в аргументы, добавлен экспорт CSV для SIAR.

Запуск на маке:
  python ml/predict.py \
      --model ml/artifacts/prod_ensemble_20260702_2203.pkl \
      --meta  ml/artifacts/meta_20260702_2203.json \
      --data  "24.06.2026 Список дисквал.xlsx" \
      --out   predictions/
Выходы: full_report_*.xlsx (как в ноутбуке) + model_risks.csv (по видам спорта)
        + region_risks.csv (по регионам) + full_grid.csv (вся сетка для БД).
Зоны и {причина} в CSV — только из siar/rules.py (assign_zone, SIAR v2);
свободные формулировки консольных отчётов в CSV не попадают.
Целевой период: --period "YYYY QN"; без флага — квартал, следующий за последним
закрытым календарным кварталом (LOGIC.md §2: прогноз «на следующий квартал»).
"""
import argparse, sys
from pathlib import Path

# Корень репозитория → sys.path, чтобы `import siar.rules` работал при запуске
# `python ml/predict.py` (тот же приём, что в tests/conftest.py).
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_ap = argparse.ArgumentParser()
_ap.add_argument("--model", required=True, help="pkl ансамбля (joblib)")
_ap.add_argument("--meta", required=True, help="meta json")
_ap.add_argument("--data", required=True, help="xlsx/csv базы дисквалификаций")
_ap.add_argument("--out", default="predictions", help="папка выходов")
_ap.add_argument("--period", default=None,
                 help="целевой период 'YYYY QN' (напр. '2026 Q3'); без флага — "
                      "квартал, следующий за последним закрытым календарным кварталом")
_args = _ap.parse_args()
MODEL_PATH = _args.model
META_PATH  = _args.meta
DATA_PATH  = _args.data
Path(_args.out).mkdir(parents=True, exist_ok=True)

try:
    display  # type: ignore
except NameError:
    def display(*a, **k):  # заглушка вне Jupyter: печатаем головы таблиц
        for x in a:
            try: print(x.head(15).to_string())
            except Exception: print(x)


import os, re, json, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import joblib
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime
from catboost import CatBoostClassifier, Pool

# Чтобы скрипт работал и в Jupyter/VS Code Interactive (где есть display),
# и при запуске как обычный .py (где display отсутствует):
try:
    display
except NameError:
    def display(x):
        print(x)

print("=" * 60)
print("🔮 ПОЛНОЕ ПРОГНОЗИРОВАНИЕ И ГЕНЕРАЦИЯ ОТЧЁТОВ")
print("=" * 60)

# ── 1. ЗАГРУЗКА МОДЕЛИ И МЕТАДАННЫХ ─────────────────────────
print("\n📂 Загружаем модель и метаданные...")
prod_models = joblib.load(MODEL_PATH)
with open(META_PATH, "r", encoding="utf-8") as f:
    meta = json.load(f)
print(f"✅ Ансамбль из {len(prod_models)} моделей загружен. Прогноз на: {meta['forecast_period']}")

# ── 2. ФУНКЦИИ ОЧИСТКИ И АГРЕГАЦИИ ──────────────────────────
SPORT_MAP = {"Вольная Борьба": "Спортивная Борьба", "Греко-Римская Борьба": "Спортивная Борьба",
              "Греко-римская борьба": "Спортивная Борьба", "Спортивная борьба": "Спортивная Борьба"}
REGION_MAP = {"Г. Москва": "Москва", "Г.москва": "Москва", "Г. Санкт-Петербург": "Санкт-Петербург",
               "Цска": "Москва", "Локомотив": "Москва", "Клб Спартак": "Москва"}

def _year(t):
    if pd.isna(t): return None
    m = re.findall(r"\d{4}", str(t)); return int(m[0]) if m else None
def _month(t):
    if pd.isna(t): return None
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", str(t).lower().strip()); return int(m.group(2)) if m else None
def _first_region(s):
    if pd.isna(s): return None
    s = str(s).strip()
    for sep in [" - ", " – ", " — ", "-", ", ", " и "]:
        if sep in s: return s.split(sep)[0].strip().title()
    return s.title()

# ─────────────────────────────────────────────────────────────
#  РОБАСТНЫЙ ЗАГРУЗЧИК «СЫРЫХ» ФАЙЛОВ (как 24.06.2026)
#  Файл РУСАДА имеет «грязную» шапку: сверху пустая строка(и),
#  настоящие заголовки на 2-й строке, под ними — под-шапка
#  («Дисквалификация / Временное отстранение / Аннулирование»),
#  а внутри данных — строки-разделители по годам («2004 год»).
#  Старый код искал шапку на копии, прочитанной с header=0, и
#  ошибался на 1 строку (off-by-one) → колонки оставались Unnamed
#  → падало с «Обязательная колонка 'Вид спорта' отсутствует».
#  Здесь шапка ищется по «сырым» строкам (header=None), поэтому
#  смещения нет; служебные строки удаляются явно.
# ─────────────────────────────────────────────────────────────
def _row_has_header(cells):
    """Строка считается шапкой, если в ней одновременно есть
    столбец вида спорта И столбец региона/субъекта."""
    vals = [str(c).lower() for c in cells if pd.notna(c)]
    joined = " | ".join(vals)
    has_sport = any(("вид" in v and "спорт" in v) for v in vals)   # «Вид спорта» и «Вида спорта»
    has_region = ("субъект" in joined) or ("регион" in joined)     # «Субъект РФ» и «Регион»
    return has_sport and has_region

def _find_header_row(raw, scan=15):
    """Возвращает индекс строки с настоящими заголовками, или None."""
    for i in range(min(scan, len(raw))):
        if _row_has_header(raw.iloc[i].tolist()):
            return i
    return None

def _sniff_csv_sep(path):
    """Определяем разделитель CSV по первым строкам (',', ';', tab, '|')."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        sample = f.readline() + f.readline()
    counts = {sep: sample.count(sep) for sep in [",", ";", "\t", "|"]}
    return max(counts, key=counts.get)

def _read_raw_table(path):
    """Читает .xlsx или .csv с ПРАВИЛЬНО найденным заголовком,
    независимо от количества пустых/служебных строк сверху."""
    ext = os.path.splitext(str(path))[1].lower()

    if ext in (".xlsx", ".xls", ".xlsm"):
        xl = pd.ExcelFile(path)
        names = xl.sheet_names
        # Предпочитаем лист российских спортсменов («РФ»), иначе — первый лист
        preferred = [n for n in names if str(n).strip().lower() in ("рф", "rf")]
        order = preferred + [n for n in names if n not in preferred]
        chosen, hdr = order[0], 0
        for n in order:
            peek = pd.read_excel(path, sheet_name=n, header=None, nrows=15)
            h = _find_header_row(peek)
            if h is not None:
                chosen, hdr = n, h
                break
        print(f"   • Лист: «{chosen}»  ·  строка заголовка (0-инд.): {hdr}")
        df = pd.read_excel(path, sheet_name=chosen, header=hdr)

    elif ext in (".csv", ".tsv", ".txt"):
        sep = "\t" if ext == ".tsv" else _sniff_csv_sep(path)
        peek = pd.read_csv(path, sep=sep, header=None, nrows=15,
                           encoding="utf-8-sig", dtype=str, engine="python")
        hdr = _find_header_row(peek)
        if hdr is None:
            hdr = 0
        print(f"   • CSV  ·  разделитель: {sep!r}  ·  строка заголовка (0-инд.): {hdr}")
        df = pd.read_csv(path, sep=sep, header=hdr, encoding="utf-8-sig", engine="python")

    else:
        raise ValueError(f"❌ Неподдерживаемый формат файла: '{ext}'. Ожидается .xlsx или .csv")

    # Выбрасываем «пустые» технические колонки (Unnamed) и полностью пустые столбцы
    df = df.loc[:, ~df.columns.astype(str).str.match(r"^Unnamed")]
    df = df.dropna(axis=1, how="all")
    return df

def _strip_separator_rows(df):
    """Удаляет строки-разделители («2004 год»), под-шапку
    («Дисквалификация / Временное отстранение / …») и пустые строки.
    Все они не содержат ФИО спортсмена, поэтому удаляются по пустому ФИО."""
    before = len(df)
    fio_cols = [c for c in df.columns
                if str(c).strip().lower().startswith("фио") and "тренер" not in str(c).lower()]
    if fio_cols:
        fio = fio_cols[0]
        df = df[df[fio].notna() & (df[fio].astype(str).str.strip() != "")].copy()
    df = df.dropna(axis=0, how="all")
    removed = before - len(df)
    if removed:
        print(f"   • Удалено служебных строк (разделители/под-шапка/пустые): {removed}")
    return df

import warnings; warnings.filterwarnings('ignore')
import pandas as pd, numpy as np, re, difflib

# ── Канонические субъекты РФ (официальные формы) ──
CANON = [
 "Москва","Санкт-Петербург","Севастополь",
 "Республика Адыгея","Республика Алтай","Республика Башкортостан","Республика Бурятия",
 "Республика Дагестан","Республика Ингушетия","Кабардино-Балкарская Республика","Республика Калмыкия",
 "Карачаево-Черкесская Республика","Республика Карелия","Республика Коми","Республика Крым",
 "Республика Марий Эл","Республика Мордовия","Республика Саха (Якутия)","Республика Северная Осетия — Алания",
 "Республика Татарстан","Республика Тыва","Удмуртская Республика","Республика Хакасия",
 "Чеченская Республика","Чувашская Республика",
 "Алтайский Край","Забайкальский Край","Камчатский Край","Краснодарский Край","Красноярский Край",
 "Пермский Край","Приморский Край","Ставропольский Край","Хабаровский Край",
 "Амурская Область","Архангельская Область","Астраханская Область","Белгородская Область","Брянская Область",
 "Владимирская Область","Волгоградская Область","Вологодская Область","Воронежская Область","Ивановская Область",
 "Иркутская Область","Калининградская Область","Калужская Область","Кемеровская Область","Кировская Область",
 "Костромская Область","Курганская Область","Курская Область","Ленинградская Область","Липецкая Область",
 "Магаданская Область","Московская Область","Мурманская Область","Нижегородская Область","Новгородская Область",
 "Новосибирская Область","Омская Область","Оренбургская Область","Орловская Область","Пензенская Область",
 "Псковская Область","Ростовская Область","Рязанская Область","Самарская Область","Саратовская Область",
 "Сахалинская Область","Свердловская Область","Смоленская Область","Тамбовская Область","Тверская Область",
 "Томская Область","Тульская Область","Тюменская Область","Ульяновская Область","Челябинская Область",
 "Ярославская Область",
 "Еврейская Автономная Область","Ненецкий Автономный Округ","Ханты-Мансийский Автономный Округ",
 "Чукотский Автономный Округ","Ямало-Ненецкий Автономный Округ",
]
def _key(s): return re.sub(r"\s+"," ",str(s).lower().replace("ё","е")).strip()
CANON_KEYS = {_key(c): c for c in CANON}

# ── Алиасы: ключ (lower, ё→е) → канон. Города, коды, фрагменты, короткие формы, дубли ──
_AL = {
 # города → регион
 "красноярск":"Красноярский Край","нижний новгород":"Нижегородская Область","курск":"Курская Область",
 "ростов":"Ростовская Область","омск":"Омская Область","брянск":"Брянская Область","новосибирск":"Новосибирская Область",
 "волгоград":"Волгоградская Область","пермь":"Пермский Край","ульяновск":"Ульяновская Область","казань":"Республика Татарстан",
 "ярославль":"Ярославская Область","саянск":"Иркутская Область","барнаул":"Алтайский Край","пенза":"Пензенская Область",
 "самара":"Самарская Область","екатеринбург":"Свердловская Область","уфа":"Республика Башкортостан","москва цска":"Москва",
 # фрагменты (обрезка по дефису/тире) и коды
 "ямало":"Ямало-Ненецкий Автономный Округ","янао":"Ямало-Ненецкий Автономный Округ",
 "ханты":"Ханты-Мансийский Автономный Округ","хмао":"Ханты-Мансийский Автономный Округ",
 "кабардино":"Кабардино-Балкарская Республика","кбр":"Кабардино-Балкарская Республика",
 "карачаево":"Карачаево-Черкесская Республика","кчр":"Карачаево-Черкесская Республика",
 "северная осетия":"Республика Северная Осетия — Алания","осетия":"Республика Северная Осетия — Алания",
 "рсо":"Республика Северная Осетия — Алания","рсо алания":"Республика Северная Осетия — Алания",
 "республика северная осетия":"Республика Северная Осетия — Алания",
 # короткие формы / порядок слов республик + дубли
 "дагестан":"Республика Дагестан","республика чувашия":"Чувашская Республика","чувашия":"Чувашская Республика",
 "чувашская":"Чувашская Республика","мордовия":"Республика Мордовия","хакасия":"Республика Хакасия",
 "башкортостан":"Республика Башкортостан","башкоркостан":"Республика Башкортостан","якутия":"Республика Саха (Якутия)",
 "республика якутия":"Республика Саха (Якутия)","республика саха якутия":"Республика Саха (Якутия)",
 "калмыкия":"Республика Калмыкия","удмуртия":"Удмуртская Республика","республика удмуртия":"Удмуртская Республика",
 "республика удмуртская":"Удмуртская Республика","крым":"Республика Крым","бурятия":"Республика Бурятия",
 "республика бурятия":"Республика Бурятия","татарстан":"Республика Татарстан","карелия":"Республика Карелия",
 "коми":"Республика Коми","тыва":"Республика Тыва","адыгея":"Республика Адыгея","ингушетия":"Республика Ингушетия",
 "марий эл":"Республика Марий Эл","алтай":"Республика Алтай",
 # обрезанные адъективы, которые не достаёт авто-логика
 "пермская":"Пермский Край","сверловская":"Свердловская Область",
 # клубы → регион (очевидные)
 "волгоградское динамо":"Волгоградская Область",
}
ALIAS = { _key(k): v for k,v in _AL.items() }

# доп. города и клубы → регион
_AL2 = {
 "ростов-на-дону":"Ростовская Область","иркутск":"Иркутская Область","челябинск":"Челябинская Область",
 "магадан":"Магаданская Область","обнинск":"Калужская Область","мценск":"Орловская Область",
 "новый уренгой":"Ямало-Ненецкий Автономный Округ","тольятти":"Самарская Область","сочи":"Краснодарский Край",
 "санкт":"Санкт-Петербург","цска":"Москва","локомотив":"Москва","клб спартак":"Москва","спартак":"Москва","динамо":"Москва",
 # варианты республик с дефисом/без «Республика»
 "кабардино-балкария":"Кабардино-Балкарская Республика","кабардино балкария":"Кабардино-Балкарская Республика",
 "кабардино-балкарская":"Кабардино-Балкарская Республика","республика кабардино-балкария":"Кабардино-Балкарская Республика",
 "карачаево-черкесская":"Карачаево-Черкесская Республика","карачаево-черкессия":"Карачаево-Черкесская Республика",
 "чеченская":"Чеченская Республика","рсо-алания":"Республика Северная Осетия — Алания",
}
ALIAS.update({_key(k): v for k,v in _AL2.items()})

_SEP = ["/", ";", ",", " - ", " – ", " — ", " и "]   # мультирегион → ПЕРВЫЙ. Дефис БЕЗ пробелов (Ямало-Ненецкий) НЕ режем.
def normalize_region(raw):
    if pd.isna(raw): return None
    s = str(raw).strip()
    s = re.sub(r"\(.*?\)","",s); s = re.sub(r"\(.*$","",s)     # убрать скобки «(ЦСКА)», в т.ч. незакрытые
    s = re.sub(r"\s+"," ",s).strip()
    for sep in _SEP:
        if sep in s: s = s.split(sep)[0].strip(); break
    s = re.sub(r"^г\.?\s*","",s, flags=re.I).strip()          # убрать «Г.»/«Г »
    s = re.sub(r"\bобл\.?$","Область",s, flags=re.I)
    s = re.sub(r"\bобл\.?\b","Область",s, flags=re.I)
    s = re.sub(r"\bресп\.?\b","Республика",s, flags=re.I)
    s = s.title()
    k = _key(s)
    if k in ALIAS: return ALIAS[k]
    if k in CANON_KEYS: return CANON_KEYS[k]
    for full in ["Область","Край"]:                            # обрезанный адъектив: + тип
        if _key(s+" "+full) in CANON_KEYS: return CANON_KEYS[_key(s+" "+full)]
    if _key("Республика "+s) in CANON_KEYS: return CANON_KEYS[_key("Республика "+s)]
    if _key(s+" Республика") in CANON_KEYS: return CANON_KEYS[_key(s+" Республика")]
    m = difflib.get_close_matches(k, list(CANON_KEYS.keys()), n=1, cutoff=0.84)   # нечёткое добивание
    if m: return CANON_KEYS[m[0]]
    return s.title()        # иностранцы/мусор → редкие → «Другое»

def clean_data(path, remove_age_outliers=True):
    # ── Чтение файла с автоопределением формата и поиском настоящей шапки ──
    print(f"\n📥 Читаем файл: {os.path.basename(str(path))}")
    df = _read_raw_table(path)
    df = _strip_separator_rows(df)
    print(f"   • Колонки после загрузки: {list(df.columns)}")

    # ── Приведение названий колонок к единому виду ──
    column_map = {
        "Вида спорта": "Вид спорта",
        "Вид спорта": "Вид спорта",
        "Период дисквалификации / временного отстранения": "Период действия санкции",
        "Период действия санкции": "Период действия санкции",
        "Регион": "Субъект РФ",
        "Субъект РФ": "Субъект РФ",
        "Класс запрещенной субстанции / вид запрещенного метода (пункт нарушения правил)": "Пункт нарушения АДП",
    }
    for old_name, new_name in column_map.items():
        if old_name in df.columns:
            df = df.rename(columns={old_name: new_name})
        else:
            similar = [c for c in df.columns if old_name.lower() in str(c).lower()]
            if similar:
                df = df.rename(columns={similar[0]: new_name})
                print(f"   • Сопоставлено: '{similar[0]}' → '{new_name}'")

    # ── Проверка обязательных колонок ──
    required_columns = ["Вид спорта", "Субъект РФ", "Период действия санкции"]
    for col in required_columns:
        if col not in df.columns:
            similar = [c for c in df.columns if col.lower() in str(c).lower()]
            if similar:
                df = df.rename(columns={similar[0]: col})
                print(f"   • Использую '{similar[0]}' вместо '{col}'")
            else:
                raise ValueError(f"❌ Обязательная колонка '{col}' отсутствует в данных")

    # ── Обработка данных (без изменений по сравнению с исходной логикой) ──
    s = df["Вид спорта"].astype(str).str.strip().str.title().str.replace(r"\s+", " ", regex=True)
    s = s.replace(SPORT_MAP).str.replace("Ё", "Е", regex=False).str.replace("ё", "е", regex=False)
    s = s.str.replace("\u00a0", " ", regex=False).replace({"": np.nan, "Nan": np.nan})
    df["Вид спорта"] = s.fillna(s.mode()[0])

    df["Год нарушения"] = df["Период действия санкции"].apply(_year)
    df["Месяц нарушения"] = df["Период действия санкции"].apply(_month)

    by = pd.to_datetime(df["Дата рождения"], errors="coerce", dayfirst=True).dt.year
    df["Возраст"] = df["Год нарушения"] - by

    r = df["Субъект РФ"].apply(normalize_region).astype(str).str.strip()
    r = r.replace({"Nan": np.nan, "None": np.nan, "": np.nan, "Na": np.nan})
    r = r.fillna(r.mode()[0]); vc = r.value_counts(); rare = vc[vc < 5].index
    df["Субъект РФ_исходный"] = r            # нормализованный регион ДО свёртки в «Другое»
    df["Субъект РФ"] = r.where(~r.isin(rare), "Другое")

    if remove_age_outliers:
        known = df["Возраст"].notna()
        df = df[~known | ((df["Возраст"] >= 14) & (df["Возраст"] <= 70))].copy()
        def mask(x):
            xn = x.dropna()
            if len(xn) < 4: return pd.Series(True, index=x.index)
            q1, q3 = xn.quantile(.25), xn.quantile(.75); iqr = q3 - q1
            return ((x >= q1 - 1.5 * iqr) & (x <= q3 + 1.5 * iqr)) | x.isna()
        df = df[df.groupby("Вид спорта")["Возраст"].transform(mask)]

    df["Год нарушения"] = pd.to_numeric(df["Год нарушения"], errors="coerce")
    df = df[(df["Год нарушения"] >= 2004) & (df["Год нарушения"] <= 2026)].copy()
    df["Год нарушения"] = df["Год нарушения"].astype(int)
    df = df[df["Месяц нарушения"].notna()].copy()
    df["Квартал"] = ((df["Месяц нарушения"].astype(int) - 1) // 3) + 1

    print(f"   ✅ Готово: {df.shape[0]} строк, годы {int(df['Год нарушения'].min())}–{int(df['Год нарушения'].max())}")
    return df

def build_agg(df):
    sports = df["Вид спорта"].astype(str).str.strip().unique()
    regions = df["Субъект РФ"].astype(str).str.strip().unique()
    years = sorted(df["Год нарушения"].unique())
    grid = pd.MultiIndex.from_product([sports, regions, years, [1, 2, 3, 4]],
        names=["Вид спорта", "Субъект РФ", "Год нарушения", "Квартал"]).to_frame(index=False).drop_duplicates()
    real = df.groupby(["Вид спорта", "Субъект РФ", "Год нарушения", "Квартал"]).size().reset_index(name="target")
    agg = grid.merge(real, on=["Вид спорта", "Субъект РФ", "Год нарушения", "Квартал"], how="left")
    agg["target"] = agg["target"].fillna(0).astype(int)
    agg["risk_class"] = np.where(agg["target"] >= 2, 2, np.where(agg["target"] == 1, 1, 0))
    return agg

def create_features(df):
    CAT = ["Вид спорта", "Субъект РФ"]
    NUM = ["Год нарушения", "Квартал", "lag_1q", "lag_2q", "lag_4q",
            "rolling_mean_4q", "rolling_sum_4q", "rolling_max_4q", "rolling_mean_8q", "rolling_std_4q"]
    df = df.sort_values(["Вид спорта", "Субъект РФ", "Год нарушения", "Квартал"]).copy()
    df["gk"] = df["Вид спорта"] + "|" + df["Субъект РФ"]; g = df.groupby("gk")["target"]
    for k in (1, 2, 4): df[f"lag_{k}q"] = g.shift(k)
    df["rolling_mean_4q"] = g.transform(lambda x: x.shift(1).rolling(4, min_periods=1).mean())
    df["rolling_sum_4q"] = g.transform(lambda x: x.shift(1).rolling(4, min_periods=1).sum())
    df["rolling_max_4q"] = g.transform(lambda x: x.shift(1).rolling(4, min_periods=1).max())
    df["rolling_mean_8q"] = g.transform(lambda x: x.shift(1).rolling(8, min_periods=1).mean())
    df["rolling_std_4q"] = g.transform(lambda x: x.shift(1).rolling(4, min_periods=1).std())
    df = df.drop(columns=["gk"]); df[NUM[2:]] = df[NUM[2:]].fillna(0); return df

# ── 3. ОБРАБОТКА ДАННЫХ И ПРОГНОЗ ───────────────────────────
print("\n🔧 Агрегируем данные и считаем лаги...")
df = clean_data(DATA_PATH)
df_agg = create_features(build_agg(df))

# Жестко привязываем категории к тем, что были при обучении.
# ВАЖНО: если в свежем файле появилось значение, которого НЕ было при обучении
# (например, новый вид спорта), pd.Categorical превратит его в NaN, и CatBoost
# упадёт с «cat_features ... NaN values should be converted to string».
# Поэтому такие незнакомые модели комбинации сначала ОТСЕИВАЕМ и явно сообщаем о них.
CAT = meta['cat_features']
for c in CAT:
    known = set(map(str, meta['categories'][c]))
    col = df_agg[c].astype(str)
    oov_mask = ~col.isin(known)
    if oov_mask.any():
        oov_vals = sorted(col[oov_mask].unique())
        print(f"⚠️  В признаке «{c}» есть значения, которых не было при обучении модели: "
              f"{oov_vals} (затронуто строк: {int(oov_mask.sum())}).")
        print(f"    Эти комбинации исключены из прогноза. Чтобы они учитывались — "
              f"переобучите модель на свежих данных.")
        df_agg = df_agg[~oov_mask].copy()

# Теперь жёстко приводим категории к обучающим — NaN уже гарантированно не будет
for c in CAT:
    df_agg[c] = pd.Categorical(df_agg[c].astype(str), categories=meta['categories'][c])

# ── 4. ПРОГНОЗ НА ЦЕЛЕВОЙ КВАРТАЛ ───────────────────────────
# Целевой период (LOGIC.md §2: прогноз «на следующий квартал»):
#   1) --period "YYYY QN" — явное задание (повторные прогоны, бэктесты);
#   2) без флага — квартал, следующий за последним ЗАКРЫТЫМ календарным
#      кварталом на дату запуска: июль 2026 → закрыт Q2 → цель 2026 Q3.
# Старая эвристика «максимум по сетке» всегда упиралась в Q4 последнего года:
# build_agg добивает сетку кварталами 1–4 независимо от реальных данных.

def _parse_period(text):
    m = re.fullmatch(r"\s*(\d{4})\s*[Qq]\s*([1-4])\s*", str(text))
    if not m:
        raise SystemExit(f"❌ --period: ожидается 'YYYY QN' (N=1..4), получено: {text!r}")
    return int(m.group(1)), int(m.group(2))

if _args.period:
    ly, lq = _parse_period(_args.period)
    _period_src = "задан явно (--period)"
else:
    _now = datetime.now()
    _q_closed = (_now.month - 1) // 3      # закрытых кварталов в текущем году: 0..3
    ly, lq = _now.year, _q_closed + 1      # 0 закрыто → цель Q1 (после Q4 прошлого года)
    _period_src = "по календарю: следующий за последним закрытым кварталом"

_real_q = (df.groupby(["Год нарушения", "Квартал"]).size()
             .reset_index(name="n").sort_values(["Год нарушения", "Квартал"]))
_lr_y = int(_real_q.iloc[-1]["Год нарушения"])
_lr_q = int(_real_q.iloc[-1]["Квартал"])
print(f"   • Целевой период: {ly} Q{lq} ({_period_src}) · последний квартал "
      f"с записями в базе: {_lr_y} Q{_lr_q} · горизонт обучения из меты: "
      f"{meta.get('forecast_period', 'н/д')}")

_future = df[(df["Год нарушения"] > ly) |
             ((df["Год нарушения"] == ly) & (df["Квартал"] >= lq))]
if len(_future):
    print(f"⚠️  Записей с датой в целевом квартале или позже: {len(_future)}. "
          f"Обычно это даты окончания санкций из колонки периода; на лаги цели "
          f"{ly} Q{lq} они не влияют, но при сдвиге горизонта вперёд исказят признаки.")

_py, _pq = (ly, lq - 1) if lq > 1 else (ly - 1, 4)
if not bool(((df["Год нарушения"] == _py) & (df["Квартал"] == _pq)).any()):
    print(f"⚠️  В базе нет записей за {_py} Q{_pq} (квартал перед целью) — lag_1q "
          f"будет нулевым по всей сетке. База устарела для горизонта {ly} Q{lq}: "
          f"обновите файл или задайте --period ближе к данным.")

# Опциональные фильтры детальных текстовых отчётов (в ноутбуке — блок настроек).
# В CLI не используются: полный срез уходит в CSV. None → раздел пропускается.
ВИД = None
РЕГИОН = None

print(f"\n🤖 Делаем прогноз на {ly} Q{lq}...")
scored = df_agg[(df_agg["Год нарушения"] == ly) & (df_agg["Квартал"] == lq)].copy()

if len(scored) == 0:
    raise ValueError(f"⚠️ Период {ly} Q{lq} не найден в агрегированных данных. Проверьте, есть ли этот год в исходном Excel-файле, или задайте --period в пределах лет базы.")

# Усредняем предсказания ансамбля
FEATURES = meta['features']
target_idx = meta['target_class_index']
proba_list = [m.predict_proba(scored[FEATURES])[:, target_idx] for m in prod_models]
scored['proba'] = np.mean(proba_list, axis=0)

# ── 5. РАСЧЁТ ЗОН РИСКА И ПРИЧИН ────────────────────────────
def _скл(n, one, few, many):
    n=int(abs(n)); d10,d100=n%10,n%100
    if d100 in (11,12,13,14): return many
    if d10==1: return one
    if d10 in (2,3,4): return few
    return many
def _нар(n): return f"{int(n)} {_скл(n,'нарушение','нарушения','нарушений')}"

def assign_risk_levels(d, col="proba", high=10, medium=25):
    d=d.copy(); sig=d[col]>0
    p_hi=np.percentile(d.loc[sig,col],100-high) if sig.sum() else 1.0
    p_md=np.percentile(d.loc[sig,col],100-high-medium) if sig.sum() else 1.0
    d["уровень_риска"]=d[col].apply(lambda v:"ВЫСОКИЙ" if v>=p_hi else("СРЕДНИЙ" if v>=p_md else "НИЗКИЙ")); return d

def build_reason(row):
    lag1=row.get("lag_1q",0); lag2=row.get("lag_2q",0); recent2=lag1+lag2
    year=row.get("rolling_sum_4q",0); hist8=row.get("rolling_mean_8q",0)
    has_hist=(hist8>=0.25) or (year>=3); parts=[]
    if lag1>=1 and lag2>=1: parts.append(f"всплеск 2 квартала подряд ({_нар(recent2)} за последние 2 квартала)")
    elif lag1>=1: parts.append(f"{_нар(lag1)} в прошлом квартале")
    elif lag2>=1: parts.append(f"{_нар(lag2)} два квартала назад")
    elif year>=1: parts.append(f"{_нар(year)} за последний год")
    if parts and has_hist: parts.append("подтверждается историей зоны")
    elif parts and not has_hist: parts.append("ранее зона была тихой — новый сигнал")
    elif not parts and has_hist: parts.append("исторически устойчивая зона риска (свежей активности нет)")
    if not parts: parts.append("повышенный фон без свежей активности")
    return "; ".join(parts[:2])


# ── ПОРЯДОК ЗОН (🔴→🟠→🟢) + НЕЧЁТКИЙ ПОИСК + РАСШИФРОВКА «Другое» ──
import difflib
ZONE_ORDER = {"🔴 КРАСНАЯ": 0, "🟠 ОРАНЖЕВАЯ": 1, "🟢 ЗЕЛЁНАЯ": 2}
def sort_by_zone(d, pc="proba"):
    d = d.copy(); d["_z"] = d["зона_риска"].map(ZONE_ORDER).fillna(3)
    cols = ["_z"] + [c for c in [pc, "lag_1q", "rolling_sum_4q"] if c in d.columns]
    return d.sort_values(cols, ascending=[True]+[False]*(len(cols)-1)).drop(columns="_z").reset_index(drop=True)
def _norm(s): return str(s).lower().replace("ё","е").replace("  "," ").strip()
def _match(name, known):
    if name is None: return None
    nm = {_norm(k): k for k in known}; n = _norm(name)
    if n in nm: return nm[n]
    cand = difflib.get_close_matches(n, list(nm.keys()), n=1, cutoff=0.6)
    if cand: print(f"   • запрос «{name}» → «{nm[cand[0]]}» (ближайшее совпадение)"); return nm[cand[0]]
    print(f"   ⚠️ «{name}» не найдено. Примеры: {list(known)[:6]}"); return None
def состав_другое(df):
    if "Субъект РФ_исходный" not in df.columns: return []
    return sorted(df.loc[df["Субъект РФ"]=="Другое","Субъект РФ_исходный"].astype(str).unique())
def расшифровать_другое(df, sport=None):
    sub = df[df["Субъект РФ"]=="Другое"].copy()
    if sport is not None:
        sp=_match(sport, df["Вид спорта"].astype(str).unique())
        if sp is not None: sub=sub[sub["Вид спорта"]==sp]
    return sub.groupby("Субъект РФ_исходный").size().sort_values(ascending=False)

scored = assign_risk_levels(scored)
scored["причина"] = scored.apply(build_reason, axis=1)
_rec = scored["lag_1q"] + scored["lag_2q"]
_hist = (scored["rolling_mean_8q"] >= 0.25) | (scored["rolling_sum_4q"] >= 2)
scored["зона_риска"] = np.where(_rec > 0, "🔴 КРАСНАЯ", np.where(_hist, "🟠 ОРАНЖЕВАЯ", "🟢 ЗЕЛЁНАЯ"))
scored["признак_активности"] = scored["зона_риска"]
scored = sort_by_zone(scored)   # ПОРЯДОК: 🔴 → 🟠 → 🟢, внутри по оценке
scored["ранг"] = np.arange(1, len(scored) + 1)

print(f"✅ Прогноз готов: {len(scored)} комбинаций | зоны:", dict(scored["зона_риска"].value_counts()))

# ── 6. ГРАФИКИ И ТЕМЫ (Plotly) ──────────────────────────────
INK = "#0F2D52"; SUB = "#7C8DA6"; GRID = "#EEF2F7"
FONT = "Inter, Segoe UI, Roboto, Arial, sans-serif"
BLUESCALE = [[0, "#7DD3FC"], [0.5, "#2563EB"], [1, "#1E3A8A"]]
RISK_COLORS = {"ВЫСОКИЙ": "#DC2626", "СРЕДНИЙ": "#F59E0B", "НИЗКИЙ": "#10B981", "НЕТ ДАННЫХ": "#94A3B8"}
ZONE_COLORS = {"🔴 КРАСНАЯ": "#DC2626", "🟠 ОРАНЖЕВАЯ": "#F59E0B", "🟢 ЗЕЛЁНАЯ": "#10B981"}

def _theme(fig, title, subtitle=""):
    sub = f"<br><span style='font-size:12px;color:{SUB}'>{subtitle}</span>" if subtitle else ""
    fig.update_layout(template="plotly_white", font=dict(family=FONT, color=INK, size=13),
        title=dict(text=f"<b>{title}</b>{sub}", x=0.01, xanchor="left", y=0.95, font=dict(size=19)),
        margin=dict(l=10, r=24, t=84, b=24), paper_bgcolor="white", plot_bgcolor="white",
        coloraxis_showscale=False, legend_title_text="")
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False)
    return fig

def _pc(d): return "оценка_риска" if "оценка_риска" in d.columns else "proba"

def график_топ_зон(data, n=20, title="Топ зон риска"):
    pc = _pc(data); d = data.sort_values("ранг").head(n).copy()
    d["зона"] = d["Вид спорта"].astype(str) + " — " + d["Субъект РФ"].astype(str)
    d = d.iloc[::-1]; hov = [c for c in ["причина", "признак_активности"] if c in d.columns]
    fig = px.bar(d, x=pc, y="зона", orientation="h", color=pc, color_continuous_scale=BLUESCALE,
                 hover_data=hov, text=d[pc].map(lambda v: f"{v:.2f}"))
    fig.update_traces(marker_cornerradius=7, textposition="outside", textfont=dict(size=11, color=INK), cliponaxis=False)
    _theme(fig, title, f"топ-{n} · оценка риска (0–1)")
    fig.update_layout(height=max(420, 30 * n), yaxis_title="", xaxis_title="")
    fig.update_xaxes(showgrid=True, gridcolor=GRID); fig.update_yaxes(showgrid=False)
    return fig

def график_тепловая_карта(data, top_n=12, title="Тепловая карта риска: вид спорта × регион"):
    pc = _pc(data)
    sp = data.groupby("Вид спорта")[pc].max().nlargest(top_n).index
    rg = data.groupby("Субъект РФ")[pc].max().nlargest(top_n).index
    piv = data[data["Вид спорта"].isin(sp) & data["Субъект РФ"].isin(rg)].pivot_table(
        index="Вид спорта", columns="Субъект РФ", values=pc, aggfunc="max")
    fig = px.imshow(piv, color_continuous_scale=["#F0F9FF", "#7DD3FC", "#2563EB", "#1E3A8A"],
                    aspect="auto", text_auto=".2f")
    _theme(fig, title, "топ виды спорта × топ регионы")
    fig.update_layout(height=520, coloraxis_showscale=True); fig.update_yaxes(showgrid=False)
    return fig

def визуализировать(data, вид="топ", **kw):
    return {"топ": график_топ_зон, "карта": график_тепловая_карта}[вид](data, **kw)

# ── 7. ФУНКЦИИ ОТЧЁТОВ ──────────────────────────────────────
def отчет_виды_и_топ_регион(scored, n=25):
    pc = _pc(scored); z = sort_by_zone(scored, pc)
    top = sort_by_zone(z.groupby("Вид спорта", as_index=False).first(), pc).head(n).reset_index(drop=True)
    out = top[["Вид спорта", "Субъект РФ", "зона_риска", pc, "причина"]].rename(
        columns={"Субъект РФ": "самый рисковый регион", pc: "оценка_риска"})
    out.insert(0, "место", range(1, len(out) + 1))
    return out

def отчет_по_виду(scored, sport, n=20):
    pc = _pc(scored); sp = _match(sport, scored["Вид спорта"].astype(str).unique())
    if sp is None: return pd.DataFrame()
    d = sort_by_zone(scored[scored["Вид спорта"].astype(str) == sp], pc).head(n).reset_index(drop=True)
    out = d[["Субъект РФ", "зона_риска", pc, "причина"]].rename(columns={pc: "оценка_риска"})
    out.insert(0, "место", range(1, len(out) + 1))
    return out

def отчет_по_региону(scored, region, n=20):
    pc = _pc(scored); rg = _match(region, scored["Субъект РФ"].astype(str).unique())
    if rg is None: return pd.DataFrame()
    d = sort_by_zone(scored[scored["Субъект РФ"].astype(str) == rg], pc).head(n).reset_index(drop=True)
    out = d[["Вид спорта", "зона_риска", pc, "причина"]].rename(columns={pc: "оценка_риска"})
    out.insert(0, "место", range(1, len(out) + 1))
    return out

def график_отчет(report_df, value_col, title, n=20):
    pc = "оценка_риска" if "оценка_риска" in report_df.columns else _pc(report_df)
    d = report_df.head(n).iloc[::-1]
    fig = px.bar(d, x=pc, y=value_col, orientation="h", color="зона_риска",
                 color_discrete_map=ZONE_COLORS, text=d[pc].map(lambda v: f"{v:.2f}"),
                 hover_data=[c for c in ["причина"] if c in d.columns])
    fig.update_traces(marker_cornerradius=7, textposition="outside", cliponaxis=False, textfont=dict(size=11))
    _theme(fig, title, "цвет = зона: 🔴 свежая динамика · 🟠 история · 🟢 фон")
    fig.update_layout(height=max(380, 30 * len(d)), yaxis_title="", xaxis_title="", legend_title_text="зона")
    fig.update_yaxes(showgrid=False); fig.update_xaxes(showgrid=True, gridcolor=GRID)
    return fig

# ═══════════════════════════════════════════════════════════════
# 🚀 ВЫВОД ВСЕХ ОТЧЁТОВ И ГРАФИКОВ
# ═══════════════════════════════════════════════════════════════

# Сохраняем общий файл
Path(_args.out).mkdir(exist_ok=True)
timestamp = datetime.now().strftime("%Y%m%d_%H%M")
output_path = str(Path(_args.out) / f"full_report_{timestamp}.xlsx")
scored.to_excel(output_path, index=False)
print(f"\n💾 Полный отчёт сохранён: {output_path}")

# ── ГРАФИКИ ──
print("\n📊 Генерируем графики...")
# [CLI: график отключён] визуализировать(scored, вид="топ", n=20).show()
# [CLI: график отключён] визуализировать(scored, вид="карта").show()

# ── ОТЧЁТ 1 ──
r1 = отчет_виды_и_топ_регион(scored, n=20)
print("\n" + "="*60)
print("ОТЧЁТ 1 — рисковые виды спорта и самый рисковый регион:")
print("="*60)
display(r1)
# [CLI: график отключён] график_отчет(r1, value_col="Вид спорта", title="Рисковые виды спорта (цвет — зона)", n=15).show()

# ── ОТЧЁТ 2 ──
if ВИД is not None:
    r2 = отчет_по_виду(scored, ВИД, n=20)
    print("\n" + "="*60)
    print(f"ОТЧЁТ 2 — рисковые регионы для «{ВИД}»:")
    print("="*60)
    display(r2)
# [CLI: график отключён]     график_отчет(r2, value_col="Субъект РФ", title=f"Рисковые регионы — {ВИД}", n=15).show()
else:
    print("\n⚠️ ОТЧЁТ 2 не генерируется (ВИД = None)")

# ── ОТЧЁТ 3 ──
if РЕГИОН is not None:
    r3 = отчет_по_региону(scored, РЕГИОН, n=20)
    print("\n" + "="*60)
    print(f"ОТЧЁТ 3 — рисковые виды спорта в «{РЕГИОН}»:")
    print("="*60)
    display(r3)
# [CLI: график отключён]     график_отчет(r3, value_col="Вид спорта", title=f"Рисковые виды спорта — {РЕГИОН}", n=15).show()
else:
    print("\n⚠️ ОТЧЁТ 3 не генерируется (РЕГИОН = None)")

# ── Расшифровка «Другое» (какие регионы внутри) ──
if "Другое" in scored["Субъект РФ"].astype(str).values:
    print("\n" + "="*60); print("Регионы в «Другое» (редкие/иностранные):"); print("="*60)
    print(", ".join(состав_другое(df)))
    if ВИД is not None:
        d_=расшифровать_другое(df, sport=ВИД)
        if len(d_): print(f"\nИз «Другое» имели нарушения по «{ВИД}»:"); display(d_.to_frame("нарушений"))

print("\n" + "="*60)
print("✅ ВСЕ ОТЧЁТЫ СФОРМИРОВАНЫ!")
print("="*60)

# ═══════════════ ЭКСПОРТ ДЛЯ SIAR (добавлено при переносе в CLI) ═══════════════
# Зоны и {причина} для CSV/БД — ТОЛЬКО из siar/rules.py (STRUCTURE.md, п. 3):
# пороги не дублируются, формулировки не генерируются «на лету». Свободные
# фразы build_reason остаются в консольных отчётах и full_report_*.xlsx выше;
# в model_risks/region_risks/full_grid они не попадают.
from siar.rules import SIAR_VERSION, ZONE_SEVERITY, assign_zone  # noqa: E402

_exp = scored.copy().rename(columns={_pc(scored): "proba"})
_zr = _exp.apply(lambda r: assign_zone(r["lag_1q"], r["lag_2q"],
                                       r["rolling_mean_8q"], r["rolling_sum_4q"]), axis=1)
_exp["зона_риска"] = [zone.value for zone, _ in _zr]
_exp["причина"] = [reason for _, reason in _zr]        # GREEN → пусто (None)

# Самопроверка: зоны ноутбука обязаны совпасть с rules.assign_zone.
# Расхождение = пороги поменяли в одном месте из двух → падаем, а не расходимся молча.
_ZONE_NORM = {"🔴 КРАСНАЯ": "RED", "🟠 ОРАНЖЕВАЯ": "ORANGE", "🟢 ЗЕЛЁНАЯ": "GREEN",
              "RED": "RED", "ORANGE": "ORANGE", "GREEN": "GREEN"}
_mism = int((scored["зона_риска"].map(_ZONE_NORM).fillna("GREEN")
             != _exp["зона_риска"]).sum())
if _mism:
    sys.exit(f"❌ Зоны ноутбука и rules.assign_zone разошлись в {_mism} строк(ах) — "
             f"пороги рассинхронизированы, выдача CSV запрещена "
             f"(источник истины — siar/rules.py)")

_exp["_z"] = _exp["зона_риска"].map({z.value: s for z, s in ZONE_SEVERITY.items()})
_exp = _exp.sort_values(["_z", "proba"], ascending=[True, False])

_cols = ["зона_риска", "proba", "причина"]
_by_sport = _exp.groupby("Вид спорта", as_index=False).first()[["Вид спорта"] + _cols]
_by_region = _exp.groupby("Субъект РФ", as_index=False).first()[["Субъект РФ"] + _cols]
_grid_cols = [c for c in ["Вид спорта", "Субъект РФ", "зона_риска", "proba", "причина",
                          "lag_1q", "lag_2q", "rolling_mean_8q", "rolling_sum_4q"] if c in _exp.columns]

_by_sport.to_csv(Path(_args.out) / "model_risks.csv", index=False)
_by_region.to_csv(Path(_args.out) / "region_risks.csv", index=False)
_exp[_grid_cols].to_csv(Path(_args.out) / "full_grid.csv", index=False)
print(f"\n💾 CSV для SIAR ({SIAR_VERSION}, зоны/причины — siar/rules.assign_zone): "
      f"model_risks.csv ({len(_by_sport)} видов), region_risks.csv ({len(_by_region)} регионов), "
      f"full_grid.csv ({len(_exp)} строк) → {_args.out}")

# Компактный агрегат базы для СЛОЯ 3 (db/loaders → таблица registry_agg):
# только ненулевые ячейки вид × регион × квартал из ОЧИЩЕННОЙ базы (df), до
# OOV-фильтра сетки. ФИО сюда не попадают по построению (STRUCTURE.md, п. 8);
# сама очистка живёт в одном месте — в этом файле, загрузчик её не дублирует.
_reg = (df.groupby(["Вид спорта", "Субъект РФ", "Год нарушения", "Квартал"])
          .size().reset_index(name="Нарушений"))
_reg.to_csv(Path(_args.out) / "registry_agg.csv", index=False)
print(f"💾 registry_agg.csv: {len(_reg)} ненулевых ячеек агрегата базы → {_args.out}")
