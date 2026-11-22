"""Рабочий ноутбук вызывает пакет: своих функций расчёта в нём нет.

run_notebook выполняет кодовые ячейки `метод_сравнения_вариантов.ipynb` подряд (без Jupyter) — им пользуются
test_etalon_v5 (ноутбук воспроизводит эталоны tests/etalon/v5) и приёмочный тест.
"""
import json
import os

os.environ['MIXUSE_PROVISION'] = 'fallback'   # эталоны — с запасным расчётом школ и садов (4.7.3)

import matplotlib
import pandas as pd
import pytest

from conftest import ROOT

matplotlib.use('Agg')
pytestmark = pytest.mark.filterwarnings('ignore:FigureCanvasAgg is non-interactive')   # plt.show() без экрана
NOTEBOOK = os.path.join(ROOT, 'метод_сравнения_вариантов.ipynb')


def code_cells():
    nb = json.load(open(NOTEBOOK, encoding='utf-8'))
    return [''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'code']


def run_notebook(example, out_dir):
    """Выполняет ноутбук с ПРИМЕР = example; результаты пишутся в out_dir. Рабочая папка — корень проекта."""
    ns = {'__name__': '__notebook__'}
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        for src in code_cells():
            src = src.replace('ПРИМЕР = None', f'ПРИМЕР = {example!r}').replace("OUT = 'results'", f'OUT = {out_dir!r}')
            exec(compile(src, NOTEBOOK, 'exec'), ns)
    finally:
        os.chdir(cwd)
        import matplotlib.pyplot as plt
        plt.close('all')
    return ns


def test_notebook_cells_use_package():
    """В ноутбуке нет своих функций расчёта — только вызовы пакета."""
    text = '\n'.join(code_cells())
    assert 'def ' not in text
    assert 'from mixuse' in text
