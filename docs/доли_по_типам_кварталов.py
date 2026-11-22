"""Фактические доли поэтажной площади по типам кварталов (к docs/доли_вариантов.md).

Запуск из корня проекта:  python docs/доли_по_типам_кварталов.py vysotsk gatchina_layers spb_full
Результат — таблица в results/доли_по_типам_кварталов.csv и печать.

Поэтажная площадь квартала по группам (здания по правилам раздела 4 ТЗ — таблица зданий пакета):
  Ж  = поэтажная площадь жилых домов − встроенные помещения;
  К  = поэтажная площадь нежилых зданий группы К (от S_min) + встроенные помещения К;   ОД — так же;
  П  = нежилые здания группы П.  Здания группы X (функция не определена) не входят.
Тип квартала («К+ОД», «Ж+К+ОД», …) — набор групп, которые в нём есть. Три правила «есть»:
  наличие — площадь группы больше 0;  порог 5 % и порог 10 % — доля группы в Ж+К+ОД+П не меньше порога.
Для каждого типа — число кварталов, медиана долей по кварталам и доли суммарной площади.
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
TYPES = ['К+ОД', 'Ж+К+ОД']
RULES = [('наличие', None), ('порог 5 %', 5), ('порог 10 %', 10)]


def block_areas(code):
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
    return a[a[G].sum(axis=1) > 0]


def summary(areas):
    rows = []
    for code, a in areas.items():
        sh = a[G].div(a[G].sum(axis=1), axis=0) * 100
        for rule, thr in RULES:
            has = a[G].gt(0) if thr is None else sh.ge(thr)
            typ = has.apply(lambda r: '+'.join(g for g in G if r[g]), axis=1)
            for tt in TYPES:
                m = typ == tt
                gs = tt.split('+')
                part = a.loc[m, gs]
                med = (part.div(part.sum(axis=1), axis=0) * 100).median() if m.any() else pd.Series(dtype=float)
                tot = 100 * part.sum() / part.sum().sum() if m.any() else pd.Series(dtype=float)
                rows.append({'набор': code, 'правило': rule, 'тип': tt, 'кварталов': int(m.sum()),
                             **{f'медиана {g}, %': round(med.get(g, float('nan')), 1) for g in gs},
                             **{f'по сумме {g}, %': round(tot.get(g, float('nan')), 1) for g in gs}})
    return pd.DataFrame(rows)


if __name__ == '__main__':
    codes = sys.argv[1:] or ['vysotsk', 'gatchina_layers', 'spb_full']
    areas = {c: block_areas(c) for c in codes}
    if len(codes) > 1:
        areas['все три'] = pd.concat(areas.values(), ignore_index=True)
    vo = os.path.join(ROOT, 'examples', 'spb_vasilievsky', 'blocks.geojson')
    if 'spb_full' in areas and os.path.exists(vo):          # Васильевский остров — номера кварталов совпадают с spb_full
        from mixuse.geometry import read_layer
        ids = set(pd.to_numeric(read_layer(vo)[0]['block_id']).astype(int))
        areas['Васильевский остров'] = areas['spb_full'][areas['spb_full']['block_id'].isin(ids)]
    out = summary(areas)
    os.makedirs(os.path.join(ROOT, 'results'), exist_ok=True)
    out.to_csv(os.path.join(ROOT, 'results', 'доли_по_типам_кварталов.csv'), index=False, encoding='utf-8-sig')
    with pd.option_context('display.width', 250, 'display.max_columns', 20):
        print(out.to_string(index=False))
