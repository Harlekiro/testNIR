"""Расчёт на маленьком примере (conftest.py) — числа посчитаны вручную.

Параметры по умолчанию: k_liv = 0,7; q = 30; a_К = 35, a_ОД = 20, a_П = 70, a_X = 50; S_min = 200;
встроенные помещения: s0 = 100 м², β = 0,5, дом не ниже 2 этажей; КИТ = 1,4; R = 800; r = 500;
школы 110, сады 60 мест на 1000 жителей.
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


def test_blocks_table_by_hand(small_cfg):
    cfg, city, t = table(small_cfg)
    # квартал 10: склад 20×20, 2 этажа → A = 800 м², группа П (сервис warehouse внутри)
    assert t.at[10, 'nr_П'] == pytest.approx(800)
    assert t.at[10, 'jobs'] == pytest.approx(800 / 70)
    # квартал 11: жилой дом 20×20, 5 этажей → A = 2000; внутри 1 К и 1 ОД → B = min(2·100, 0,5·400) = 200
    assert t.at[11, 'встр_К'] == pytest.approx(100) and t.at[11, 'встр_ОД'] == pytest.approx(100)
    #   жилая площадь (A − B)·k_liv = 1800·0,7 = 1260; поля жителей нет → 1260 / 30 = 42
    assert t.at[11, 'liv'] == pytest.approx(1260)
    assert t.at[11, 'pop'] == pytest.approx(42)
    #   нежилое 15×15 без сервисов, зона ТД1 → ОД: 225 м² + встроенные 100 м²
    assert t.at[11, 'nr_ОД'] == pytest.approx(325) and t.at[11, 'nr_К'] == pytest.approx(100)
    assert t.at[11, 'jobs'] == pytest.approx(100 / 35 + 325 / 20)
    assert (t.at[11, 'n_К'], t.at[11, 'n_ОД']) == (1, 1)
    # квартал 12: дом в 1 этаж — без встроенных; жилая площадь из поля 50 м²; нежилое 10×10 < S_min не учтено
    assert t.at[12, 'liv'] == pytest.approx(50) and t.at[12, 'pop'] == pytest.approx(50 / 30)
    assert t.at[12, 'jobs'] == 0 and t.at[12, 'cap_school'] == 100
    # квартал 13: этажность не указана → 1 этаж; зона ТР2 → X: 400/50 = 8
    assert t.at[13, 'nr_X'] == pytest.approx(400) and t.at[13, 'jobs'] == pytest.approx(8)
    r = city['report']
    assert r['зданий без этажности (принят 1 этаж)'] == 1
    assert r['детских садов без числа мест (принято 0 мест)'] == 1
    assert r['жилых домов со встроенными помещениями'] == 1
    assert r['  встроенная площадь К / ОД, м²'] == '100 / 100'
    assert r['нежилых зданий меньше S_min (не учтены)'] == 1
    assert r['типы не из таблицы групп (не учтены)'] == ['outpost']
    assert (r['нежилых зданий в группе П'], r['нежилых зданий в группе ОД'], r['нежилых зданий в группе X']) == (1, 1, 1)


def test_builtin_off(small_cfg):
    _, _, t = table(small_cfg, builtin=False)
    assert t.at[11, 'nr_ОД'] == pytest.approx(225) and t.at[11, 'nr_К'] == 0
    assert t.at[11, 'liv'] == pytest.approx(2000 * 0.7)
    assert t.at[11, 'pop'] == pytest.approx(2000 * 0.7 / 30)
    assert bool(t.at[11, 'есть_К'])          # кафе есть — функция К в квартале есть


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


def test_compare_by_hand(small_cfg):
    cfg, city, t = table(small_cfg)
    tb, info, det = compare(city, cfg['territory'], cfg['params'], cfg['scenarios'])
    popE = 42 + 50 / 30                       # жители окружения (кварталы 11 и 12)
    jobsE = 100 / 35 + 325 / 20
    jobsT0 = 800 / 70
    popA, jobsA = popE, jobsE + jobsT0 + 8    # все кварталы (на территории жителей нет)
    # окружение: центры 11 и 12 в 150 м от территории, 13 — в 950 м (> R = 800)
    assert info['кварталов в окружении'] == 2
    assert info['поэтажная площадь F, м²'] == 14000            # S = 10 000 м² · КИТ 1,4
    c = tb['С1 Ж+ОД']
    N = 14000 * 0.6 * 0.7 / 30                                   # 196
    J = 14000 * (0.1 / 35 + 0.3 / 20)                            # 250
    assert c['Жители на территории N'] == 196 and c['Рабочие места на территории J'] == 250
    assert c['Изменение рабочих мест к нынешним'] == round(J - jobsT0)
    assert c['Работа на жителя K: окружение'] == round((jobsE + J) / (popE + N), 2)
    assert c['Работа на жителя K: все данные'] == round((jobsA - jobsT0 + J) / (popA + N), 2)
    assert tb.at['Работа на жителя K: окружение', 'Как есть'] == round((jobsE + jobsT0) / popE, 2)
    assert tb.at['Изменение рабочих мест к нынешним', 'Как есть'] == '—'
    # П было только на территории → после замены жители 11 и 12 теряют доступ к П
    assert c['Доступ к П: получают / теряют, жителей'] == f'+0 / −{popE:.0f}'
    assert c['Доступ к К: получают / теряют, жителей'] == '+0 / −0'
    # в варианте С2 есть П (50 %) и территория ближе r → доступ сохраняется
    assert tb.at['Доступ к П: получают / теряют, жителей', 'С2 ОД+П'] == '+0 / −0'
    # школы: «как есть» 100 мест (в E и T); в варианте — места только в окружении
    needS0, needS = popE * 0.11, (popE + N) * 0.11
    assert tb.at['Школы: обеспеченность окружения, %', 'Как есть'] == round(100 * 100 / needS0)
    assert tb.at['Школы: не хватает мест', 'Как есть'] == 0
    assert c['Школы: не хватает мест'] == round(max(0, needS - 100))
    assert c['Школы: ученики с территории'] == round(N * 0.11)
    assert c['Сады: дети с территории'] == round(N * 0.06)
    assert c['Сады: не хватает мест'] == round((popE + N) * 0.06)
    assert c['Сады: обеспеченность окружения, %'] == 0


def test_mixed_crs_same_numbers(small_cfg, small_cfg_mixed):
    """Здания, сервисы и зоны в градусах, кварталы в UTM: после пересчёта числа те же."""
    _, _, a = table(small_cfg)
    _, city, b = table(small_cfg_mixed)
    assert city['crs_notes'], 'пересчёт координат должен попасть в отчёт'
    for col in ['pop', 'liv', 'nr_К', 'nr_ОД', 'nr_П', 'nr_X', 'jobs', 'cap_school']:
        assert b[col].to_numpy() == pytest.approx(a[col].to_numpy(), abs=0.05), col


def test_territory_errors(small_cfg):
    cfg, city, _ = table(small_cfg)
    with pytest.raises(TerritoryError, match='не задана'):
        compare(city, [], cfg['params'], cfg['scenarios'])
    with pytest.raises(TerritoryError, match='99'):
        compare(city, [99], cfg['params'], cfg['scenarios'])
