# -*- coding: utf-8 -*-
"""tests/test_determinism.py — «повторный расчёт даёт побайтово идентичный
результат» (Definition of Done). Раньше это заявлялось, но не проверялось —
сама постройка Excel/HTML через openpyxl/Plotly добавляла недетерминизм
(таймстемпы zip-контейнера, dcterms:modified, случайный div_id Plotly),
никак не связанный с самими данными/правилами. siar/xlsx_determinism.py
и явные div_id в osf_report.py/region_report.py эту дыру закрывают —
здесь фиксируем это тестом, а не только ручной проверкой.

Требует реальные исходные файлы рейтингов в корне репозитория (тот же
пример, что и в predictions_examples/reports/examples) — пропускается,
если их нет (например, в CI без этих файлов).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OSF_PDF = ROOT / "Rei_ting-OSF-2025-_itog_-_1_.pdf"
REGION_XLSX = ROOT / "Rei_ting-regionov-Itogi-2025.xlsx"
MODEL_RISKS_CSV = ROOT / "predictions" / "model_risks.csv"
REGION_RISKS_CSV = ROOT / "predictions" / "region_risks.csv"

pytestmark = pytest.mark.skipif(
    not (OSF_PDF.exists() and REGION_XLSX.exists()
         and MODEL_RISKS_CSV.exists() and REGION_RISKS_CSV.exists()),
    reason="исходные файлы рейтингов/прогноза недоступны в этом окружении",
)


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"{cmd} упал:\n{result.stdout}\n{result.stderr}"


def test_osf_report_byte_identical_across_runs(tmp_path):
    out1, out2 = tmp_path / "run1", tmp_path / "run2"
    for out in (out1, out2):
        _run([sys.executable, str(ROOT / "siar" / "osf_report.py"),
              "--pdf", str(OSF_PDF), "--risks-csv", str(MODEL_RISKS_CSV), "--out", str(out)])

    xlsx1, xlsx2 = out1 / "osf_risk_final.xlsx", out2 / "osf_risk_final.xlsx"
    assert xlsx1.read_bytes() == xlsx2.read_bytes()

    html1, html2 = out1 / "osf_risk_dashboard_final.html", out2 / "osf_risk_dashboard_final.html"
    assert html1.read_bytes() == html2.read_bytes()


def test_region_report_byte_identical_across_runs(tmp_path):
    out1, out2 = tmp_path / "run1", tmp_path / "run2"
    for out in (out1, out2):
        _run([sys.executable, str(ROOT / "siar" / "region_report.py"),
              "--xlsx", str(REGION_XLSX), "--risks-csv", str(REGION_RISKS_CSV), "--out", str(out)])

    xlsx1, xlsx2 = out1 / "region_risk_final.xlsx", out2 / "region_risk_final.xlsx"
    assert xlsx1.read_bytes() == xlsx2.read_bytes()

    html1, html2 = out1 / "region_risk_dashboard.html", out2 / "region_risk_dashboard.html"
    assert html1.read_bytes() == html2.read_bytes()
