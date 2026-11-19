"""Этап 2: рабочий ноутбук v4 вызывает пакет, результат прежний.

Тест выполняет кодовые ячейки `метод_сравнения_вариантов.ipynb` подряд (без Jupyter) для примеров
spb, gatchina, vysotsk и сверяет файлы results/ с эталонами ноутбука v4 (tests/etalon).
Если данных примера нет (examples/), тест пропускается.
"""
import json
import os

import matplotlib
import pandas as pd
import pytest

from conftest import ROOT
from test_etalon import ETALON, etalon, same_strings

matplotlib.use('Agg')
pytestmark = pytest.mark.filterwarnings('ignore:FigureCanvasAgg is non-interactive')   # plt.show() без экрана
NOTEBOOK = os.path.join(ROOT, 'метод_сравнения_вариантов.ipynb')
# пример ноутбука → (код эталона, данные). Правила v4 — эталоны tests/etalon.
DATA = {'spb': ('spb', 'examples/spb_vasilievsky'), 'gatchina': ('gatchina', 'examples/gatchina'),
        'vysotsk_v4': ('vysotsk', 'examples/vysotsk')}


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


@pytest.fixture(scope='module', params=list(DATA))
def ran(request, tmp_path_factory):
    example = request.param
    code, data = DATA[example]
    if not os.path.exists(os.path.join(ROOT, data)):
        pytest.skip(f'нет данных примера {example}')
    out = str(tmp_path_factory.mktemp(example))
    run_notebook(example, out)
    return code, out


def got(out, code, name, **kw):
    return pd.read_csv(os.path.join(out, f'{code}_{name}.csv'), encoding='utf-8-sig', **kw)


def test_blocks_table(ran):
    code, out = ran
    ref, res = etalon(code, 'таблица_кварталов'), got(out, code, 'таблица_кварталов')
    assert list(ref.columns) == list(res.columns) and len(ref) == len(res)
    for c in ref.columns:
        a, b = ref[c], res[c]
        if pd.api.types.is_numeric_dtype(a) and not pd.api.types.is_bool_dtype(a):
            assert (a - b).abs().max() <= 0.1 + 1e-9, c       # граница округления, как в test_etalon
        else:
            norm = lambda s: s.astype(object).where(s.notna(), '').astype(str).to_numpy()
            assert (norm(a) == norm(b)).all(), c


@pytest.mark.parametrize('name, kw', [('сравнение_вариантов', {'index_col': 0}), ('устойчивость', {}), ('встроенные', {})])
def test_tables(ran, name, kw):
    code, out = ran
    path = os.path.join(ETALON, code, f'{code}_{name}.csv')
    if not os.path.exists(path):
        assert not os.path.exists(os.path.join(out, f'{code}_{name}.csv'))    # Гатчина «таблицей»: шага 7б нет
        return
    opts = dict(kw, dtype=str, keep_default_na=False)
    same_strings(etalon(code, name, **opts), got(out, code, name, **opts))


def test_web_json(ran):
    code, out = ran
    res = json.load(open(os.path.join(out, f'{code}_для_страницы.json'), encoding='utf-8'))
    ref = json.load(open(os.path.join(ETALON, code, f'{code}_для_страницы.json'), encoding='utf-8'))
    assert {k: v for k, v in res.items() if k != 'blocks'} == {k: v for k, v in ref.items() if k != 'blocks'}
    assert len(res['blocks']) == len(ref['blocks'])
    for a, b in zip(ref['blocks'], res['blocks']):
        for k in a:
            assert (abs(a[k] - b[k]) <= 1) if k == 'area' else (a[k] == b[k]), (a['id'], k)


def test_map_and_qgis_layer(ran):
    code, out = ran
    assert os.path.getsize(os.path.join(out, f'{code}_карта_С1.png')) > 10000
    layer = json.load(open(os.path.join(out, f'{code}_кварталы.geojson'), encoding='utf-8'))
    ref = json.load(open(os.path.join(ETALON, code, f'{code}_кварталы.geojson'), encoding='utf-8')) \
        if os.path.exists(os.path.join(ETALON, code, f'{code}_кварталы.geojson')) else None
    assert len(layer['features']) == len(etalon(code, 'таблица_кварталов'))
    if ref:
        assert [f['properties'] for f in layer['features']] == [f['properties'] for f in ref['features']]
