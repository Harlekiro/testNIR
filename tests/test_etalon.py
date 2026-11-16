"""Сверка с эталонами ноутбука (results/ из архива от 29.10.2026, прежний набор из 4 вариантов).

Эталоны посчитаны до введения встроенных помещений, поэтому здесь builtin = нет.
Допуск — совпадение округлённых значений; для площадей в таблице кварталов допускается
расхождение на 1 в последнем знаке (0,1 м²): это граница округления, она зависит от версии numpy.
Если данных примеров нет (examples/), тесты пропускаются.
"""
import os

import numpy as np
import pandas as pd
import pytest

from conftest import ROOT
from mixuse.config import load_config
from mixuse.blocks import load_layers, build_table
from mixuse.compare import compare
from mixuse.checks import sensitivity

ETALON = os.path.join(ROOT, 'tests', 'etalon')
CASES = ['spb', 'gatchina']


@pytest.fixture(scope='module', params=CASES)
def run(request):
    code = request.param
    cfg_path = os.path.join(ROOT, 'configs', f'{code}.yaml')
    cfg = load_config(cfg_path)
    if not os.path.exists(cfg['blocks']):
        pytest.skip(f'нет данных примера {code}')
    cfg['params']['builtin'] = False
    L = load_layers(cfg, cfg['_groups'])
    city = build_table(L, cfg, cfg['params'], cfg['_groups'])
    return code, cfg, city


def etalon(code, name, **kw):
    return pd.read_csv(os.path.join(ETALON, code, f'{code}_{name}.csv'), encoding='utf-8-sig', **kw)


def test_blocks_table(run):
    code, cfg, city = run
    ref = etalon(code, 'таблица_кварталов')
    got = city['table'].drop(columns=['cx', 'cy']).round(1).reset_index(drop=True)
    assert list(ref.columns) == [c for c in got.columns if c in ref.columns]
    assert len(ref) == len(got)
    for c in ref.columns:
        a, b = ref[c], got[c]
        if pd.api.types.is_numeric_dtype(a) and not pd.api.types.is_bool_dtype(a):
            diff = np.abs(a.to_numpy(float) - b.to_numpy(float))
            assert diff.max() <= 0.1 + 1e-9, f'{c}: расхождение {diff.max()}'
        else:
            norm = lambda s: s.astype(object).where(s.notna(), '').astype(str).to_numpy()   # пусто = пусто
            assert (norm(a) == norm(b)).all(), c


def test_comparison(run):
    code, cfg, city = run
    ref = etalon(code, 'сравнение_вариантов', index_col=0, dtype=str, keep_default_na=False)
    tb, info, _ = compare(city, cfg['territory'], cfg['params'], cfg['scenarios'])
    got = tb.astype(str).replace('nan', '')
    assert list(ref.index) == list(got.index)
    assert list(ref.columns) == list(got.columns)
    assert (ref.to_numpy() == got.to_numpy()).all(), (ref.compare(got) if ref.shape == got.shape else '')


def test_stability(run):
    code, cfg, city = run
    ref = etalon(code, 'устойчивость', dtype=str, keep_default_na=False)
    got = sensitivity(city, cfg['territory'], cfg['params'], cfg['scenarios'])
    got.to_csv(os.devnull)
    got = got.astype(str)
    assert list(ref.columns) == list(got.columns)
    assert (ref.to_numpy() == got.to_numpy()).all()


def test_spb_control_numbers_without_builtin(run):
    """Контрольные числа ТЗ (раздел 8) для builtin = нет: J_E = 50 296, рабочих мест 212 086."""
    code, cfg, city = run
    if code != 'spb':
        pytest.skip('только для spb')
    _, info, _ = compare(city, cfg['territory'], cfg['params'], cfg['scenarios'])
    assert city['report']['кварталов'] == 251
    assert city['report']['рабочих мест (оценка)'] == 212086
    assert info['рабочих мест в окружении'] == 50296
    assert info['жителей в окружении'] == 49340
    assert info['кварталов в окружении'] == 52
    assert info['поэтажная площадь F, м²'] == 346114


@pytest.mark.xfail(strict=True, reason='Числа ТЗ со встроенными помещениями получены более новой версией ноутбука, '
                                       'которой у нас нет: 350 домов / 56 325 / 8 367 м² вместо 345 / 56 390 / 7 300; '
                                       'жителей 208 713 вместо 208 524. Ждём ноутбук или правило от автора.')
def test_spb_control_numbers_with_builtin():
    cfg = load_config(os.path.join(ROOT, 'configs', 'spb.yaml'))
    if not os.path.exists(cfg['blocks']):
        pytest.skip('нет данных примера spb')
    L = load_layers(cfg, cfg['_groups'])
    city = build_table(L, cfg, cfg['params'], cfg['_groups'])
    r = city['report']
    assert r['жилых домов со встроенными помещениями'] == 345
    assert (r['встроенная площадь К, м²'], r['встроенная площадь ОД, м²']) == (56390, 7300)
    assert r['жителей'] == 208524 and r['рабочих мест (оценка)'] == 214062
