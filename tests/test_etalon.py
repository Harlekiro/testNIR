"""Сверка с эталонами ноутбука v4 (results/ из метод_сравнения_вариантов_v4.zip, 16.11.2026).

Эталоны посчитаны со встроенными помещениями (builtin = да) на прежнем наборе из 4 вариантов.
Допуск — совпадение округлённых значений; для площадей допускается расхождение на 1 в последнем
знаке: это граница округления, она зависит от версии numpy (в Гатчине — 2 квартала в таблице и 1 в JSON).
Если данных примеров нет (examples/), тесты пропускаются.
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

from conftest import ROOT
from mixuse.config import load_config
from mixuse.blocks import load_layers, build_table
from mixuse.compare import compare
from mixuse.checks import sensitivity, builtin_sensitivity
from mixuse import export

ETALON = os.path.join(ROOT, 'tests', 'etalon')
CASES = ['spb', 'gatchina', 'vysotsk']


def _load(code, **params):
    cfg = load_config(os.path.join(ROOT, 'configs', 'legacy', f'{code}.yaml'))
    if not os.path.exists(cfg['blocks']):
        pytest.skip(f'нет данных примера {code}')
    cfg['params'].update(params)
    L = load_layers(cfg, cfg['_groups'])
    return cfg, L, build_table(L, cfg, cfg['params'], cfg['_groups'])


@pytest.fixture(scope='module', params=CASES)
def run(request):
    cfg, L, city = _load(request.param)
    return request.param, cfg, L, city


def etalon(code, name, **kw):
    return pd.read_csv(os.path.join(ETALON, code, f'{code}_{name}.csv'), encoding='utf-8-sig', **kw)


def same_strings(ref, got):
    assert list(ref.columns) == list(got.columns)
    assert list(map(str, ref.index)) == list(map(str, got.index))
    bad = ref.to_numpy() != got.to_numpy()
    assert not bad.any(), ref.where(bad).stack().to_dict()


def test_blocks_table(run):
    code, cfg, L, city = run
    ref = etalon(code, 'таблица_кварталов')
    got = city['table'].drop(columns=['cx', 'cy']).round(1).reset_index(drop=True)
    assert list(ref.columns) == list(got.columns)
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
    code, cfg, L, city = run
    ref = etalon(code, 'сравнение_вариантов', index_col=0, dtype=str, keep_default_na=False)
    tb, _, _ = compare(city, cfg['territory'], cfg['params'], cfg['scenarios'])
    same_strings(ref, tb.astype(str))


def test_stability(run):
    code, cfg, L, city = run
    ref = etalon(code, 'устойчивость', dtype=str, keep_default_na=False)
    got = sensitivity(city, cfg['territory'], cfg['params'], cfg['scenarios'])
    same_strings(ref, got.astype(str))


def test_builtin_step_7b(run):
    code, cfg, L, city = run
    got = builtin_sensitivity(L, cfg, cfg['params'], cfg['territory'], cfg['scenarios'])
    path = os.path.join(ETALON, code, f'{code}_встроенные.csv')
    if not os.path.exists(path):
        assert got is None            # режим «таблица»: шаг 7б не считается
        return
    same_strings(etalon(code, 'встроенные', dtype=str, keep_default_na=False), got.astype(str))


def test_web_json(run, tmp_path):
    code, cfg, L, city = run
    p = export.web_json(city, cfg, str(tmp_path / 'web.json'))
    got = json.load(open(p, encoding='utf-8'))
    ref = json.load(open(os.path.join(ETALON, code, f'{code}_для_страницы.json'), encoding='utf-8'))
    assert {k: v for k, v in got.items() if k != 'blocks'} == {k: v for k, v in ref.items() if k != 'blocks'}
    assert len(got['blocks']) == len(ref['blocks'])
    for a, b in zip(ref['blocks'], got['blocks']):
        for k in a:
            if k == 'area':
                assert abs(a[k] - b[k]) <= 1, (a['id'], k)
            else:
                assert a[k] == b[k], (a['id'], k)


def test_spb_control_numbers():
    """Контрольные числа ТЗ, раздел 8 (Васильевский остров, территория 8346, 9366, 2059)."""
    cfg, L, city = _load('spb')
    r = city['report']
    assert r['кварталов'] == 251 and r['жителей'] == 208524 and r['рабочих мест (оценка)'] == 214062
    assert r['K_ref — рабочих мест на жителя в среднем'] == 1.027
    assert r['жилых домов со встроенными помещениями'] == 345
    assert r['  встроенная площадь К / ОД, м²'] == '56390 / 7300'
    tb, info, _ = compare(city, cfg['territory'], cfg['params'], cfg['scenarios'])
    assert round(city['table'].area.iloc[[int(i) for i in np.where(city['table'].block_id.isin(cfg['territory']))[0]]].sum()) == 247224
    assert info['поэтажная площадь F, м²'] == 346114
    assert (info['кварталов в окружении'], info['жителей в окружении'], info['рабочих мест в окружении']) == (52, 49340, 50892)
    now, c1 = tb['Как есть'], tb['С1 Ж+ОД']
    assert (now['Жители на территории N'], now['Рабочие места на территории J']) == (0, 3040)
    assert (c1['Жители на территории N'], c1['Рабочие места на территории J'], c1['Изменение рабочих мест к нынешним']) == (4846, 6181, 3141)
    assert (c1['Работа на жителя K: окружение'], now['Работа на жителя K: окружение']) == (1.05, 1.09)
    assert (c1['Работа на жителя K: все данные'], now['Работа на жителя K: все данные']) == (1.02, 1.03)
    assert (c1['Школы: не хватает мест'], c1['Сады: не хватает мест']) == (731, 915)
    assert c1['Доступ к П: получают / теряют, жителей'] == '+0 / −3 241'


def test_spb_control_numbers_without_builtin():
    """При builtin = нет — как до введения встроенных помещений: J_E = 50 296, рабочих мест 212 086."""
    cfg, L, city = _load('spb', builtin=False)
    _, info, _ = compare(city, cfg['territory'], cfg['params'], cfg['scenarios'])
    assert city['report']['рабочих мест (оценка)'] == 212086
    assert info['рабочих мест в окружении'] == 50296
