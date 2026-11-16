"""Шаги 5–6: окружение территории и сравнение вариантов (перенесено из ноутбука без изменений).

Чистые функции: на входе — таблица кварталов (результат blocks.build_table), номера кварталов
территории, параметры и варианты; на выходе — таблица сравнения. Файлы не читаются и не пишутся.
"""
import numpy as np
import pandas as pd

from .geometry import dist_points_to_polys
from .groups import FUNCS
from .scenarios import normalize


class TerritoryError(ValueError):
    """Территория задана неверно — сообщение для пользователя."""


def territory_indices(table, T_ids):
    """Номера кварталов территории → номера строк таблицы. Понятная ошибка, если номера нет."""
    if not T_ids:
        raise TerritoryError('Территория не задана. Укажите номера кварталов в настройках (territory: [..]) '
                             'или в команде: --territory 12,13. Номера видны в слое results/<код>_кварталы.geojson, поле block_id.')
    ids = table.block_id.to_numpy()
    missing = [i for i in T_ids if i not in set(ids.tolist())]
    if missing:
        raise TerritoryError(f'Нет кварталов с номерами {missing}. Номера видны в слое results/<код>_кварталы.geojson, поле block_id.')
    return [int(np.where(ids == i)[0][0]) for i in T_ids]


def environment(city, T, R):
    """Шаг 5. Окружение E — кварталы вне T, центр которых не дальше R от контура территории.

        distT(b) = min по кварталам территории расстояния от центра b до контура (0 внутри).
    """
    t = city['table']; n = len(t)
    inT = np.zeros(n, bool); inT[T] = True
    C = t[['cx', 'cy']].to_numpy()
    distT = np.min([dist_points_to_polys(C, city['polys'][k]) for k in T], axis=0)
    E = np.where(~inT & (distT <= R))[0]
    return E, inT, distT


def compare(city, T_ids, P, SCN):
    """Шаги 5–6. Окружение и сравнение вариантов.

    Для варианта с долями d (нормированы к 1):
        F = S · КИТ;  N = F · d_Ж · k_liv / q;  J = F · (d_К/a_К + d_ОД/a_ОД + d_П/a_П);
        K = (J_E + J) / (P_E + N);
        доступ к g для жилого квартала b окружения (кварталы, контур которых не дальше r от центра b):
          до    — есть квартал с функцией g (территория — в нынешнем виде);
          после — есть квартал с g вне территории, либо d_g > 0 и территория не дальше r;
        школы и сады: места − (P_E + N) · норма / 1000; места «как есть» — в E и T, в варианте — только в E.
    Существующая застройка территории в варианте заменяется полностью.
    Возвращает (таблица сравнения, сводка об окружении, данные для карты).
    """
    t = city['table']; G = city['geom']
    T = territory_indices(t, T_ids)
    E, inT, distT = environment(city, T, P['R'])
    C = t[['cx', 'cy']].to_numpy()
    S = t.area.iloc[T].sum(); F = S * P['kit']
    popE, jobsE = t['pop'].iloc[E].sum(), t['jobs'].iloc[E].sum()
    Kref = t['jobs'].sum() / t['pop'].sum()
    pres = {g: t['есть_' + g].to_numpy() for g in FUNCS}
    near = {b: G.dist_from_point(*C[b]) <= P['r'] for b in E if t['pop'].iloc[b] > 0}
    Tpolys = [p for k in T for p in city['polys'][k]]
    rows, effect = {}, {}
    for name, sh in [('Как есть', None)] + list(SCN.items()):
        if sh is None:
            N, J = t['pop'].iloc[T].sum(), t['jobs'].iloc[T].sum(); d = None
            capS = t.cap_school.iloc[list(E) + T].sum(); capK = t.cap_kinder.iloc[list(E) + T].sum()
        else:
            d = normalize(sh)
            N = F * d['Ж'] * P['k_liv'] / P['q']
            J = F * (d['К'] / P['a_К'] + d['ОД'] / P['a_ОД'] + d['П'] / P['a_П'])
            capS, capK = t.cap_school.iloc[E].sum(), t.cap_kinder.iloc[E].sum()
        K = (jobsE + J) / (popE + N)
        acc = {}
        eff = {}
        if d is not None:
            for g in FUNCS:
                gain = lost = 0.0
                for b, nb in near.items():
                    before = bool((nb & pres[g]).any())
                    after = bool((nb & pres[g] & ~inT).any()) or (d[g] > 0 and distT[b] <= P['r'])
                    if not before and after: gain += t['pop'].iloc[b]; eff[b] = eff.get(b, 0) + 1
                    if before and not after: lost += t['pop'].iloc[b]; eff[b] = eff.get(b, 0) - 1
                acc[g] = (gain, lost)
        effect[name] = eff
        # проверки ограничений
        flags = []
        if d is not None:
            if P['kit'] > P['kit_max']: flags.append('КИТ выше предельного')
            if d['Ж'] > 0:
                near_p = sum(1 for c in np.where(pres['П'] & ~inT)[0]
                             if dist_points_to_polys(np.vstack([r for p in city['polys'][c] for r in p]), Tpolys).min() <= P['r_szz'])
                near_p += int((dist_points_to_polys(city['pts']['производство'], Tpolys) <= P['r_szz']).sum()) if len(city['pts']['производство']) else 0
                if near_p: flags.append(f'производство в {P["r_szz"]} м ({near_p}) — проверить СЗЗ')
                if d['П'] > 0: flags.append('только производства без СЗЗ за границей участка')
        rows[name] = {
            'Новые жители N': int(round(N)), 'Рабочие места на территории J': int(round(J)),
            'Доля нежилых площадей, %': '' if d is None else round(100 * (1 - d['Ж'])),
            'Работа на жителя K': round(float(K), 2), 'Отклонение от среднего |K−K_ref|': round(float(abs(K - Kref)), 2),
            **{f'Доступ к {g}: получают / теряют, жителей': ('—' if d is None else f'+{acc[g][0]:,.0f} / −{acc[g][1]:,.0f}'.replace(',', ' ')) for g in FUNCS},
            'Школы: свободно (+) / не хватает (−), мест': int(round(capS - (popE + N) * P['n_school'] / 1000)),
            'Сады: свободно (+) / не хватает (−), мест': int(round(capK - (popE + N) * P['n_kinder'] / 1000)),
            'Сигналы': '; '.join(flags) if flags else ('—' if d is None else 'нет'),
        }
    out = pd.DataFrame(rows)
    info = {'кварталов на территории': len(T), 'площадь территории, га': round(float(S) / 1e4, 1), 'поэтажная площадь F, м²': int(round(F)),
            'кварталов в окружении': len(E), 'жителей в окружении': int(round(popE)), 'рабочих мест в окружении': int(round(jobsE)),
            'K_ref': round(float(Kref), 3)}
    if len(city['pts']['метро']): info['до метро, м'] = int(round(dist_points_to_polys(city['pts']['метро'], Tpolys).min()))
    if len(city['pts']['остановка']): info['до остановки, м'] = int(round(dist_points_to_polys(city['pts']['остановка'], Tpolys).min()))
    return out, info, {'T': T, 'E': E, 'effect': effect}
