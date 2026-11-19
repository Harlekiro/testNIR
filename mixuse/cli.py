"""Командная строка.

    python -m mixuse init    <папка с данными>        составить файл настроек по папке с данными
    python -m mixuse check   configs/<код>.yaml       проверить данные, понятные сообщения об ошибках
    python -m mixuse blocks  configs/<код>.yaml       таблица кварталов (шаги 1–4)
    python -m mixuse compare configs/<код>.yaml       сравнение вариантов (шаги 5–6) + шаги 7, 7б, карта, слои
    python -m mixuse explore configs/<код>.yaml       перебор сочетаний долей (раздел 7)
    python -m mixuse access  configs/<код>.yaml       матрица доступности через blocksnet (раздел 12; Python 3.11)
    python -m mixuse provision configs/<код>.yaml     обеспеченность школами и садами через blocksnet (Python 3.11)
"""
import argparse
import os
import sys
import time

import pandas as pd

from .config import load_config, ConfigError, param_origins
from .geometry import CRSError
from .blocks import load_layers, build_table, DataError
from .compare import compare, TerritoryError, KitError
from .checks import check_config, sensitivity, builtin_sensitivity, estimates_check, stats_check, threshold_check
from . import export
from .init_config import make_config
from .data_report import data_report

USER_ERRORS = (ConfigError, CRSError, DataError, TerritoryError, KitError, FileNotFoundError)


def _say(*a):
    print(*a, flush=True)


def _out_dir(cfg, args):
    return os.path.abspath(args.out or cfg.get('output') or 'results')


def _prepare(cfg):
    errors, warns, _ = check_config(cfg)
    if errors:
        raise DataError('Данные не прошли проверку:\n  - ' + '\n  - '.join(errors) +
                        '\nПодробнее: python -m mixuse check ' + cfg['_path'])
    t0 = time.time()
    L = load_layers(cfg, cfg['_groups'])
    city = build_table(L, cfg, cfg['params'], cfg['_groups'])
    _say(f'Подготовка заняла {time.time() - t0:.0f} с')
    return L, city


def _report_lines(cfg, city, info=None):
    lines = [f'Набор данных: {cfg["name"]}', f'Настройки: {cfg["_path"]}', '', 'Отчёт о подготовке данных:']
    lines.append(f'  правила расчёта: {cfg.get("rules", "v5")}')
    for n in city.get('crs_notes', []):
        lines.append(f'  пересчёт координат: {n}')
    for k, v in city['report'].items():
        lines.append(f'  {k}: {v}')
    lines += ['', 'Параметры (значение — откуда, ТЗ 5.1):'] + [f'  {k} = {v} — {how}' for k, v, how in param_origins(cfg, info)]
    return lines


def cmd_init(args):
    path, text = make_config(args.data, name=args.name, out=args.output)
    if os.path.exists(path) and not args.force:
        _say(f'Файл {path} уже есть. Чтобы перезаписать — добавьте --force.')
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    _say(f'Файл настроек составлен: {path}')
    _say('Откройте его, проверьте строки с пометкой «ПРОВЕРЬТЕ» и запустите:')
    _say(f'  python -m mixuse check {path}')
    return 0


def cmd_check(args):
    cfg = load_config(args.config)
    errors, warns, info = check_config(cfg)
    _say(f'Проверка набора «{cfg["name"]}» ({cfg["_path"]})\n')
    for s in info:
        _say('  · ' + s)
    if warns:
        _say('\nПредупреждения (расчёт возможен):')
        for s in warns:
            _say('  ! ' + s)
    if errors:
        _say('\nОшибки (расчёт невозможен):')
        for s in errors:
            _say('  ✗ ' + s)
        return 1
    if not args.quick:
        _say('\nПробный расчёт таблицы кварталов…')
        L, city = _prepare(cfg)
        for line in _report_lines(cfg, city)[3:]:
            if line == '':
                break
            _say(line)
        lines, dwarns = data_report(city, cfg, cfg['params'])
        _say('\nОтчёт о данных:')
        for line in lines:
            _say('  ' + line if line else '')
        if dwarns:
            _say('\nЧто стоит дополнить в данных:')
            for w in dwarns:
                _say('  ! ' + w)
        path = export.report_txt([f'Отчёт о данных: {cfg["name"]} ({cfg["_path"]})', ''] + lines + ['']
                                 + [f'! {w}' for w in warns + dwarns],
                                 export.out_path(_out_dir(cfg, args), cfg['name'], 'отчёт_о_данных.txt'))
        _say(f'\nОтчёт сохранён: {path}')
    _say('\nГотово: ошибок нет.')
    return 0


def cmd_blocks(args):
    cfg = load_config(args.config)
    L, city = _prepare(cfg)
    out = _out_dir(cfg, args); code = cfg['name']
    lines = _report_lines(cfg, city)
    for s in lines[3:]:
        _say(s)
    files = [export.blocks_csv(city, export.out_path(out, code, 'таблица_кварталов.csv')),
             export.blocks_geojson(city, export.out_path(out, code, 'кварталы.geojson')),
             export.report_txt(lines, export.out_path(out, code, 'отчёт_подготовки.txt'))]
    if cfg['rules'] == 'v5':
        files.append(export.buildings_csv(city, export.out_path(out, code, 'здания.csv')))
    _say('\nСохранено:'); [_say('  ' + f) for f in files]
    return 0


def cmd_compare(args):
    cfg = load_config(args.config)
    if args.territory:
        try:
            cfg['territory'] = [int(x) for x in args.territory.split(',') if x.strip()]
        except ValueError:
            raise ConfigError('--territory: номера кварталов через запятую, например --territory 12,13')
    L, city = _prepare(cfg)
    P, SCN, T = cfg['params'], cfg['scenarios'], cfg['territory']
    out = _out_dir(cfg, args); code = cfg['name']
    table, info, det = compare(city, T, P, SCN)
    v5 = cfg['rules'] == 'v5'
    warns = info.pop('предупреждения', []) if v5 else []
    lines = _report_lines(cfg, city, info)
    lines += ['', f'Территория: кварталы {T}'] + [f'  {k}: {v}' for k, v in info.items()]
    lines += [f'  ! {w}' for w in warns]
    if v5:
        lines += ['', 'Вывод по вариантам (4.7.0):'] + [f'  {n}: {c}' for n, c in det['conclusions'].items()]
    for s in lines[3:]:
        _say(s)
    files = [export.blocks_csv(city, export.out_path(out, code, 'таблица_кварталов.csv'))]
    if v5:      # краткая таблица 4.7.0 — основной вывод; подробная — отдельным файлом
        files += [export.table_csv(det['short'], export.out_path(out, code, 'сравнение_вариантов.csv')),
                  export.table_csv(table, export.out_path(out, code, 'сравнение_подробно.csv'))]
    else:
        files.append(export.table_csv(table, export.out_path(out, code, 'сравнение_вариантов.csv')))
    with pd.option_context('display.width', 250, 'display.max_columns', 20, 'display.max_colwidth', 40):
        _say('\nСравнение вариантов:'); _say((det['short'].drop(index='Вывод') if v5 else table).to_string())
        if v5:
            _say('\nПодробно:'); _say(table.to_string())
        if not args.fast:
            stab = sensitivity(city, T, P, SCN)
            files.append(export.table_csv(stab, export.out_path(out, code, 'устойчивость.csv'), index=False))
            _say('\nШаг 7. Устойчивость:'); _say(stab.to_string(index=False))
            bs = builtin_sensitivity(L, cfg, P, T, SCN)
            if bs is not None:
                files.append(export.table_csv(bs, export.out_path(out, code, 'встроенные.csv'), index=False))
                _say('\nШаг 7б. Встроенные помещения:'); _say(bs.to_string(index=False))
            if cfg['rules'] == 'v5':
                for title, df, suffix in [
                        ('4.8.3. Основная оценка и нижняя граница', estimates_check(city, T, P, SCN), 'оценки.csv'),
                        ('4.8.4. Сравнение со статистикой', stats_check(city, P), 'статистика.csv'),
                        ('4.8.5. Порог площади одноэтажного здания производственной зоны',
                         threshold_check(L, cfg, P, T, SCN), 'порог_цеха.csv')]:
                    if df is not None:
                        files.append(export.table_csv(df, export.out_path(out, code, suffix), index=False))
                        _say(f'\n{title}:'); _say(df.to_string(index=False))
    show = args.show or (list(SCN)[1] if len(SCN) > 1 else list(SCN)[0])
    if show not in SCN:
        raise ConfigError(f'--show: варианта «{show}» нет. Есть: {", ".join(SCN)}')
    files += [export.map_png(city, det, show, P['R'], cfg.get('title') or code, export.out_path(out, code, f'карта_{show.split()[0]}.png')),
              export.blocks_geojson(city, export.out_path(out, code, 'кварталы.geojson'), det, SCN),
              export.report_txt(lines, export.out_path(out, code, 'отчёт_подготовки.txt'))]
    if cfg['rules'] == 'v5':
        files.append(export.buildings_csv(city, export.out_path(out, code, 'здания.csv')))
        _say('\nФайл для страницы по правилам v5 появится на этапе 7.')
    else:
        files.append(export.web_json(city, cfg, export.out_path(out, code, 'для_страницы.json')))
    _say('\nСохранено:'); [_say('  ' + f) for f in files]
    return 0


def _pairs(items, what):
    """«К=20» → {'К': 20}."""
    out = {}
    for it in items or []:
        for part in str(it).split(','):
            if not part.strip():
                continue
            if '=' not in part:
                raise ConfigError(f'{what}: нужен вид «группа=процент», например К=20; получено «{part}».')
            g, v = part.split('=', 1)
            try:
                out[g.strip()] = int(v)
            except ValueError:
                raise ConfigError(f'{what}: «{v}» — не целое число процентов.')
    return out


def explore_settings(cfg, args):
    """Настройки перебора (ТЗ, раздел 7): по умолчанию Ж, К, ОД, шаг 10 %, К не больше 20 %;
    раздел explore: в файле настроек; ключи команды — поверх него."""
    from .scenarios import EXPLORE_DEFAULTS, GROUPS
    raw = cfg.get('explore') or {}
    groups = list(raw.get('groups') or EXPLORE_DEFAULTS['groups'])
    step = int(raw.get('step') or EXPLORE_DEFAULTS['step'])
    mx = dict(EXPLORE_DEFAULTS['max'] if raw.get('max') is None else raw['max'])
    mn = dict(raw.get('min') or {})
    filters = list(raw.get('filters') or [])
    if args.groups:
        groups = [g.strip() for g in args.groups.split(',') if g.strip()]
    if args.step:
        step = args.step
    mx.update(_pairs(args.max, '--max'))
    mn.update(_pairs(args.min, '--min'))
    filters += args.filter or []
    bad = [g for g in groups + list(mx) + list(mn) if g not in GROUPS]
    if bad:
        raise ConfigError(f'Перебор: неизвестные группы {bad}; допустимо Ж, К, ОД, П.')
    return groups, step, mx, mn, filters


def cmd_explore(args):
    from .scenarios import enumerate_shares, explore, apply_filters, explore_summary
    cfg = load_config(args.config)
    if cfg['rules'] != 'v5':
        raise ConfigError('Перебор сочетаний считает показатели правил v5 (rules: v5).')
    if args.territory:
        cfg['territory'] = [int(x) for x in args.territory.split(',') if x.strip()]
    groups, step, mx, mn, filters = explore_settings(cfg, args)
    try:
        combos = enumerate_shares(groups, step, mx, mn)
    except ValueError as e:
        raise ConfigError(str(e))
    if not combos:
        raise ConfigError('Перебор: при таких минимумах и максимумах нет ни одного сочетания с суммой 100 %.')
    L, city = _prepare(cfg)
    P, T = cfg['params'], cfg['territory']
    table, info = explore(city, T, P, combos)
    try:
        shown = apply_filters(table, filters)
    except ValueError as e:
        raise ConfigError(str(e))
    summary = explore_summary(table, groups)
    out = _out_dir(cfg, args); code = cfg['name']
    _say(f'Перебор: группы {", ".join(groups)}, шаг {step} %, максимум {mx or "—"}, минимум {mn or "—"}; '
         f'сочетаний {len(combos)}' + (f', после фильтров {len(shown) - 1}' if filters else ''))
    _say(f'Территория: кварталы {T}; КИТ {info["КИТ варианта"]} — {info["КИТ: откуда"]}; '
         f'КИТ варианта / окружения: {info["КИТ варианта / окружения"]}')
    for w in info.get('предупреждения', []):
        _say('  ! ' + w)
    files = [export.table_csv(shown, export.out_path(out, code, 'перебор.csv'), index=False),
             export.table_csv(summary, export.out_path(out, code, 'перебор_сводка.csv'), index=False)]
    with pd.option_context('display.width', 250, 'display.max_columns', 30, 'display.max_colwidth', 40):
        _say('\nСводка (диапазон показателя и влияние долей; без оценок «лучше / хуже»):')
        _say(summary[['показатель', 'от', 'до', 'сильнее всего зависит от доли']].to_string(index=False))
    _say('\nСохранено:'); [_say('  ' + f) for f in files]
    return 0


def cmd_access(args):
    """Этап 8.3: матрица доступности по кварталам набора (blocksnet), сохраняется в data/<код>/access/."""
    from .provision_bn import build_matrix, save_matrix, check_matrix, file_sha256, BlocksnetError
    cfg = load_config(args.config)
    try:
        mx, meta = build_matrix(cfg, graph_type=args.graph, retries=args.retries, say=_say)
    except BlocksnetError as e:
        raise ConfigError(str(e))
    from .blocks import load_blocks
    ids = load_blocks(cfg)[0]['block_id'].tolist()
    errs = check_matrix(mx, meta, ids, file_sha256(cfg['blocks']))
    if errs:
        raise DataError('Матрица не соответствует кварталам mixuse: ' + '; '.join(errs))
    pm, pj = save_matrix(cfg, mx, meta, args.graph)
    _say(f'Соответствие кварталов: {len(ids)} номеров, порядок и номера совпадают с таблицей mixuse.')
    for k, v in meta.items():
        if k != 'block_id':
            _say(f'  {k}: {v}')
    _say(f'\nСохранено:\n  {pm}\n  {pj}')
    return 0


def cmd_provision(args):
    """Этап 8.4: обеспеченность школами и садами «как есть» через blocksnet (раздел 12); рядом — запасной расчёт 4.7.3."""
    from .provision_bn import load_matrix, as_is_report, BlocksnetError, require_blocksnet
    cfg = load_config(args.config)
    if args.territory:
        cfg['territory'] = [int(x) for x in args.territory.split(',') if x.strip()]
    try:
        require_blocksnet()
        L, city = _prepare(cfg)
        mx, meta = load_matrix(cfg, city['table']['block_id'].tolist())
    except BlocksnetError as e:
        raise ConfigError(str(e))
    _say(f'Матрица: граф {meta.get("граф")}, blocksnet {meta.get("blocksnet")}, построена {meta.get("построено")}; '
         f'соответствие кварталов проверено.')
    summary, blocks = as_is_report(cfg, city, mx, cfg['territory'])
    out = _out_dir(cfg, args); code = cfg['name']
    files = [export.table_csv(summary, export.out_path(out, code, 'обеспеченность.csv')),
             export.table_csv(blocks, export.out_path(out, code, 'обеспеченность_кварталы.csv'), index=False)]
    with pd.option_context('display.width', 200, 'display.max_colwidth', 70):
        _say(f'\nОбеспеченность «как есть», территория {cfg["territory"]}:'); _say(summary.to_string())
    _say('\nСохранено:'); [_say('  ' + f) for f in files]
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog='python -m mixuse', description='Сравнение сочетаний функций на территории.')
    sub = p.add_subparsers(dest='cmd', required=True, metavar='команда')
    a = sub.add_parser('init', help='составить файл настроек по папке с данными')
    a.add_argument('data', help='папка с данными (кварталы, здания, сервисы, зоны)')
    a.add_argument('--name', help='короткий код набора (латиницей), по умолчанию — имя папки')
    a.add_argument('-o', '--output', help='куда записать настройки (по умолчанию configs/<код>.yaml)')
    a.add_argument('--force', action='store_true', help='перезаписать существующий файл')
    a.set_defaults(fn=cmd_init)
    for name, fn, hlp in [('check', cmd_check, 'проверить данные'), ('blocks', cmd_blocks, 'таблица кварталов'),
                          ('compare', cmd_compare, 'сравнить варианты для территории')]:
        c = sub.add_parser(name, help=hlp)
        c.add_argument('config', help='файл настроек, например configs/vysotsk.yaml')
        c.add_argument('--out', help='папка результатов (по умолчанию results)')
        if name == 'check':
            c.add_argument('--quick', action='store_true', help='только проверка файлов и полей, без пробного расчёта')
        if name == 'compare':
            c.add_argument('--territory', help='номера кварталов территории через запятую (вместо territory: в настройках)')
            c.add_argument('--show', help='какой вариант показать на карте')
            c.add_argument('--fast', action='store_true', help='без шагов 7 и 7б')
        c.set_defaults(fn=fn)
    e = sub.add_parser('explore', help='перебор сочетаний долей (ТЗ, раздел 7)')
    e.add_argument('config', help='файл настроек, например configs/vysotsk.yaml')
    e.add_argument('--out', help='папка результатов (по умолчанию results)')
    e.add_argument('--territory', help='номера кварталов территории через запятую')
    e.add_argument('--groups', help='допустимые группы через запятую, по умолчанию Ж,К,ОД')
    e.add_argument('--step', type=int, help='шаг долей, %% (по умолчанию 10)')
    e.add_argument('--max', action='append', help='максимум доли группы, например К=20 (по умолчанию К=20)')
    e.add_argument('--min', action='append', help='минимум доли группы, например ОД=10')
    e.add_argument('--filter', action='append', help='условие, например "K окружения>=0.5" (можно несколько)')
    e.set_defaults(fn=cmd_explore)
    a2 = sub.add_parser('access', help='матрица доступности кварталов через blocksnet (раздел 12, этап 8.3)')
    a2.add_argument('config', help='файл настроек, например configs/vysotsk.yaml')
    a2.add_argument('--graph', default='walk', choices=['walk', 'drive', 'intermodal'],
                    help='вид графа (по решению автора — walk, пешеходный)')
    a2.add_argument('--retries', type=int, default=4,
                    help='сколько раз пробовать скачать граф (0 — пока сервер не ответит; скачанные части сохраняются)')
    a2.set_defaults(fn=cmd_access)
    pv = sub.add_parser('provision', help='обеспеченность школами и садами через blocksnet (раздел 12, этап 8.4)')
    pv.add_argument('config', help='файл настроек, например configs/vysotsk.yaml')
    pv.add_argument('--out', help='папка результатов (по умолчанию results)')
    pv.add_argument('--territory', help='номера кварталов территории через запятую')
    pv.set_defaults(fn=cmd_provision)
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except USER_ERRORS as e:
        _say(f'\nОшибка: {e}')
        return 2
