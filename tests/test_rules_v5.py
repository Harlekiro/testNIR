"""Этап 4: правила v5 (раздел 4 ТЗ) на маленьком искусственном примере; числа считаются вручную.

Кварталы 200 × 200 м (UTM 35N), площадь застройки — по контуру здания (поля нет):
  20 (x 0–200)      зона ТП1 → производственная
      a: 20 × 40 = 800 м², 1 этаж, без сервиса                       → шаг 6, 0
      b: 30 × 40 = 1 200 м², 1 этаж, без сервиса                     → шаг 5, 1 200 / 81
      c: 20 × 20 = 400 м², 1 этаж, точка metallurgy (норма 69)        → шаг 1, 400 / 69
      d: 20 × 20 = 400 м², 2 этажа, без сервиса                      → шаг 4, 800 / 69
      e: круг r = 10 м (32 вершины, S = 312,14 м²), без сервиса       → шаг 3, 0
      f: такой же круг с кафе (норма 28)                             → шаг 1, 312,14 / 28
  21 (x 300–500)    зона ТД1 → общественно-деловая
      g: круг r = 10 м без сервиса                                    → шаг 7, 312,14 / 50 (круг не сооружение вне П)
      h: 20 × 20, 3 этажа: кафе и два банка → тип bank (точек больше), норма 20 → шаг 1, 1 200 / 20
  22 (x 600–800)    зона ТЖ1 → прочее
      j: жилой 20 × 20, 5 этажей, 100 жителей, кафе внутри → встроенные B = min(1·100; 0,5·400) = 100 м² К → 100 / 28 (А)
      k: 20 × 20, 1 этаж: больница и поликлиника → по одной точке, большая норма 32 → шаг 2, 400 / 32
      l: 20 × 20, 2 этажа: школа на 270 мест и аптека нет — только школа → шаг 2, 270 / 13,5
      m: 20 × 20, 1 этаж, без сервиса                                → шаг 8, 0
  23 (x 900–1100)   зона ТП2 → производственная
      n: 20 × 20, 2 этажа, без сервиса                               → шаг 4, 800 / 69 — функция П по зданию
  24 (x 1200–1400)  зона ТД2 → общественно-деловая
      o: 20 × 20, 1 этаж, без сервиса                                → шаг 7, 400 / 50 — функции ОД нет (нет сервиса)
"""
import math
import os

import pytest

from conftest import write_fc, sq, pt
from mixuse.config import load_config
from mixuse.blocks import load_layers, build_table, DataError
from mixuse.compare import compare
from mixuse.checks import estimates_check, stats_check, threshold_check

CIRCLE = 0.5 * 32 * 100 * math.sin(2 * math.pi / 32)     # площадь правильного 32-угольника, r = 10 м


def circle(cx, cy, r=10, n=32):
    ring = [pt(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    return [ring + [ring[0]]]


def rect(x, y, w, h):
    return sq(x, y, w, h)


def make_v5(folder, pop_j=100, extra=''):
    d = os.path.join(folder, 'data')
    write_fc(os.path.join(d, 'blocks.geojson'), [('Polygon', sq(x, 0, 200), {'block_id': i})
                                                for i, x in zip(range(20, 25), [0, 300, 600, 900, 1200])])
    B = lambda geom, living=0, floors=1, pop=0: ('Polygon', geom, {'living': living, 'floors': floors, 'pop': pop})
    write_fc(os.path.join(d, 'buildings.geojson'), [
        B(rect(10, 10, 20, 40)),                    # a
        B(rect(50, 10, 30, 40)),                    # b
        B(rect(100, 10, 20, 20)),                   # c
        B(rect(140, 10, 20, 20), floors=2),         # d
        B(circle(50, 120)),                         # e
        B(circle(120, 120)),                        # f
        B(circle(350, 50)),                         # g
        B(rect(400, 10, 20, 20), floors=3),         # h
        B(rect(610, 10, 20, 20), living=1, floors=5, pop=pop_j),   # j
        B(rect(650, 10, 20, 20)),                   # k
        B(rect(690, 10, 20, 20), floors=2),         # l
        B(rect(730, 10, 20, 20)),                   # m
        B(rect(910, 10, 20, 20), floors=2),         # n
        B(rect(1210, 10, 20, 20)),                  # o
    ])
    sv = os.path.join(d, 'services')
    write_fc(os.path.join(sv, 'metallurgy.geojson'), [('Point', pt(110, 20), {})])
    write_fc(os.path.join(sv, 'cafe.geojson'), [('Point', pt(120, 120), {}), ('Point', pt(405, 15), {}), ('Point', pt(615, 15), {})])
    write_fc(os.path.join(sv, 'bank.geojson'), [('Point', pt(410, 20), {}), ('Point', pt(415, 25), {})])
    write_fc(os.path.join(sv, 'hospital.geojson'), [('Point', pt(655, 15), {})])
    write_fc(os.path.join(sv, 'polyclinic.geojson'), [('Point', pt(660, 20), {})])
    write_fc(os.path.join(sv, 'school.geojson'), [('Point', pt(700, 20), {'capacity': 270})])
    write_fc(os.path.join(d, 'zones.geojson'), [
        ('Polygon', sq(-10, -10, 220), {'code': 'ТП1'}), ('Polygon', sq(290, -10, 220), {'code': 'ТД1'}),
        ('Polygon', sq(590, -10, 220), {'code': 'ТЖ1'}), ('Polygon', sq(890, -10, 220), {'code': 'ТП2'}),
        ('Polygon', sq(1190, -10, 220), {'code': 'ТД2'})])
    cfg = os.path.join(folder, 'v5.yaml')
    with open(cfg, 'w', encoding='utf-8') as f:
        f.write(f"""name: v5small
mode: layers
rules: v5
blocks: data/blocks.geojson
block_id_field: block_id
buildings: data/buildings.geojson
fields: {{is_living: living, storeys: floors, population: pop}}
services: data/services
zones: data/zones.geojson
zone_field: code
zone_rules: [[ТП, П], [ТД, ОД]]
territory: [21]
scenarios:
  "Ж+К+ОД": {{Ж: 75, К: 5, ОД: 20, П: 0}}
  "ОД+П": {{Ж: 0, К: 10, ОД: 40, П: 50}}
{extra}""")
    return cfg


def build(cfg_path):
    cfg = load_config(cfg_path)
    L = load_layers(cfg, cfg['_groups'])
    return cfg, L, build_table(L, cfg, cfg['params'], cfg['_groups'])


@pytest.fixture
def v5(tmp_path):
    return build(make_v5(str(tmp_path)))


def by_block(city, col):
    t = city['table']
    return dict(zip(t.block_id.astype(int), t[col]))


EXPECTED_STEPS = {  # здание → (шаг, рабочих мест А, рабочих мест Б)
    'a': (6, 0, 0), 'b': (5, 0, 1200 / 81), 'c': (1, 400 / 69, 0), 'd': (4, 0, 800 / 69),
    'e': (3, 0, 0), 'f': (1, CIRCLE / 28, 0), 'g': (7, 0, CIRCLE / 50), 'h': (1, 1200 / 20, 0),
    'j': (0, 100 / 28, 0), 'k': (2, 400 / 32, 0), 'l': (2, 270 / 13.5, 0), 'm': (8, 0, 0),
    'n': (4, 0, 800 / 69), 'o': (7, 0, 400 / 50),
}


def test_v5_defaults(v5):
    cfg, _, _ = v5
    P = cfg['params']
    assert (P['a_К'], P['a_ОД'], P['a_П']) == (28, 15, 69) and 'a_X' not in P
    assert P['social_norms']['school'] == 13.5 and P['prod_min_footprint_one_storey'] == 1000


def test_each_building_by_hand(v5):
    _, _, city = v5
    b = city['detail']['buildings']
    assert len(b) == 14
    for (name, (step, ja, jb)), (_, row) in zip(EXPECTED_STEPS.items(), b.iterrows()):
        assert row['step'] == step, name
        assert row['jobs_A'] == pytest.approx(ja, rel=1e-4), name
        assert row['jobs_B'] == pytest.approx(jb, rel=1e-4), name
    assert b.loc[8, 'bi_К'] == pytest.approx(100) and b.loc[8, 'bi_ОД'] == 0      # дом j: встроенные помещения К


def test_totals_and_lower_bound(v5):
    _, _, city = v5
    A = sum(v[1] for v in EXPECTED_STEPS.values())
    Bj = sum(v[2] for v in EXPECTED_STEPS.values())
    t = city['table']
    assert t['jobs_A'].sum() == pytest.approx(A, rel=1e-4)    # площадь круга в UTM — точность ~0,01 м²
    assert t['jobs'].sum() == pytest.approx(A + Bj, rel=1e-4)
    assert city['report']['рабочих мест: нижняя граница (только А)'] == round(A)


def test_presence_rule_45(v5):
    _, _, city = v5
    K, OD, P = by_block(city, 'есть_К'), by_block(city, 'есть_ОД'), by_block(city, 'есть_П')
    assert K == {20: True, 21: True, 22: True, 23: False, 24: False}      # 22 — только встроенное помещение
    assert OD == {20: False, 21: True, 22: False, 23: False, 24: False}   # 24: здание зоны ОД без сервиса — функции нет
    assert P == {20: True, 21: False, 22: False, 23: True, 24: False}     # 23 — по зданию шага 4 без сервиса
    assert by_block(city, 'П_по_зданию')[23] and city['table'].n_П.sum() == 1


def test_population_rule_423(tmp_path):
    """У жилого дома j пусто в поле жителей: жители = (400 · 5 − 100) · 0,7 ÷ 30 = 44,3 — это 100 % прибавки → остановка."""
    with pytest.raises(DataError, match='4.2.3'):
        build(make_v5(str(tmp_path), pop_j=None))


def test_compare_v5_rows(v5):
    cfg, _, city = v5
    tb, info, _ = compare(city, cfg['territory'], cfg['params'], cfg['scenarios'])
    assert 'Доступ к П: получают / теряют, жителей' not in tb.index
    assert 'Жители в радиусе r от производства: до / после' in tb.index
    now = tb['Как есть']
    J_T0 = CIRCLE / 50 + 1200 / 20                     # квартал 21: g (Б) + h (А)
    assert now['Рабочие места на территории J'] == round(J_T0)
    assert now['Рабочие места на территории J, нижняя граница'] == round(1200 / 20)


def test_checks_483_485(v5, tmp_path):
    cfg, L, city = v5
    P, SCN, T = cfg['params'], cfg['scenarios'], cfg['territory']
    est = estimates_check(city, T, P, SCN)
    assert list(est['оценка']) == ['основная (А + Б)', 'нижняя граница (только А)']
    assert stats_check(city, P) is None                 # stat_jobs не задан
    thr = threshold_check(L, cfg, P, T, SCN)
    # порог 500: шаг 5 — b (1 200 м²) и a (800 м²); 1 000 — только b; 2 000 — ни одного
    assert list(thr['зданий шага 5']) == [2, 1, 0]
    assert list(thr['рабочих мест шага 5']) == [round(2000 / 81), round(1200 / 81), 0]
    cfg2 = load_config(make_v5(str(tmp_path / 's'), extra='params: {stat_jobs: 200}\n'))
    st = stats_check(city, cfg2['params'])
    assert list(st['рабочих мест']) == [round(city['table'].jobs.sum()), round(city['table'].jobs_A.sum()), 200]
