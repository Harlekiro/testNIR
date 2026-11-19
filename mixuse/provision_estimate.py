"""Быстрая оценка обеспеченности школами и садами в варианте — для страницы и без blocksnet (пункт 4, ТЗ 12.6).

Точный расчёт (blocksnet, competitive_provision) выполняется один раз для «как есть» подготовщиком данных;
его результат выгружается в файл страницы: по кварталам — спрос, обеспечено в пределах и за порогом, свободные места;
связи «квартал детей → квартал учреждения» (сколько детей и в пределах ли порога); пары кварталов с временем
не больше двух порогов (только к кварталам, где есть учреждения).

Оценка варианта — простое правило, одинаковое здесь и на странице (тест сверяет):
  1. жители территории уезжают — места, которые занимали их дети, освобождаются;
  2. учреждения территории закрываются — дети окружения, ходившие туда, остаются без места и ищут новое;
  3. новые дети с территории: спрос квартала территории = округл(N · площадь квартала ÷ площадь территории ÷ 1000 × норма);
  4. в пределах порога: все, кто ищет место, занимают места по очереди — сначала самые близкие пары
     «квартал → учреждение» (по времени; при равенстве — по порядку кварталов). Сначала свободные места; если их нет —
     место, которое занимал ребёнок, для которого это учреждение за порогом (сначала самый дальний): ребёнок,
     которому учреждение в пределах порога, получает место раньше (так распределяет и blocksnet);
     вытесненный ребёнок снова ищет место;
  5. за порогом (до двух порогов): оставшиеся и вытесненные занимают свободные места, сначала самые близкие;
     если свободных нет — место того, кому до учреждения дальше (ближе — раньше, как в blocksnet);
  6. вытесненные на шаге 5 ещё раз ищут свободное место за порогом.
Обеспеченность окружения в варианте = (обеспечено в пределах порога у кварталов окружения) ÷ (их спрос).
Это оценка, а не blocksnet: blocksnet заново распределяет всех детей города, оценка перемещает только тех, кого
коснулся вариант. Расхождение с blocksnet показывает тест (раздел 12.6).
"""
import os

import numpy as np

SERVICE_KEYS = ('school', 'kindergarten')


def estimate(sd, T, E, newpop_T, area_T):
    """Оценка для одного типа учреждений.

    sd — данные страницы для типа (provision[тип] файла страницы): norm, threshold, demand, within, without, free,
    links [[дети, учреждение, число, в пределах 0/1]], pairs [[дети, учреждение, минуты]];
    T, E — номера строк кварталов территории и окружения; newpop_T — жители варианта по кварталам территории
    (None — «как есть»); area_T — их площади.
    Возвращает словарь показателей 12.5."""
    demand = np.asarray(sd['demand'], int)
    within = np.asarray(sd['within'], int).copy()
    without = np.asarray(sd['without'], int).copy()
    E = list(E)
    dE = int(demand[E].sum())
    if newpop_T is None:
        return {'env_in': 100 * within[E].sum() / dE if dE else None,
                'env_any': 100 * (within[E].sum() + without[E].sum()) / dE if dE else None,
                'children': 0, 'provided': 0, 'provided_any': 0}
    Tset = set(T)
    free = np.asarray(sd['free'], int).copy()
    seek = {}
    for src, dst, v, ins, t in sd['links']:
        if src in Tset:                      # 1. дети уехавших жителей освобождают места
            if dst not in Tset:
                free[dst] += v
        elif dst in Tset:                    # 2. учреждение территории закрыто — ребёнок окружения ищет место
            seek[src] = seek.get(src, 0) + v
            if ins:
                within[src] -= v
            else:
                without[src] -= v
    for k in T:
        free[k] = 0
        within[k] = 0
        without[k] = 0
    new_dem = {}
    for k, p in zip(T, newpop_T):             # 3. новые дети с территории
        n = int(round(p / 1000 * sd['norm']))
        if n:
            new_dem[k] = n
            seek[k] = seek.get(k, 0) + n
    thr = sd['threshold']
    far = {}                                   # учреждение → занятые «за порогом» места [[время, ребёнок, число]]
    for src, dst, v, ins, t in sd['links']:
        if not ins and src not in Tset and dst not in Tset:
            far.setdefault(dst, []).append([t, src, v])
    for lst in far.values():
        lst.sort(key=lambda x: (-x[0], x[1]))  # сначала самый дальний
    reseek = {}
    cand = sorted((p for p in sd['pairs'] if p[1] not in Tset and p[2] <= 2 * thr), key=lambda p: (p[2], p[0], p[1]))
    for src, dst, t in cand:                   # 4. в пределах порога
        if t > thr or seek.get(src, 0) <= 0:
            continue
        x = min(seek[src], free[dst])
        seek[src] -= x
        free[dst] -= x
        within[src] += x
        for item in far.get(dst, []):
            if seek[src] <= 0:
                break
            y = min(seek[src], item[2])
            if y <= 0:
                continue
            item[2] -= y
            without[item[1]] -= y
            reseek[item[1]] = reseek.get(item[1], 0) + y
            seek[src] -= y
            within[src] += y
    for k, v in reseek.items():
        seek[k] = seek.get(k, 0) + v
    reseek2 = {}
    for src, dst, t in cand:                   # 5. за порогом: свободные места, затем места тех, кому дальше
        if t <= thr or seek.get(src, 0) <= 0:
            continue
        x = min(seek[src], free[dst])
        seek[src] -= x
        free[dst] -= x
        without[src] += x
        for item in far.get(dst, []):
            if seek[src] <= 0 or item[0] <= t:
                break                              # список — от дальнего к ближнему
            y = min(seek[src], item[2])
            if y <= 0:
                continue
            item[2] -= y
            without[item[1]] -= y
            reseek2[item[1]] = reseek2.get(item[1], 0) + y
            seek[src] -= y
            without[src] += y
    for src, dst, t in cand:                   # 6. вытесненные за порогом — ещё раз, только свободные места
        if t <= thr or reseek2.get(src, 0) <= 0 or free[dst] <= 0:
            continue
        x = min(reseek2[src], free[dst])
        reseek2[src] -= x
        free[dst] -= x
        without[src] += x
    children = sum(new_dem.values())
    return {'env_in': 100 * within[E].sum() / dE if dE else None,
            'env_any': 100 * (within[E].sum() + without[E].sum()) / dE if dE else None,
            'children': children, 'provided': int(sum(within[k] for k in new_dem)),
            'provided_any': int(sum(within[k] + without[k] for k in new_dem))}


def estimate_variants(prov_data, T, E, values, areas):
    """Оценка для всех вариантов в формате provision_bn.variant_provision (для compare_v5(prov=…)).
    values — det['values'] из compare_v5; areas — площади кварталов (в порядке строк таблицы)."""
    area_T = np.asarray([areas[k] for k in T], float)
    out = {}
    for scen, o in values.items():
        newpop = None if o['d'] is None else o['N'] * area_T / area_T.sum()
        out[scen] = {}
        for key in SERVICE_KEYS:
            sd = prov_data[key]
            r = estimate(sd, T, E, newpop, area_T)
            r.update(norm=sd['norm'], threshold=sd['threshold'])
            out[scen][key] = r
    for scen in out:
        for key in SERVICE_KEYS:
            v, b = out[scen][key]['env_in'], out['Как есть'][key]['env_in']
            out[scen][key]['delta'] = None if v is None or b is None else v - b
    out['_source'] = ('оценка по точному расчёту blocksnet «как есть» (provision_estimate): '
                      'перемещаются только дети, которых коснулся вариант')
    return out


def page_data_path(cfg, graph='walk'):
    root = os.path.dirname(os.path.dirname(cfg['_path'])) if cfg.get('_path', '').endswith('.yaml') else os.getcwd()
    return os.path.join(root, 'data', cfg['name'], 'access', f'provision_{graph}.json')


def load_page_data(cfg, city, graph='walk'):
    """Точный расчёт «как есть», сохранённый подготовщиком (команда provision). Проверяет, что он подходит к таблице
    кварталов: те же номера, тот же файл кварталов, то же число жителей. Возвращает данные или None, если файла нет."""
    import hashlib
    import json
    path = page_data_path(cfg, graph)
    if not os.path.exists(path):
        return None
    d = json.load(open(path, encoding='utf-8'))
    m = d.get('meta', {})
    t = city['table']
    h = hashlib.sha256(open(cfg['blocks'], 'rb').read()).hexdigest()
    errs = []
    if m.get('block_id') != t['block_id'].astype(int).tolist():
        errs.append('другие номера кварталов')
    if m.get('sha256 слоя кварталов') != h:
        errs.append('другой файл кварталов')
    if m.get('жителей') != int(round(t['pop'].sum())):
        errs.append('другое число жителей (данные или правила изменились)')
    if errs:
        raise ValueError(f'Данные обеспеченности {path} не подходят к таблице кварталов: {"; ".join(errs)}. '
                         'Пересчитайте их командой provision в окружении с blocksnet.')
    return d
