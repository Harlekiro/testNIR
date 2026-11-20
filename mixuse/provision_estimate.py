"""Быстрая оценка обеспеченности школами и садами в варианте — для страницы и без blocksnet (пункт 4, ТЗ 12.6).

Точный расчёт (blocksnet, competitive_provision) выполняется один раз для «как есть» подготовщиком данных;
его результат выгружается в файл страницы: по кварталам — спрос, обеспечено в пределах и за порогом, свободные места;
связи «квартал детей → квартал учреждения» (сколько детей, в пределах ли порога, время); пары кварталов с временем
не больше двух порогов (только к кварталам, где есть учреждения).

Оценка варианта — простые правила, одинаковые здесь и на странице (тест сверяет):
  1. жители территории уезжают — места, которые занимали их дети, освобождаются;
  2. учреждения территории закрываются — дети окружения, ходившие туда, остаются без места;
  3. новые дети с территории: спрос квартала территории = округл(N · площадь квартала ÷ площадь территории ÷ 1000 × норма);
  4. места в пределах порога ищут все, у кого такого места нет: новые дети территории, оставшиеся без места на шаге 2
     и дети, которым и раньше не хватило места в пределах порога (без места или с местом за порогом).
     Пары «квартал → учреждение» берутся по очереди по весу «дети квартала ÷ (время + 1)» — как в целевой функции
     blocksnet (спрос × вместимость ÷ (время + 1)). Ребёнок занимает свободное место; если свободных нет — место
     ребёнка, для которого это учреждение за порогом, а затем — место квартала с меньшим весом. Получивший место ближе
     освобождает своё место за порогом;
  5. места за порогом (до двух порогов): ищут оставшиеся без места; та же очередь по весу; свободное место или место
     квартала с меньшим весом;
  6. вытесненные ищут снова: шаги 4–5 повторяются, пока кто-то находит место.
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
    new_dem = {}
    for k, p in zip(T, newpop_T):             # 3. новые дети с территории
        n = int(round(p / 1000 * sd['norm']))
        if n:
            new_dem[k] = n

    def D(i):                                 # число детей квартала — вес в очереди (как в blocksnet)
        return new_dem.get(i, 0) if i in Tset else int(demand[i])

    nowhere = {}                              # дети без какого-либо места (ищут и в пределах, и за порогом)
    occ_in, occ_far, far_of = {}, {}, {}      # учреждение → занятые места [[вес, ребёнок, число]]; ребёнок → его места за порогом
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
        else:
            item = [D(src) / (t + 1), src, v]
            (occ_in if ins else occ_far).setdefault(dst, []).append(item)
            if not ins:
                far_of.setdefault(src, []).append([t, dst, item])
    for lst in list(occ_in.values()) + list(occ_far.values()):
        lst.sort(key=lambda x: (x[0], x[1]))  # сначала — самый малый вес
    for lst in far_of.values():
        lst.sort(key=lambda x: (-x[0], x[1]))
    for k in T:
        free[k] = within[k] = without[k] = 0
    for k, n in new_dem.items():
        nowhere[k] = nowhere.get(k, 0) + n
    for i in range(len(demand)):              # дети, которым и раньше не хватило места (без места)
        if i not in Tset:
            lack = int(demand[i] - within[i] - without[i])     # уже включает оставшихся без места на шаге 2
            if lack > 0:
                nowhere[i] = lack

    def far_count(i):
        return sum(x[2][2] for x in far_of.get(i, []))

    def take(lst, need, below=None, skip=None):
        """Забрать до need мест из списка занятых (от малого веса к большому); below — только с весом меньше;
        skip — не трогать места этого квартала. Возвращает [(ребёнок, сколько)]."""
        got = []
        for it in lst:
            if need <= 0 or (below is not None and it[0] >= below):
                break
            if it[1] == skip:
                continue
            y = min(need, it[2])
            if y > 0:
                it[2] -= y
                need -= y
                got.append((it[1], y))
        return got

    pairs = [p for p in sd['pairs'] if p[1] not in Tset and p[2] <= 2 * thr and D(p[0]) > 0]
    order = lambda p: (-D(p[0]) / (p[2] + 1), p[2], p[0], p[1])     # вес «дети ÷ (время + 1)», как в blocksnet
    cand_in = sorted((p for p in pairs if p[2] <= thr), key=order)
    cand_out = sorted((p for p in pairs if p[2] > thr), key=order)
    for _round in range(20):                  # проходы повторяются, пока кто-то находит место: вытесненные ищут снова
        moved = False
        for src, dst, t in cand_in:           # 4. места в пределах порога
            want = nowhere.get(src, 0) + far_count(src)
            if want <= 0:
                continue
            w = D(src) / (t + 1)
            x = min(want, free[dst])
            free[dst] -= x
            got = x
            for child, y in take(occ_far.get(dst, []), want - got, skip=src):   # место того, кому учреждение за порогом
                without[child] -= y
                nowhere[child] = nowhere.get(child, 0) + y
                got += y
            for child, y in take(occ_in.get(dst, []), want - got, below=w, skip=src):   # место квартала с меньшим весом
                within[child] -= y
                nowhere[child] = nowhere.get(child, 0) + y
                got += y
            if got <= 0:
                continue
            moved = True
            within[src] += got
            occ_in.setdefault(dst, []).append([w, src, got])
            occ_in[dst].sort(key=lambda x: (x[0], x[1]))
            use = min(got, nowhere.get(src, 0))   # сначала — те, у кого места не было
            nowhere[src] = nowhere.get(src, 0) - use
            rest = got - use                  # остальные — переходят с места за порогом: оно освобождается
            for rec in far_of.get(src, []):
                if rest <= 0:
                    break
                y = min(rest, rec[2][2])
                if y > 0:
                    rec[2][2] -= y
                    without[src] -= y
                    free[rec[1]] += y
                    rest -= y
        for src, dst, t in cand_out:          # 5. места за порогом
            if nowhere.get(src, 0) <= 0:
                continue
            w = D(src) / (t + 1)
            x = min(nowhere[src], free[dst])
            free[dst] -= x
            got = x
            for child, y in take(occ_far.get(dst, []), nowhere[src] - got, below=w, skip=src):
                without[child] -= y
                nowhere[child] = nowhere.get(child, 0) + y
                got += y
            if got <= 0:
                continue
            moved = True
            nowhere[src] -= got
            without[src] += got
            item = [w, src, got]
            occ_far.setdefault(dst, []).append(item)
            occ_far[dst].sort(key=lambda x: (x[0], x[1]))
            far_of.setdefault(src, []).append([t, dst, item])
        if not moved:
            break
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
