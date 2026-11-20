"""Отчёт о данных (этап 3): что есть в слоях и что придётся принять по умолчанию.

Только счётчики по уже подготовленным зданиям и сервисам (city['detail'] из table_from_layers);
формул расчёта здесь нет. Пункты отчёта — по правилам ТЗ:
  4.1.6  точки производственных сервисов в контуре здания;
  4.2.2  здания без этажности — жилые и нежилые отдельно;
  4.2.3  жилые дома без числа жителей и оценка прибавки жителей;
  4.9    что дополнить в данных (точки предприятий, этажность, объединённые контуры).
"""
import numpy as np
import pandas as pd

from .geometry import assign_points
from .groups import zone_group, NOT_IN_TABLE

SERVICE_GROUPS = ('К', 'ОД', 'П', 'школа', 'детский_сад')   # «сервис в контуре» для подсказки 4.9.1
MAX_LISTED = 15                                             # сколько точек П вне нежилых зданий показывать поимённо


def _pct(n, total):
    return f'{n} из {total} ({100 * n / total:.1f} %)' if total else f'{n} из 0'


def data_report(city, cfg, P):
    """Возвращает (строки отчёта, предупреждения). Для режима «таблица» — только сведения о кварталах."""
    lines, warns = [], []
    t = city['table']
    rules = cfg.get('zone_rules', [])
    zg = np.array([zone_group(z, rules) for z in t['zone']])
    lines.append(f'Кварталов: {len(t)}; в производственной зоне — {int((zg == "П").sum())}, '
                 f'в общественно-деловой — {int((zg == "ОД").sum())}, без зоны — {int(t["zone"].isna().sum())}')
    T = cfg.get('territory') or []
    if T:
        miss = sorted(set(T) - set(t['block_id'].astype(int)))
        lines.append(f'Территория: кварталы {T}' + (f'; нет в слое кварталов: {miss}' if miss else ''))
        if miss:
            warns.append(f'Кварталов территории {miss} нет в слое кварталов.')
    if P.get('data_note'):                    # ограничение территории, которое программа не проверяет (ТЗ 17)
        lines.append(f'Ограничение территории (программой не проверяется): {P["data_note"]}')
    if cfg.get('rules', 'v5') == 'v5':        # ТЗ 18.3: КИТ и его источник
        from .compare import kit_value, KitError
        try:
            kit, src = kit_value(P)
            lines.append(f'КИТ варианта: {kit:g} — {src}'.replace('.', ',', 1))
        except KitError as e:
            warns.append(str(e))
    det = city.get('detail')
    if det is None:
        lines.append('Режим «таблица»: слоёв зданий и сервисов нет, отчёт о зданиях не составляется.')
        return lines, warns
    b, bpolys, s = det['buildings'], det['bpolys'], det['services']
    sa = det.get('services_all')
    if sa is not None and 'group' in sa:      # ТЗ 18.3: типы не из таблицы групп — с числом объектов
        miss = sa.loc[sa.group == NOT_IN_TABLE, 'service_type'].value_counts()
        if len(miss):
            lines.append('Типы сервисов, которых нет в таблице групп (не учитываются): '
                         + ', '.join(f'{k} — {v}' for k, v in miss.items()))
    nonres = ~b['living']
    big = nonres & (b['footprint'] >= P['S_min'])

    # --- 4.2.2 этажность
    lines.append('')
    lines.append(f'Здания в кварталах: {len(b)} (жилых {int(b.living.sum())}, нежилых {int(nonres.sum())}, '
                 f'из них нежилых от S_min = {P["S_min"]:g} м² — {int(big.sum())})')
    m = b['storeys_missing']
    lines.append(f'Этажность не указана (принят {P["storeys_default"]:g} этаж, правило 4.2.2):')
    lines.append(f'  жилые — {_pct(int((m & b.living).sum()), int(b.living.sum()))}')
    lines.append(f'  нежилые — {_pct(int((m & nonres).sum()), int(nonres.sum()))}')
    lines.append(f'  нежилые от S_min — {_pct(int((m & big).sum()), int(big.sum()))}')
    one = b['storeys_one']
    lines.append(f'Указан 1 этаж: жилые — {_pct(int((one & b.living).sum()), int(b.living.sum()))}; '
                 f'нежилые от S_min — {_pct(int((one & big).sum()), int(big.sum()))}')
    if big.sum() and (m & big).sum() / big.sum() > 0.1:
        warns.append(f'У {100 * (m & big).sum() / big.sum():.0f} % нежилых зданий от {P["S_min"]:g} м² нет этажности: '
                     'они считаются одноэтажными (4.2.2, подсказка 4.9.2).')

    # --- 4.2.3 жители
    lines.append('')
    if 'pop_missing' in b:
        pm = b['pop_missing']
        add = (b.loc[pm, 'living_area'] / P['q']).sum()       # жилая площадь — из поля или A·k_liv (как в расчёте)
        total = b.loc[b.living, 'pop'].sum()
        share = add / total if total else 0.0
        lines.append(f'Жилые дома без числа жителей: {_pct(int(pm.sum()), int(b.living.sum()))}; '
                     f'по правилу 4.2.3 они получат жителей «жилая площадь ÷ q»: +{add:,.0f} к {total:,.0f} ({100 * share:.2f} %)'
                     .replace(',', ' '))
        if share > 0.01:
            warns.append(f'Прибавка жителей по правилу 4.2.3 — {100 * share:.1f} % (больше 1 %): по ТЗ расчёт '
                         'останавливается и показывается автору.')
    else:
        lines.append('Поле жителей не задано: все жители — оценка «жилая площадь ÷ q».')

    # --- сервисы: школы и сады без мест
    ins = s['block'] >= 0
    for g, what in [('школа', 'Школ'), ('детский_сад', 'Детских садов')]:
        sel = ins & (s.group == g)
        lines.append(f'{what} без числа мест: {_pct(int((sel & s.capacity.isna()).sum()), int(sel.sum()))}; '
                     f'мест всего {int(s.loc[sel, "capacity"].fillna(0).sum())}')

    # --- 4.1.6 точки производственных сервисов в контуре здания
    lines.append('')
    sp = s[ins & (s.group == 'П')].reset_index(drop=True)
    n_out = int((det['services_all'].group == 'П').sum()) - len(sp)
    if len(sp):
        own_any = assign_points(sp[['x', 'y']].to_numpy(), bpolys)
        nr_idx = np.where(big.to_numpy())[0]
        own_nr = assign_points(sp[['x', 'y']].to_numpy(), [bpolys[i] for i in nr_idx]) if len(nr_idx) else np.full(len(sp), -1)
        lines.append(f'Точки производственных сервисов (группа П) в кварталах: {len(sp)}; '
                     f'в контуре здания — {int((own_any >= 0).sum())}, в контуре нежилого здания от S_min — {int((own_nr >= 0).sum())}; '
                     f'вне кварталов (не учитываются) — {n_out}')
        out = sp[own_nr < 0]
        if len(out):
            n_small = int((own_any[out.index] >= 0).sum())
            lines.append(f'  не в нежилом здании от S_min — {len(out)}: в контуре здания меньше S_min или жилого — {n_small}, '
                         f'вне контуров зданий — {len(out) - n_small}')
        for k, r in enumerate(out.itertuples()):
            if k == MAX_LISTED:
                lines.append(f'  … и ещё {len(out) - MAX_LISTED}')
                break
            why = 'в контуре здания меньше S_min или жилого' if own_any[r.Index] >= 0 else 'вне контуров зданий'
            lines.append(f'  не в нежилом здании: {r.name or "(без названия)"} [{r.service_type}] — {why}')
    else:
        lines.append(f'Точек производственных сервисов (группа П) в кварталах нет; вне кварталов — {n_out}.')

    # --- 4.9.1 производственные зоны: одноэтажные здания без сервисов, кварталы без точек П
    lines.append('')
    zone_P = zg[b['block'].to_numpy()] == 'П'
    sv = s[ins & s.group.isin(SERVICE_GROUPS)].reset_index(drop=True)
    has_srv = np.zeros(len(b), bool)
    idx = np.where((big & zone_P).to_numpy())[0]
    if len(idx) and len(sv):
        o = assign_points(sv[['x', 'y']].to_numpy(), [bpolys[i] for i in idx])
        has_srv[idx[o[o >= 0]]] = True
    one = b['floor_area'] <= b['footprint'] + 1e-9           # один этаж, в том числе по умолчанию (4.2.2)
    fa_P = b.loc[big & zone_P, 'floor_area'].sum()
    fa_one = b.loc[big & zone_P & one & ~has_srv, 'floor_area'].sum()
    nP = int((zg == 'П').sum())
    blocks_P_pts = set(s.loc[ins & (s.group == 'П'), 'block'])
    nP_no = int(sum(1 for k in np.where(zg == 'П')[0] if k not in blocks_P_pts))
    lines.append(f'Производственные зоны: поэтажная площадь нежилых зданий от S_min — {fa_P:,.0f} м²; '
                 f'из неё в одноэтажных без сервиса в контуре — {fa_one:,.0f} м² ({100 * fa_one / fa_P if fa_P else 0:.0f} %)'.replace(',', ' '))
    lines.append(f'Производственных кварталов без точек П: {nP_no} из {nP}')
    kP = city.get('report', {}).get('кварталов с П: по сервисам / по зданиям шагов 4–5 / всего')
    if kP:
        lines.append(f'Кварталов с функцией П: по сервисам / по зданиям производственных зон (шаги 4–5) / всего — {kP}')
    if nP and nP_no:
        warns.append(f'В {nP_no} из {nP} производственных кварталов нет точек предприятий (группа П). Одноэтажный цех '
                     'меньше 1 000 м² без точки будет считаться хозпостройкой (подсказка 4.9.1): добавьте точки предприятий.')
    lines.append('Подсказка 4.9.3: если корпуса разной этажности объединены в один контур, этажность контура '
                 'применяется ко всей площади застройки — такие контуры стоит разделить (автоматически не проверяется).')
    return lines, warns
