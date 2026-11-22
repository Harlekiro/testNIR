"""Геометрия, пересчёт координат, проверка данных и командная строка."""
import json
import os

import numpy as np
import pytest

from conftest import make_small, write_fc, sq
from mixuse import geometry as g
from mixuse.cli import main
from mixuse.config import load_config, ConfigError
from mixuse.checks import check_config


# ---------- геометрия ----------

def test_area_and_point_in_polygon_with_hole():
    outer = np.array([[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], float)
    hole = np.array([[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]], float)
    poly = [[outer, hole]]
    assert g.poly_area(poly) == pytest.approx(96)
    inside = g.points_in_polygon(np.array([1.0, 5.0, 11.0]), np.array([1.0, 5.0, 5.0]), poly)
    assert inside.tolist() == [True, False, False]


def test_utm_known_points_and_roundtrip():
    # осевой меридиан зоны 35 (27°), широта 60°: E = 500 000, N = 0,9996 · дуга меридиана
    e, n = g.lonlat_to_utm([27.0, 60.0], 35)
    assert e == pytest.approx(500000, abs=1e-3) and n == pytest.approx(6651411.190, abs=0.01)
    pts = np.array([[28.5456453, 60.5924164], [24.1, 59.0], [30.9, 61.7]])
    back = g.utm_to_lonlat(g.lonlat_to_utm(pts, 35), 35)
    assert np.abs(back - pts).max() < 1e-9


def test_mercator_is_refused():
    with pytest.raises(g.CRSError, match='3857'):
        g.check_crs(3857, False, 'кварталы')


# ---------- проверка данных и настройки ----------

def test_check_reports_missing_field(tmp_path):
    cfg_path = make_small(str(tmp_path))
    cfg = load_config(cfg_path)
    cfg['fields']['is_living'] = 'нет_такого_поля'
    err, warn, info = check_config(cfg)
    assert any('жилое' in e for e in err)


def test_check_reports_mercator_layer(tmp_path):
    cfg_path = make_small(str(tmp_path))
    write_fc(os.path.join(str(tmp_path), 'data', 'zones.geojson'),
             [('Polygon', sq(0, 0, 100), {'code': 'ТП'})], crs='urn:ogc:def:crs:EPSG::3857')
    err, _, _ = check_config(load_config(cfg_path))
    assert any('3857' in e for e in err)


def test_config_errors(tmp_path):
    p = tmp_path / 'bad.yaml'
    p.write_text('blocks: x.geojson\nparams: {kitt: 2}\n', encoding='utf-8')
    with pytest.raises(ConfigError, match='kitt'):
        load_config(str(p))
    p.write_text('blocks: x.geojson\nparams: {builtin: может быть}\n', encoding='utf-8')
    with pytest.raises(ConfigError, match='да'):
        load_config(str(p))
    p.write_text('blocks: x.geojson\nparams: {builtin: нет}\n', encoding='utf-8')
    assert load_config(str(p))['params']['builtin'] is False


# ---------- командная строка ----------

def test_cli_full_run(tmp_path, capsys):
    cfg_path = make_small(str(tmp_path))
    out = str(tmp_path / 'results')
    assert main(['check', cfg_path]) == 0
    assert main(['blocks', cfg_path, '--out', out]) == 0
    assert main(['compare', cfg_path, '--out', out]) == 0
    files = sorted(os.listdir(out))
    for name in ['small_таблица_кварталов.csv', 'small_сравнение_вариантов.csv', 'small_сравнение_подробно.csv',
                 'small_устойчивость.csv', 'small_встроенные.csv', 'small_оценки.csv', 'small_порог_цеха.csv',
                 'small_кварталы.geojson', 'small_здания.csv', 'small_отчёт_подготовки.txt', 'small_карта_С2.png']:
        assert name in files, name
    gj = json.load(open(os.path.join(out, 'small_кварталы.geojson'), encoding='utf-8'))
    assert gj['crs']['properties']['name'].endswith('32635')
    assert sum(f['properties']['территория'] for f in gj['features']) == 1


def test_cli_no_territory_gives_clear_message(tmp_path, capsys):
    cfg_path = make_small(str(tmp_path), territory=())
    assert main(['compare', cfg_path, '--out', str(tmp_path / 'r'), '--fast']) == 2
    assert 'Территория не задана' in capsys.readouterr().out
    assert main(['compare', cfg_path, '--out', str(tmp_path / 'r'), '--fast', '--territory', '10,11']) == 0


def test_cli_init_makes_working_config(tmp_path):
    make_small(str(tmp_path))
    cfg_out = str(tmp_path / 'configs' / 'mine.yaml')
    assert main(['init', str(tmp_path / 'data'), '--name', 'mine', '-o', cfg_out]) == 0
    cfg = load_config(cfg_out)
    assert cfg['fields']['is_living'] == 'living' and cfg['fields']['storeys'] == 'floors'
    assert cfg['zone_field'] == 'code' and cfg['block_id_field'] == 'block_id'
    err, _, _ = check_config(cfg)
    assert err == []
