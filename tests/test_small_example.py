"""Маленький пример (conftest.py): общие свойства расчёта, не зависящие от норм.

Ручная проверка рабочих мест, встроенных помещений и показателей вариантов — test_rules_v5.py и test_variants_v5.py.
"""
import pytest

from mixuse.config import load_config
from mixuse.blocks import load_layers, build_table
from mixuse.compare import compare, TerritoryError


def table(cfg_path, **params):
    cfg = load_config(cfg_path)
    cfg['params'].update(params)
    L = load_layers(cfg, cfg['_groups'])
    city = build_table(L, cfg, cfg['params'], cfg['_groups'])
    return cfg, city, city['table'].set_index('block_id')


def test_nonliving_buildings_have_no_residents(tmp_path):
    """У нежилого здания жители = 0 и жилая площадь = 0, даже если в поле что-то записано."""
    from conftest import make_small, write_fc, sq
    cfg_path = make_small(str(tmp_path))
    write_fc(str(tmp_path / 'data' / 'buildings.geojson'), [
        ('Polygon', sq(1040, 40, 20), {'area': 400, 'living': 0, 'floors': 1, 'liv_area': 300, 'people': 25}),
        ('Polygon', sq(210, 10, 20), {'area': 400, 'living': 1, 'floors': 1, 'liv_area': 280, 'people': 9})])
    with open(cfg_path, encoding='utf-8') as f:
        txt = f.read().replace('living_area: liv_area}', 'living_area: liv_area, population: people}')
    with open(cfg_path, 'w', encoding='utf-8') as f:
        f.write(txt)
    _, city, t = table(cfg_path)
    assert t.at[13, 'pop'] == 0 and t.at[13, 'liv'] == 0
    assert t.at[11, 'pop'] == 9 and t.at[11, 'liv'] == 280
    assert city['report']['нежилых зданий с жителями в поле (обнулены)'] == 1


def test_territory_errors(small_cfg):
    cfg, city, _ = table(small_cfg)
    with pytest.raises(TerritoryError, match='не задана'):
        compare(city, [], cfg['params'], cfg['scenarios'])
    with pytest.raises(TerritoryError, match='99'):
        compare(city, [99], cfg['params'], cfg['scenarios'])
