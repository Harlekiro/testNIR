"""Командная строка.

    python -m mixuse init    <папка с данными>        составить файл настроек по папке с данными
    python -m mixuse check   configs/<код>.yaml       проверить данные, понятные сообщения об ошибках
    python -m mixuse blocks  configs/<код>.yaml       таблица кварталов (шаги 1–4)
    python -m mixuse compare configs/<код>.yaml       сравнение вариантов (шаги 5–6) + шаги 7, 7б, карта, слои
"""
import argparse
import os
import sys
import time

import pandas as pd

from .config import load_config, ConfigError
from .geometry import CRSError
from .blocks import load_layers, build_table, DataError
from .compare import compare, TerritoryError
from .checks import check_config, sensitivity, builtin_sensitivity
from . import export
from .init_config import make_config

USER_ERRORS = (ConfigError, CRSError, DataError, TerritoryError, FileNotFoundError)


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


def _report_lines(cfg, city):
    lines = [f'Набор данных: {cfg["name"]}', f'Настройки: {cfg["_path"]}', '', 'Отчёт о подготовке данных:']
    for n in city.get('crs_notes', []):
        lines.append(f'  пересчёт координат: {n}')
    for k, v in city['report'].items():
        lines.append(f'  {k}: {v}')
    lines += ['', 'Параметры:'] + [f'  {k} = {v}' for k, v in cfg['params'].items()]
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
    lines = _report_lines(cfg, city)
    lines += ['', f'Территория: кварталы {T}'] + [f'  {k}: {v}' for k, v in info.items()]
    for s in lines[3:]:
        _say(s)
    files = [export.blocks_csv(city, export.out_path(out, code, 'таблица_кварталов.csv')),
             export.table_csv(table, export.out_path(out, code, 'сравнение_вариантов.csv'))]
    with pd.option_context('display.width', 250, 'display.max_columns', 20, 'display.max_colwidth', 40):
        _say('\nСравнение вариантов:'); _say(table.to_string())
        if not args.fast:
            stab = sensitivity(city, T, P, SCN)
            files.append(export.table_csv(stab, export.out_path(out, code, 'устойчивость.csv'), index=False))
            _say('\nШаг 7. Устойчивость:'); _say(stab.to_string(index=False))
            bs = builtin_sensitivity(L, cfg, P, T, SCN)
            if bs is not None:
                files.append(export.table_csv(bs, export.out_path(out, code, 'встроенные.csv'), index=False))
                _say('\nШаг 7б. Встроенные помещения:'); _say(bs.to_string(index=False))
    show = args.show or (list(SCN)[1] if len(SCN) > 1 else list(SCN)[0])
    if show not in SCN:
        raise ConfigError(f'--show: варианта «{show}» нет. Есть: {", ".join(SCN)}')
    files += [export.map_png(city, det, show, P['R'], cfg.get('title') or code, export.out_path(out, code, f'карта_{show.split()[0]}.png')),
              export.blocks_geojson(city, export.out_path(out, code, 'кварталы.geojson'), det, SCN),
              export.web_json(city, cfg, export.out_path(out, code, 'для_страницы.json')),
              export.report_txt(lines, export.out_path(out, code, 'отчёт_подготовки.txt'))]
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
        c.add_argument('config', help='файл настроек, например configs/spb.yaml')
        c.add_argument('--out', help='папка результатов (по умолчанию results)')
        if name == 'check':
            c.add_argument('--quick', action='store_true', help='только проверка файлов и полей, без пробного расчёта')
        if name == 'compare':
            c.add_argument('--territory', help='номера кварталов территории через запятую (вместо territory: в настройках)')
            c.add_argument('--show', help='какой вариант показать на карте')
            c.add_argument('--fast', action='store_true', help='без шагов 7 и 7б')
        c.set_defaults(fn=fn)
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
