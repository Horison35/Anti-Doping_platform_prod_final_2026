# -*- coding: utf-8 -*-
"""tests/test_watch_registry.py — файл-триггер автопереобучения.

Проверяем: стабилизация размера файла перед обработкой, успешный файл
уходит в _processed/, а файл, на котором retrain.py упал (повреждён/
неполон), уходит в _failed/ — и не трогает ничего в самой БД/модели
(это гарантирует retrain.py, здесь важно только правильное перемещение).
"""
from __future__ import annotations

import subprocess

from ml import watch_registry as wr


def test_wait_until_stable_true_for_static_file(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "STABLE_CHECKS", 2)
    monkeypatch.setattr(wr, "STABLE_INTERVAL_SECONDS", 0.01)
    f = tmp_path / "a.xlsx"
    f.write_bytes(b"1234")
    assert wr.wait_until_stable(f) is True


def test_wait_until_stable_false_for_missing_file(tmp_path):
    assert wr.wait_until_stable(tmp_path / "does_not_exist.xlsx") is False


def test_process_new_file_success_moves_to_processed(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "wait_until_stable", lambda p: True)
    monkeypatch.setattr(
        wr.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(args=a, returncode=0, stdout="ok", stderr=""),
    )
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    f = inbox / "new.xlsx"
    f.write_bytes(b"data")

    wr.process_new_file(f, inbox / "_processed", inbox / "_failed")

    assert not f.exists()
    assert (inbox / "_processed" / "new.xlsx").exists()
    assert not (inbox / "_failed").exists()


def test_process_new_file_failure_moves_to_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "wait_until_stable", lambda p: True)
    monkeypatch.setattr(
        wr.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(
            args=a, returncode=1, stdout="", stderr="Обязательная колонка 'Вид спорта' отсутствует"
        ),
    )
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    f = inbox / "broken.xlsx"
    f.write_bytes(b"data")

    wr.process_new_file(f, inbox / "_processed", inbox / "_failed")

    assert not f.exists()
    assert (inbox / "_failed" / "broken.xlsx").exists()
    assert not (inbox / "_processed").exists()


def test_process_new_file_skips_when_not_stable(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(wr, "wait_until_stable", lambda p: False)
    monkeypatch.setattr(wr.subprocess, "run", lambda *a, **k: called.append(1))

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    f = inbox / "still_copying.xlsx"
    f.write_bytes(b"data")

    wr.process_new_file(f, inbox / "_processed", inbox / "_failed")

    assert called == []  # retrain.py не вызывался
    assert f.exists()  # файл остался на месте — попробуем в следующий опрос
