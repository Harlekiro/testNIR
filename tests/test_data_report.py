"""Этап 3: настройки наборов v5, правило 4.1.2 (одна система координат), отчёт о данных.

Числа маленького примера (conftest.py) посчитаны вручную:
  здания в кварталах — 6: жилых 2 (дом 5 этажей в кв. 11; дом 1 этаж в кв. 12), нежилых 4;
  нежилых от S_min = 200 м² — 3: склад 400 м² (кв. 10, 2 этажа), 225 м² (кв. 11, 1 этаж), 400 м² (кв. 13, этажность пуста);
  этажность пуста — 1 нежилое (кв. 13), оно же среди нежилых от S_min → 1 из 3;
  указан 1 этаж — жилые: 1 из 2; нежилые от S_min: 1 из 3;
  школа на 100 мест — с местами; детский сад — без мест;
  точка П — склад (warehouse) в контуре нежилого здания 400 м²;
  зоны: кв. 10 — ТП1 (П), кв. 11 — ТД1 (ОД), кв. 12 — без зоны, кв. 13 — ТР2;
  производственная зона: поэтажная площадь 400 · 2 = 800 м², одноэтажных без сервиса — 0; кварталов П без точек — 0 из 1.
"""
import json
import os

import pytest

from conftest import ROOT, make_small, WGS
from mixuse.config import load_config, ConfigError
from mixuse.checks import check_config
from mixuse.blocks import load_layers, build_table
from mixuse.data_report import data_report


def _edit(path, old, new):
    """Заменяет текст в файле настроек (сначала читает, потом пишет)."""
    text = open(path, encoding='utf-8').read()
    assert old in text, old
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace(old, new))


def _city(cfg_path):
    cfg = load_config(cfg_path)
    L = load_layers(cfg, cfg['_groups'])
    return cfg, build_table(L, cfg, cfg['params'], cfg['_groups'])


def _report(cfg_path):
    cfg, city = _city(cfg_path)
    lines, warns = data_report(city, cfg, cfg['params'])
    return '\n'.join(lines), warns


def test_rules_key(tmp_path):
    cfg = load_config(make_small(str(tmp_path)))
    assert cfg['rules'] == 'v4'
    p = make_small(str(tmp_path / 'b'))
    _edit(p, 'rules: v4\n', '')
    assert load_config(p)['rules'] == 'v5'                       # по умолчанию — v5 (ТЗ, раздел 9)
    _edit(p, 'mode: layers\n', 'mode: layers\nrules: v3\n')
    with pytest.raises(ConfigError, match='rules'):
        load_config(p)


def test_mixed_crs_is_error_in_v5_warning_in_v4(tmp_path):
    p4 = make_small(str(tmp_path / 'a'), other_crs=WGS)
    err, warn, _ = check_config(load_config(p4))
    assert not err and any('разных системах координат' in w for w in warn)
    p5 = make_small(str(tmp_path / 'b'), other_crs=WGS)
    _edit(p5, 'rules: v4', 'rules: v5')
    err, _, _ = check_config(load_config(p5))
    assert any('4.1.2' in e for e in err)


def test_param_sources(tmp_path):
    p = make_small(str(tmp_path), extra='params: {kit: 1.4}\nparam_sources: {kit: ПЗЗ}\n')
    assert load_config(p)['param_sources'] == {'kit': 'ПЗЗ'}
    p = make_small(str(tmp_path / 'b'), extra='param_sources: {kitt: ПЗЗ}\n')
    with pytest.raises(ConfigError, match='kitt'):
        load_config(p)


def test_small_report_by_hand(small_cfg):
    text, warns = _report(small_cfg)
    assert 'Кварталов: 4; в производственной зоне — 1, в общественно-деловой — 1, без зоны — 1' in text
    assert 'Здания в кварталах: 6 (жилых 2, нежилых 4, из них нежилых от S_min = 200 м² — 3)' in text
    assert 'жилые — 0 из 2 (0.0 %)' in text and 'нежилые — 1 из 4 (25.0 %)' in text
    assert 'нежилые от S_min — 1 из 3 (33.3 %)' in text
    assert 'Указан 1 этаж: жилые — 1 из 2 (50.0 %); нежилые от S_min — 1 из 3 (33.3 %)' in text
    assert 'Поле жителей не задано' in text
    assert 'Школ без числа мест: 0 из 1 (0.0 %); мест всего 100' in text
    assert 'Детских садов без числа мест: 1 из 1 (100.0 %); мест всего 0' in text
    assert ('Точки производственных сервисов (группа П) в кварталах: 1; в контуре здания — 1, '
            'в контуре нежилого здания от S_min — 1; вне кварталов (не учитываются) — 0') in text
    assert 'поэтажная площадь нежилых зданий от S_min — 800 м²; из неё в одноэтажных без сервиса в контуре — 0 м² (0 %)' in text
    assert 'Производственных кварталов без точек П: 0 из 1' in text
    assert any('33 % нежилых зданий' in w for w in warns)        # больше 10 % без этажности → подсказка 4.9.2


def test_small_report_population_rule_423(tmp_path):
    """Поле жителей задано; у дома 5 этажей (кв. 11) оно пустое.
    Встроенные помещения: B = min(2 · 100; 0,5 · 400) = 200 м²; жилая площадь (400 · 5 − 200) · 0,7 = 1 260 м²;
    прибавка 1 260 ÷ 30 = 42 жителя к 2 (дом в кв. 12) → больше 1 % → предупреждение."""
    p = make_small(str(tmp_path))
    bpath = os.path.join(str(tmp_path), 'data', 'buildings.geojson')
    fc = json.load(open(bpath, encoding='utf-8'))
    for f, pop in zip(fc['features'], [0, None, 0, 2, 0, 0]):
        f['properties']['pop'] = pop
    json.dump(fc, open(bpath, 'w', encoding='utf-8'), ensure_ascii=False)
    _edit(p, 'liv_area}', 'liv_area, population: pop}')
    text, warns = _report(p)
    assert 'Жилые дома без числа жителей: 1 из 2 (50.0 %)' in text
    assert '+42 к 2 (2100.00 %)' in text
    assert any('больше 1 %' in w for w in warns)


# ---------- настройки трёх наборов v5 ----------

def _cfg(code):
    cfg = load_config(os.path.join(ROOT, 'configs', f'{code}.yaml'))
    if not os.path.exists(cfg['blocks']):
        pytest.skip(f'нет данных набора {code}')
    return cfg


@pytest.mark.parametrize('code', ['spb_full', 'gatchina_layers', 'vysotsk'])
def test_v5_configs_pass_check(code):
    cfg = _cfg(code)
    assert cfg['rules'] == 'v5'
    if code == 'spb_full':
        assert cfg['params']['kit'] == 1.4 and 'ПЗЗ' in cfg['params']['kit_source']
    else:
        assert cfg['params']['kit_sp_row'] == {'gatchina_layers': 'zh_multi', 'vysotsk': 'zh_low_mid'}[code]   # ТЗ 17
    err, warn, info = check_config(cfg)
    assert not err, err
    assert not any('разных системах' in w for w in warn)


def test_gatchina_layers_report():
    """ТЗ 4.1.4 и 4.1.6: 517 кварталов; 12 заводов — 11 в кварталах, 10 в контуре здания
    (комбикормовый завод — вне слоя кварталов, «Новая высота» — в квартале без здания); жителей 91 464 (раздел 9)."""
    cfg = _cfg('gatchina_layers')
    cfg_, city = _city(cfg['_path'])
    lines, _ = data_report(city, cfg_, cfg_['params'])
    text = '\n'.join(lines)
    assert len(city['table']) == 517 and city['report']['жителей'] == 91464
    assert ('в кварталах: 11; в контуре здания — 10, в контуре нежилого здания от S_min — 10; '
            'вне кварталов (не учитываются) — 1') in text
    assert '«Новая высота» [woodworking] — вне контуров зданий' in text
