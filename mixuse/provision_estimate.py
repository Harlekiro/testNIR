"""Быстрая оценка обеспеченности школами и садами в варианте — для страницы и без blocksnet (пункт 4, ТЗ 12.6).

Точный расчёт (blocksnet, competitive_provision) выполняется один раз для «как есть» подготовщиком данных;
его результат выгружается в файл страницы: по кварталам — спрос, обеспечено в пределах и за порогом, свободные места;
связи «квартал детей → квартал учреждения» (сколько детей, в пределах ли порога, время); пары кварталов с временем
не больше двух порогов (только к кварталам, где есть учреждения).

Оценка варианта — простые правила, одинаковые здесь и на странице (тест сверяет):
  1. жители территории уезжают — места, которые занимали их дети, освобождаются;
  2. учреждения территории закрываются — дети окружения, ходившие туда, остаются без места;
  3. новые дети с территории: спрос квартала территории = округл(N · площадь квартала ÷ площадь территории ÷ 1000 × норма);
  4. места в пределах порога: их ищут все, у кого такого места нет, — новые дети территории, оставшиеся без места
     на шаге 2 и дети, которым и раньше не хватило места в пределах порога (без места или с местом за порогом).
     Пары «квартал → учреждение» берутся по очереди, сначала самые близкие (при равенстве — по порядку кварталов).
     Ребёнок занимает свободное место; если свободных нет — место, которое занимал ребёнок, для которого это
     учреждение за порогом (сначала самый дальний): кому учреждение в пределах порога, тот получает место раньше
     (так распределяет и blocksnet). Ребёнок, получивший место ближе, освобождает своё место за порогом;
  5. места за порогом (до двух порогов): их ищут оставшиеся без места (в том числе вытесненные на шаге 4); сначала
     ближайшие пары; свободное место, а если его нет — место того, кому до учреждения дальше;
  6. вытесненные на шаге 5 ещё раз ищут свободное место за порогом.
Обеспеченность окружения в варианте = (обеспечено в пределах порога у кварталов окружения) ÷ (их спрос).
Это оценка, а не blocksnet: blocksnet заново решает задачу распределения для всего города. Расхождение с ним
на трёх территориях каждого набора показывает тест (раздел 12.6).
"""
import os

import numpy as np

SERVICE_KEYS = ('school', 'kindergarten')


def _take_far(far_list, need):
    """Забрать до need мест «за порогом» из списка [[время, ребёнок, число]] (от дальнего к ближнему).
    Возвращает [(ребёнок, сколько)]."""
    got = []
    for item in far_list:
        if need <= 0:
            break
        y = min(need, item[2])
        if y > 0:
            item[2] -= y
            need -= y
            got.append((item[1], y))
    return got


def estimate(sd, T, E, newpop_T, area_T):
    """Оценка для одного типа учреждений (правила 1–6 в описании модуля).

    sd — данные страницы для типа: norm, threshold, demand, within, without, free,
    links [[дети, учреждение, число, в пределах 0/1, минуты]], pairs [[дети, учреждение, минуты]];
    T, E — номера строк кварталов территории и окружения; newpop_T — жители варианта по кварталам территории
    (None — «как есть»). Возвращает показатели 12.5."""
    demand = np.asarray(sd['demand'], int)
    within = np.asarray(sd['within'], int).copy()
    without = np.asarray(sd['without'], int).copy()
    E = list(E)
    dE = int(demand[E].sum())

    def result(children=0, provided=0, provided_any=0):
        return {'env_in': 100 * within[E].sum() / dE if dE else None,
                'env_any': 100 * (within[E].sum() + without[E].sum()) / dE if dE else None,
                'children': children, 'provided': provided, 'provided_any': provided_any}

    if newpop_T is None:
        return result()
    Tset = set(T)
    thr = sd['threshold']
    free = np.asarray(sd['free'], int).copy()
    nowhere = {}                              # дети без какого-либо места (ищут и в пределах, и за порогом)
    far = {}                                  # учреждение → места «за порогом» [[время, ребёнок, число]]
    far_of = {}                               # ребёнок → его места «за порогом» [[время, учреждение, ссылка]]
    for src, dst, v, ins, t in sd['links']:
        if src in Tset:                       # 1. дети уехавших жителей освобождают места
            if dst not in Tset:
                free[dst] += v
        elif dst in Tset:                     # 2. учреждение территории закрыто
            nowhere[src] = nowhere.get(src, 0) + v
            if ins:
                within[src] -= v
            else:
                without[src] -= v
        elif not ins:
            item = [t, src, v]
            far.setdefault(dst, []).append(item)
            far_of.setdefault(src, []).append([t, dst, item])
    for lst in far.values():
        lst.sort(key=lambda x: (-x[0], x[1]))
    for lst in far_of.values():
        lst.sort(key=lambda x: (-x[0], x[1]))
    for k in T:
        free[k] = within[k] = without[k] = 0
    new_dem = {}
    for k, p in zip(T, newpop_T):             # 3. новые дети с территории
        n = int(round(p / 1000 * sd['norm']))
        if n:
            new_dem[k] = n
            nowhere[k] = nowhere.get(k, 0) + n
    for i in range(len(demand)):              # дети, которым и раньше не хватило места (без места)
        if i not in Tset:
            lack = int(demand[i] - within[i] - without[i])     # уже включает оставшихся без места на шаге 2
            if lack > 0:
                nowhere[i] = lack

    def far_count(i):
        return sum(x[2][2] for x in far_of.get(i, []))

    cand = sorted((p for p in sd['pairs'] if p[1] not in Tset and p[2] <= 2 * thr), key=lambda p: (p[2], p[0], p[1]))
    for src, dst, t in cand:                  # 4. места в пределах порога
        if t > thr:
            continue
        want = nowhere.get(src, 0) + far_count(src)
        if want <= 0:
            continue
        x = min(want, free[dst])
        free[dst] -= x
        got = x
        if want - got > 0:                    # место того, кому учреждение за порогом
            for child, y in _take_far(far.get(dst, []), want - got):
                without[child] -= y
                nowhere[child] = nowhere.get(child, 0) + y
                got += y
        within[src] += got
        use = min(got, nowhere.get(src, 0))   # сначала — те, у кого места не было
        nowhere[src] = nowhere.get(src, 0) - use
        rest = got - use                      # остальные — переходят с места за порогом: оно освобождается
        for rec in far_of.get(src, []):
            if rest <= 0:
                break
            y = min(rest, rec[2][2])
            if y > 0:
                rec[2][2] -= y
                without[src] -= y
                free[rec[1]] += y
                rest -= y
    reseek = {}
    for src, dst, t in cand:                  # 5. места за порогом
        if t <= thr or nowhere.get(src, 0) <= 0:
            continue
        x = min(nowhere[src], free[dst])
        free[dst] -= x
        got = x
        if nowhere[src] - got > 0:
            for child, y in _take_far([it for it in far.get(dst, []) if it[0] > t], nowhere[src] - got):
                without[child] -= y
                reseek[child] = reseek.get(child, 0) + y
                got += y
        nowhere[src] -= got
        without[src] += got
    for src, dst, t in cand:                  # 6. вытесненные на шаге 5 — только свободные места за порогом
        if t <= thr or reseek.get(src, 0) <= 0 or free[dst] <= 0:
            continue
        x = min(reseek[src], free[dst])
        reseek[src] -= x
        free[dst] -= x
        without[src] += x
    return result(sum(new_dem.values()), int(sum(within[k] for k in new_dem)),
                  int(sum(within[k] + without[k] for k in new_dem)))


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
