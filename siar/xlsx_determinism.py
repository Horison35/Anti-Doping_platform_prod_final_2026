# -*- coding: utf-8 -*-
"""siar/xlsx_determinism.py — побайтовая воспроизводимость .xlsx (LOGIC.md §1).

Два независимых источника недетерминизма в файле, который пишет openpyxl,
ни один не лечится публичным API openpyxl:

1. openpyxl пишет .xlsx как обычный zip через stdlib `zipfile`, который по
   умолчанию проставляет каждому файлу внутри архива ZipInfo.date_time =
   текущее время — независимо от workbook.properties (те влияют только на
   содержимое docProps/core.xml, не на сам контейнер zip).
2. `Workbook.save()` сам перезаписывает `dcterms:modified` в docProps/core.xml
   временем сохранения, даже если workbook.properties.modified был выставлен
   заранее в вызывающем коде — то есть выставить его до save() бесполезно.

Оба лечатся только пост-обработкой уже сохранённого файла; содержимое
(порядок файлов, байты, сжатие) при этом не меняется — правится только
метаданные архива и одна строка в core.xml.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Union

_FIXED_DATE_TIME = (2000, 1, 1, 0, 0, 0)
_MODIFIED_RE = re.compile(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)")
_FIXED_MODIFIED = b"2000-01-01T00:00:00Z"


def normalize_xlsx_timestamps(path: Union[str, Path]) -> None:
    """Переписывает .xlsx на месте: фиксирует ZipInfo.date_time и dcterms:modified."""
    path = Path(path)
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    with zipfile.ZipFile(path, "r") as src:
        infos = src.infolist()
        contents = [src.read(info.filename) for info in infos]

    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as dst:
        for info, data in zip(infos, contents):
            info.date_time = _FIXED_DATE_TIME
            if info.filename == "docProps/core.xml":
                data = _MODIFIED_RE.sub(rb"\1" + _FIXED_MODIFIED + rb"\2", data)
            dst.writestr(info, data)

    tmp_path.replace(path)
