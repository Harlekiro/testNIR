"""Доли вариантов Ж+К+ОД и К+ОД по фактическим кварталам — метод из docs/доли_вариантов.md (решение автора 23.11.2026).

Запуск из корня проекта:  python docs/доли_по_типам_кварталов.py
Результат — печать и results/доли_по_типам_кварталов.csv.

1. Поэтажная площадь квартала по группам (здания по правилам раздела 4 ТЗ — таблица зданий пакета):
     Ж  = поэтажная площадь жилых домов − встроенные помещения;
     К  = поэтажная площадь нежилых зданий группы К (от S_min) + встроенные помещения К;   ОД — так же;
     П  = нежилые здания группы П.  Здания группы X (функция не определена) не входят.
2. Функция присутствует в квартале, если её доля в Ж + К + ОД + П не меньше 5 %.
   Тип квартала — набор присутствующих функций («Ж+К+ОД» — ровно Ж, К и ОД; «К+ОД» — ровно К и ОД).
3. Доли квартала этого типа — доли его функций типа, приведённые к 100 % (функции меньше 5 % отбрасываются).
4. Доли варианта — медиана по кварталам этого типа трёх городов вместе; медианы приводятся к 100 %
   и округляются до 5 % (сумма — 100: недостающие 5 % получает функция с наибольшим остатком округления).
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('MIXUSE_PROVISION', 'fallback')
from mixuse.config import load_config            # noqa: E402
from mixuse.blocks import load_layers, build_table   # noqa: E402

G = ['Ж', 'К', 'ОД', 'П']
THRESHOLD = 5          # %: функция присутствует в квартале
STEP = 5               # %: округление долей варианта
CODES = ['vysotsk', 'gatchina_layers', 'spb_full']
TYPES = ['Ж+К+ОД', 'К+ОД']


def block_areas(code):
    """Поэтажная площадь Ж, К, ОД, П по кварталам набора (кварталы без площади этих групп — отброшены)."""
    cfg = load_config(os.path.join(ROOT, 'configs', f'{code}.yaml'))
    L = load_layers(cfg, cfg['_groups'])
    city = build_table(L, cfg, cfg['params'], cfg['_groups'])
    b = city['detail']['buildings']
    a = pd.DataFrame(0.0, index=range(len(city['table'])), columns=G)
    liv = b[b.living]
    a['Ж'] = (liv['floor_area'] - liv['bi_К'] - liv['bi_ОД']).groupby(liv['block']).sum().reindex(a.index).fillna(0)
    for g in ['К', 'ОД', 'П']:
        nr = b[(~b.living) & (b.group == g)]
        a[g] = nr['floor_area'].groupby(nr['block']).sum().reindex(a.index).fillna(0)
    for g in ['К', 'ОД']:
        a[g] += b['bi_' + g].groupby(b['block']).sum().reindex(a.index).fillna(0)
    a['block_id'] = city['table']['block_id'].to_numpy()
    a['набор'] = code
    return a[a[G].sum(axis=1) > 0].reset_index(drop=True)


def typed_shares(a, tt):
    """Кварталы типа tt и доли их функций типа, % (сумма по кварталу — 100)."""
    sh = a[G].div(a[G].sum(axis=1), axis=0) * 100
    typ = sh.ge(THRESHOLD).apply(lambda r: '+'.join(g for g in G if r[g]), axis=1)
    gs = tt.split('+')
    part = a.loc[typ == tt, gs]
    return part.div(part.sum(axis=1), axis=0) * 100


def round_to_step(med):
    """Медианы → доли варианта: к 100 %, округление до STEP, сумма 100."""
    x = med / med.sum() * 100
    r = (x / STEP).round() * STEP
    while r.sum() != 100:
        d = 100 - r.sum()
        k = (x - r).idxmax() if d > 0 else (x - r).idxmin()
        r[k] += STEP if d > 0 else -STEP
    return r.astype(int)


if __name__ == '__main__':
    areas = pd.concat([block_areas(c) for c in CODES], ignore_index=True)
    rows = []
    for tt in TYPES:
        gs = tt.split('+')
        for code in CODES + ['все три']:
            a = areas if code == 'все три' else areas[areas['набор'] == code]
            s = typed_shares(a, tt)
            med = s.median() if len(s) else pd.Series(float('nan'), index=gs)
            row = {'вариант': tt, 'набор': code, 'кварталов': len(s), **{f'медиана {g}, %': round(med[g], 1) for g in gs}}
            if code == 'все три':
                row.update({f'доля варианта {g}, %': v for g, v in round_to_step(med).items()})
            rows.append(row)
    out = pd.DataFrame(rows)
    os.makedirs(os.path.join(ROOT, 'results'), exist_ok=True)
    out.to_csv(os.path.join(ROOT, 'results', 'доли_по_типам_кварталов.csv'), index=False, encoding='utf-8-sig')
    with pd.option_context('display.width', 250, 'display.max_columns', 20):
        print(out.to_string(index=False))
