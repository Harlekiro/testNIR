"""Шаги 5–6: окружение территории и сравнение вариантов (как в листинге ноутбука v4).

Чистые функции: на входе — таблица кварталов (результат blocks.build_table), номера кварталов
территории, параметры и варианты; на выходе — таблица сравнения. Файлы не читаются и не пишутся.
Сводного балла и порядка вариантов нет.
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

    Для варианта с долями d (нормированы к 1), существующая застройка территории заменяется полностью:
        F = S · КИТ;  N = F · d_Ж · k_liv / q;  J = F · (d_К/a_К + d_ОД/a_ОД + d_П/a_П);
    А. Работа и жильё:
        ΔJ = J − J_T0;
        K окружения = (J_E + J) / (P_E + N);
        K по всем данным = (Σjobs − J_T0 + J) / (Σpop − P_T0 + N);
    Б. Доступ к g для жилого квартала b окружения (кварталы, контур которых не дальше r от центра b):
        до    — есть квартал с функцией g (территория — в нынешнем виде);
        после — есть квартал с g вне территории, либо d_g > 0 и территория не дальше r;
    В. Школы и сады: потребность = (P_E + N) · норма / 1000; места «как есть» — в E и T, в варианте — только в E;
        обеспеченность = места / потребность; не хватает = max(0, потребность − места); с территории = N · норма / 1000.
    «Как есть»: N = P_T0, J = J_T0.
    Правила v5 (в таблице кварталов есть jobs_A):
        строка П — нейтральная (4.7.2): «Жители в радиусе r от производства: до / после» — сумма жителей кварталов b,
        у которых «до» = 1, и сумма для «после» = 1;
        нижняя граница (4.4.5, 4.8.3): K_A окружения = (J_E,A + J_A) / (P_E + N), где J_A «как есть» — категория А
        территории, в варианте — J.
    Возвращает (таблица сравнения, сводка об окружении, данные для карты).
    """
    t = city['table']; G = city['geom']
    T = territory_indices(t, T_ids)
    E, inT, distT = environment(city, T, P['R'])
    C = t[['cx', 'cy']].to_numpy()
    S = t.area.iloc[T].sum(); F = S * P['kit']
    popE, jobsE = t['pop'].iloc[E].sum(), t['jobs'].iloc[E].sum()
    v5 = 'jobs_A' in t
    jobsE_A = t['jobs_A'].iloc[E].sum() if v5 else None
    Kref = t['jobs'].sum() / t['pop'].sum()
    popA, jobsA = t['pop'].sum(), t['jobs'].sum()                    # все загруженные кварталы
    popT0, jobsT0 = t['pop'].iloc[T].sum(), t['jobs'].iloc[T].sum()  # территория в нынешнем виде
    pres = {g: t['есть_' + g].to_numpy() for g in FUNCS}
    near = {b: G.dist_from_point(*C[b]) <= P['r'] for b in E if t['pop'].iloc[b] > 0}
    Tpolys = [p for k in T for p in city['polys'][k]]
    rows, effect = {}, {}
    for name, sh in [('Как есть', None)] + list(SCN.items()):
        if sh is None:
            N, J, d = popT0, jobsT0, None
            J_A = t['jobs_A'].iloc[T].sum() if v5 else None
            capS = t.cap_school.iloc[list(E) + T].sum(); capK = t.cap_kinder.iloc[list(E) + T].sum()
        else:
            d = normalize(sh)
            N = F * d['Ж'] * P['k_liv'] / P['q']
            J = F * (d['К'] / P['a_К'] + d['ОД'] / P['a_ОД'] + d['П'] / P['a_П'])
            J_A = J
            capS, capK = t.cap_school.iloc[E].sum(), t.cap_kinder.iloc[E].sum()   # существующее на территории сносится
        K = (jobsE + J) / (popE + N)
        Kall = (jobsA - jobsT0 + J) / (popA - popT0 + N)
        acc, eff = {}, {}
        if d is not None:
            for g in FUNCS:
                gain = lost = 0.0
                for b, nb in near.items():
                    before = bool((nb & pres[g]).any())
                    after = bool((nb & pres[g] & ~inT).any()) or (d[g] > 0 and distT[b] <= P['r'])
                    if v5 and g == 'П':                    # 4.7.2: жители рядом с производством до / после
                        gain += t['pop'].iloc[b] if before else 0.0
                        lost += t['pop'].iloc[b] if after else 0.0
                        continue
                    if not before and after: gain += t['pop'].iloc[b]; eff[b] = eff.get(b, 0) + 1
                    if before and not after: lost += t['pop'].iloc[b]; eff[b] = eff.get(b, 0) - 1
                acc[g] = (gain, lost)
        effect[name] = eff
        needS, needK = (popE + N) * P['n_school'] / 1000, (popE + N) * P['n_kinder'] / 1000
        rows[name] = {
            'Жители на территории N': int(round(N)), 'Рабочие места на территории J': int(round(J)),
            'Изменение рабочих мест к нынешним': '—' if d is None else int(round(J - jobsT0)),
            'Доля нежилых площадей, %': '' if d is None else round(100 * (1 - d['Ж'])),
            'Работа на жителя K: окружение': round(float(K), 2), 'Работа на жителя K: все данные': round(float(Kall), 2),
            **({'Рабочие места на территории J, нижняя граница': int(round(J_A)),
                'Работа на жителя K: окружение, нижняя граница': round(float((jobsE_A + J_A) / (popE + N)), 2)} if v5 else {}),
            **{f'Доступ к {g}: получают / теряют, жителей': ('—' if d is None else f'+{acc[g][0]:,.0f} / −{acc[g][1]:,.0f}'.replace(',', ' '))
               for g in (['К', 'ОД'] if v5 else FUNCS)},
            **({'Жители в радиусе r от производства: до / после': ('—' if d is None else f'{acc["П"][0]:,.0f} / {acc["П"][1]:,.0f}'.replace(',', ' '))}
               if v5 else {}),
            'Школы: ученики с территории': int(round(N * P['n_school'] / 1000)),
            'Школы: обеспеченность окружения, %': int(round(100 * capS / needS)) if needS > 0 else '',
            'Школы: не хватает мест': int(round(max(0.0, needS - capS))),
            'Сады: дети с территории': int(round(N * P['n_kinder'] / 1000)),
            'Сады: обеспеченность окружения, %': int(round(100 * capK / needK)) if needK > 0 else '',
            'Сады: не хватает мест': int(round(max(0.0, needK - capK))),
        }
    out = pd.DataFrame(rows)
    info = {'кварталов на территории': len(T), 'площадь территории, га': round(float(S) / 1e4, 1), 'поэтажная площадь F, м²': int(round(F)),
            'кварталов в окружении': len(E), 'жителей в окружении': int(round(popE)), 'рабочих мест в окружении': int(round(jobsE)),
            'K_ref': round(float(Kref), 3)}
    if v5:
        info['рабочих мест в окружении, нижняя граница'] = int(round(jobsE_A))
    if len(city['pts']['метро']): info['до метро, м'] = int(round(dist_points_to_polys(city['pts']['метро'], Tpolys).min()))
    if len(city['pts']['остановка']): info['до остановки, м'] = int(round(dist_points_to_polys(city['pts']['остановка'], Tpolys).min()))
    return out, info, {'T': T, 'E': E, 'effect': effect}
