"""Этап 6: перебор сочетаний (ТЗ, раздел 7) — команда explore.

Число сочетаний считается вручную: группы Ж, К, ОД, шаг 10 %, К не больше 20 %:
  К = 0 — Ж + ОД = 100: 11 сочетаний; К = 10 — 10; К = 20 — 9  →  30.
Без предела К — все сочетания трёх долей с шагом 10: C(12, 2) = 66.
"""
import os

import pandas as pd
import pytest

from test_rules_v5 import make_v5, build
from mixuse.scenarios import enumerate_shares, combo_name, explore, apply_filters, explore_summary, EXPLORE_COLUMNS
from mixuse.compare import compare
from mixuse.cli import main

SP_ROW = 'params: {kit_sp_row: zh_low_mid}' + chr(10)


def test_enumerate_counts_by_hand():
    assert len(enumerate_shares(['Ж', 'К', 'ОД'], 10, {'К': 20})) == 30
    assert len(enumerate_shares(['Ж', 'К', 'ОД'], 10)) == 66
    assert len(enumerate_shares(['Ж', 'ОД'], 25)) == 5                        # 100/0, 75/25, 50/50, 25/75, 0/100
    c = enumerate_shares(['Ж', 'К', 'ОД'], 10, {'К': 20}, {'ОД': 30})
    assert all(x['К'] <= 20 and x['ОД'] >= 30 and x['П'] == 0 and sum(x.values()) == 100 for x in c)
    assert len(c) == 8 + 7 + 6                                               # К = 0: ОД 30…100; К = 10: ОД 30…90; К = 20: 30…80


def test_enumerate_errors():
    with pytest.raises(ValueError, match='шаг'):
        enumerate_shares(['Ж', 'К'], 30)
    with pytest.raises(ValueError, match='группы'):
        enumerate_shares([], 10)


def test_order_is_by_shares_not_by_indicators():
    names = [combo_name(x) for x in enumerate_shares(['Ж', 'К', 'ОД'], 50)]
    assert names == ['Ж100', 'Ж50 К50', 'Ж50 ОД50', 'К100', 'К50 ОД50', 'ОД100']


@pytest.fixture
def small(tmp_path):
    cfg, L, city = build(make_v5(str(tmp_path), extra=SP_ROW))
    return cfg, city


def test_explore_equals_compare(small):
    """Показатели перебора — те же, что у варианта с такими же долями в compare (одна функция)."""
    cfg, city = small
    combos = enumerate_shares(['Ж', 'К', 'ОД'], 10, {'К': 20})
    table, info = explore(city, [21], cfg['params'], combos)
    assert len(table) == 31 and table['сочетание'].iloc[0] == 'Как есть'
    full, _, _ = compare(city, [21], cfg['params'], {'x': {'Ж': 70, 'К': 10, 'ОД': 20, 'П': 0}})
    row = table[table['сочетание'] == 'Ж70 К10 ОД20'].iloc[0]
    assert row['Жители на территории N'] == full.loc['Жители на территории N', 'x']
    assert row['Рабочие места на территории J'] == full.loc['Рабочие места на территории J', 'x']
    assert row['K окружения'] == full.loc['K окружения', 'x']
    assert info['КИТ варианта'] == 0.8


def test_filters_keep_order_and_now_row(small):
    cfg, city = small
    table, _ = explore(city, [21], cfg['params'], enumerate_shares(['Ж', 'К', 'ОД'], 10, {'К': 20}))
    f = apply_filters(table, ['Жители на территории N>=500', 'К, %=10'])
    assert f['сочетание'].iloc[0] == 'Как есть'
    rest = f.iloc[1:]
    assert (rest['К, %'] == 10).all() and (rest['Жители на территории N'] >= 500).all()
    assert list(rest['сочетание']) == [n for n in table['сочетание'] if n in set(rest['сочетание'])]   # порядок прежний
    with pytest.raises(ValueError, match='нет показателя'):
        apply_filters(table, ['Счастье>=1'])


def test_summary_ranges_and_influence(small):
    cfg, city = small
    table, _ = explore(city, [21], cfg['params'], enumerate_shares(['Ж', 'К', 'ОД'], 10, {'К': 20}))
    s = explore_summary(table, ['Ж', 'К', 'ОД']).set_index('показатель')
    assert list(s.index) == [c for c, _ in EXPLORE_COLUMNS]
    n = pd.to_numeric(table['Жители на территории N'].iloc[1:])
    assert (s.loc['Жители на территории N', 'от'], s.loc['Жители на территории N', 'до']) == (n.min(), n.max())
    # N = F · δЖ · 0,7 ÷ 30 — зависит только от доли Ж, растёт с ней (r = 1)
    assert s.loc['Жители на территории N', 'сильнее всего зависит от доли'] == 'Ж (растёт с ростом доли)'
    assert s.loc['Жители на территории N', 'Ж: r'] == 1.0
    assert s.loc['Жители на территории N', 'Ж: на +10 п. п.'] == pytest.approx(40000 * 0.8 * 0.1 * 0.7 / 30, abs=1)


def test_cli_explore(tmp_path):
    cfg = make_v5(str(tmp_path), extra=SP_ROW)
    out = str(tmp_path / 'out')
    assert main(['explore', cfg, '--out', out, '--groups', 'Ж,ОД', '--step', '25', '--filter', 'ОД, %>=50']) == 0
    t = pd.read_csv(os.path.join(out, 'v5small_перебор.csv'), encoding='utf-8-sig')
    assert list(t['сочетание']) == ['Как есть', 'Ж50 ОД50', 'Ж25 ОД75', 'ОД100']
    assert os.path.exists(os.path.join(out, 'v5small_перебор_сводка.csv'))
    assert main(['explore', cfg, '--out', out, '--max', 'Х=10']) == 2                     # неизвестная группа
