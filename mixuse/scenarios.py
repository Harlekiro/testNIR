"""Варианты сочетания функций: доли поэтажной площади по группам Ж, К, ОД, П.

Перебор сочетаний (раздел 6 ТЗ) добавляется на этапе 5.
"""

GROUPS = ['Ж', 'К', 'ОД', 'П']


def normalize(shares):
    """Доли варианта, нормированные к 1:  d_g = доля_g / Σ долей (Ж, К, ОД, П)."""
    tot = sum(shares.values())
    return {k: v / tot for k, v in shares.items()}


def validate_scenarios(scn):
    """Проверка вариантов из настроек. Возвращает список ошибок (пустой — всё верно)."""
    errors = []
    if not scn:
        return ['Не задано ни одного варианта (раздел scenarios:).']
    for name, sh in scn.items():
        if not isinstance(sh, dict):
            errors.append(f'Вариант «{name}»: нужны доли вида {{Ж: 60, К: 10, ОД: 30, П: 0}}.')
            continue
        extra = set(sh) - set(GROUPS)
        miss = set(GROUPS) - set(sh)
        if extra:
            errors.append(f'Вариант «{name}»: неизвестные группы {sorted(extra)}; допустимо Ж, К, ОД, П.')
        if miss:
            errors.append(f'Вариант «{name}»: не указаны доли {sorted(miss)} (поставьте 0).')
        vals = list(sh.values())
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 for v in vals):
            errors.append(f'Вариант «{name}»: доли должны быть неотрицательными числами.')
        elif sum(vals) <= 0:
            errors.append(f'Вариант «{name}»: сумма долей равна нулю.')
    return errors
