"""Этап 5: варианты v5 (4.6), выбор КИТ (4.6.2, 5.1), краткая таблица и вывод (4.7.0).

Маленький пример — test_rules_v5.make_v5; территория — квартал 21. Окружение (центр не дальше 800 м от контура
квартала 21, x 300–500): кварталы 20 (центр x = 100, 200 м), 22 (700, 200 м), 23 (1 000, 500 м), 24 (1 300, ровно 800 м).
КИТ окружения = Σ поэтажной площади всех зданий E ÷ Σ площади кварталов E:
  кв. 20: 800 + 1 200 + 400 + 800 + 312,14 + 312,14 = 3 824,29;  кв. 22: 2 000 + 400 + 800 + 400 = 3 600;
  кв. 23: 800;  кв. 24: 400  →  8 624,29 ÷ (4 · 40 000) = 0,0539 → 0,05.
"""
import pytest

from test_rules_v5 import make_v5, build, CIRCLE
from mixuse.compare import compare, conclusion, choose_kit, environment, territory_indices
from mixuse.params import SCENARIOS_V5
from mixuse.config import load_config, param_origins


def test_default_scenarios_v5(tmp_path):
    p = make_v5(str(tmp_path))
    text = open(p, encoding='utf-8').read()
    start = text.index('scenarios:')
    end = text.index('\n', text.index('"ОД+П"'))
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text[:start] + text[end + 1:])                # без своих вариантов → пять вариантов 4.6.1
    cfg = load_config(p)
    assert cfg['scenarios'] == SCENARIOS_V5
    assert list(cfg['scenarios']) == ['Ж+К', 'Ж+К+ОД', 'К+ОД', 'ОД+П', 'Ж+П']
    assert cfg['scenarios']['Ж+К+ОД'] == {'Ж': 75, 'К': 5, 'ОД': 20, 'П': 0}


def test_kit_by_data(tmp_path):
    cfg, L, city = build(make_v5(str(tmp_path)))
    t = city['table']
    T = territory_indices(t, [21])
    E, _, _ = environment(city, T, 800)
    assert sorted(t.block_id.iloc[E]) == [20, 22, 23, 24]
    fa = 800 + 1200 + 400 + 800 + 2 * CIRCLE + 2000 + 400 + 800 + 400 + 800 + 400
    kit, how, kitE, warn = choose_kit(t, E, cfg['params'])
    assert kitE == pytest.approx(fa / 160000, rel=1e-4) and kit == 0.05 and how.startswith('по данным')
    assert warn is None                                           # этажность указана у всех зданий
    full, info, det = compare(city, [21], cfg['params'], cfg['scenarios'])
    F = 40000 * 0.05
    assert info['поэтажная площадь F, м²'] == round(F)
    assert full.loc['Жители на территории N', 'Ж+К+ОД'] == round(F * 0.75 * 0.7 / 30)
    assert full.loc['Рабочие места на территории J', 'Ж+К+ОД'] == round(F * (0.05 / 28 + 0.20 / 15))
    origins = {k: how for k, _, how in param_origins(cfg, info)}
    assert origins['kit'].startswith('по данным') and origins['R'] == 'по умолчанию — без источника'


def test_kit_user_and_warning(tmp_path):
    cfg, L, city = build(make_v5(str(tmp_path), extra='params: {kit: 1.4}\nparam_sources: {kit: ПЗЗ}\n'))
    full, info, det = compare(city, [21], cfg['params'], cfg['scenarios'])
    assert (info['КИТ варианта'], info['КИТ: откуда']) == (1.4, 'пользователь')
    assert dict((k, h) for k, _, h in param_origins(cfg, info))['kit'] == 'пользователь: ПЗЗ'
    # предупреждение «КИТ занижен»: больше половины зданий окружения без этажности
    t = city['table'].copy()
    t['n_bld_default'] = t['n_bld']
    T = territory_indices(t, [21])
    E, _, _ = environment(city, T, 800)
    assert 'занижен' in choose_kit(t, E, cfg['params'])[3]


def test_short_table_rows(tmp_path):
    cfg, L, city = build(make_v5(str(tmp_path)))
    full, info, det = compare(city, [21], cfg['params'], cfg['scenarios'])
    assert list(det['short'].index) == [
        'Жители на территории', 'Рабочие места на территории (изменение к нынешним)', 'Рабочих мест на жителя в окружении',
        'Доступ к торговле и услугам: получают / теряют, жителей', 'Доступ к общественно-деловой функции: получают / теряют',
        'Жители рядом с производством', 'Школьники / дошкольники с территории (без свободного места в окружении)', 'Вывод']
    assert det['short'].loc['Вывод', 'Как есть'] == '—'
    assert 'Школы: не хватает мест' not in full.index            # 4.7.3: формула «нехватка после − как есть» не используется


def V(N, J, dJ, K, acc, sNo=0.0, kNo=0.0):
    return dict(N=N, J=J, dJ=dJ, K=K, acc=acc, sNo=sNo, kNo=kNo)


BASE = V(0, 100, None, 0.50, {})
NO = {'К': (0, 0), 'ОД': (0, 0), 'П': (10, 10)}


def test_conclusion_phrases():
    """Фразы 4.7.0 по порядку; числа — через тире или в скобках; без оценок и сравнения вариантов."""
    assert conclusion(V(1234.4, 50, -50, 0.52, NO), BASE) == (
        'Новых жителей — 1 234, рабочих мест — 50; к нынешним рабочим местам −50; '
        'рабочих мест на жителя в окружении почти без изменений: 0.50 → 0.52; '
        'доступ к торговле и общественно-деловой функции без изменений; '
        'свободных мест в школах и садах окружения хватает.')
    acc = {'К': (120, 0), 'ОД': (0, 35), 'П': (300, 100)}
    assert conclusion(V(0, 2500, 2400, 0.80, acc), BASE) == (
        'Жилья нет, рабочих мест — 2 500; к нынешним рабочим местам +2 400; '
        'рабочих мест на жителя в окружении больше: 0.50 → 0.80; '
        'доступ к торговле и услугам получают жители (120 чел.); '
        'доступ к общественно-деловой функции теряют жители (35 чел.); '
        'рядом с производством жителей меньше на 200.')
    text = conclusion(V(500, 10, -90, 0.40, {'К': (0, 0), 'ОД': (0, 0), 'П': (0, 50)}, sNo=12.4, kNo=0.2), BASE)
    assert 'меньше: 0.50 → 0.40' in text and 'рядом с производством жителей больше на 50' in text
    assert text.endswith('без свободного места в окружении: школьники — 12, дошкольники — 0.')
