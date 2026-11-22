"""Анкеты шага 0 для трёх наборов — так, как их заполняет пользователь по инструкции docs/инструкция_пользователя.md
(ТЗ 18.4): слои лежат в data/<код>_user/, пути — от папки ноутбука; примеры ноутбука и файлы YAML не используются.

FORMS[код] = (текст анкеты для ячейки «Шаг 0», параметры для ячейки P, откуда копировать слои).
С ТЗ 18.2а всё задаётся в анкете: ячейку P пользователь не трогает (словарь параметров пуст).
"""

FORMS = {
    'vysotsk': ('''ДАННЫЕ = dict(
    название='Высоцк',
    код='vysotsk_user',
    правила='v5',
    режим='слои',
    кварталы=dict(файл='data/vysotsk_user/кварталы.geojson', поле_номера=None),
    здания=dict(файл='data/vysotsk_user/здания.geojson', поле_жилое='is_living', поле_этажность='number_of_floors',
                поле_площадь_застройки='footprint_area', поле_жилая_площадь='living_area', поле_жители='population'),
    сервисы=dict(файл=['data/vysotsk_user/сервисы', 'data/vysotsk_user/промышленность'], поле_типа=None, поле_мест='capacity'),
    зоны=dict(файл='data/vysotsk_user/зоны.geojson', поле_кода='Зона', поле_в_кварталах=None,
              правила=None),
    территория=[305, 309, 314],
    кит=dict(значение=None, источник='ПЗЗ нет, тип застройки города — мало- и среднеэтажная', строка_СП='zh_low_mid',
             процент_застройки_ПЗЗ=None, этажность_ПЗЗ=None),
    точный_расчёт=dict(включить=False, файл_OSM=None),
)
''', {},
        [('data/vysotsk/кварталы.geojson', 'кварталы.geojson'), ('data/vysotsk/здания.geojson', 'здания.geojson'),
         ('data/vysotsk/зоны.geojson', 'зоны.geojson'), ('data/vysotsk/сервисы', 'сервисы'),
         ('data/vysotsk/промышленность', 'промышленность')]),

    'gatchina_layers': ('''ДАННЫЕ = dict(
    название='Гатчина',
    код='gatchina_layers_user',
    правила='v5',
    режим='слои',
    кварталы=dict(файл='data/gatchina_layers_user/кварталы.gpkg', поле_номера='block_id'),
    здания=dict(файл='data/gatchina_layers_user/здания.geojson', поле_жилое='is_living', поле_этажность='number_of_floors',
                поле_площадь_застройки='footprint_area', поле_жилая_площадь='living_area', поле_жители='population'),
    сервисы=dict(файл='data/gatchina_layers_user/services', поле_типа=None, поле_мест='capacity'),
    зоны=dict(файл=None, поле_кода=None, поле_в_кварталах='land_use',
              правила=None),
    территория=[322, 323, 377],
    кит=dict(значение=None, источник='целевая зона О-8 ПЗЗ МО «Город Гатчина»', строка_СП='zh_multi',
             процент_застройки_ПЗЗ=None, этажность_ПЗЗ=None),
    ограничения_территории='жильё допустимо только вне санитарно-защитных зон действующих предприятий',
    точный_расчёт=dict(включить=False, файл_OSM=None),
)
''', {},
        [('data/gatchina_layers/кварталы.gpkg', 'кварталы.gpkg'), ('data/gatchina_layers/здания.geojson', 'здания.geojson'),
         ('data/gatchina_layers/services', 'services')]),

    'spb_full': ('''ДАННЫЕ = dict(
    название='Санкт-Петербург',
    код='spb_full_user',
    правила='v5',
    режим='слои',
    кварталы=dict(файл='data/spb_full_user/blocks.geojson', поле_номера=None),
    здания=dict(файл='data/spb_full_user/buildings.geojson', поле_жилое='is_living', поле_этажность='storeys_count',
                поле_площадь_застройки='building_area', поле_жилая_площадь='living_area', поле_жители='population_balanced'),
    сервисы=dict(файл='data/spb_full_user/services', поле_типа=None, поле_мест='capacity'),
    зоны=dict(файл='data/spb_full_user/functional_zones.geojson', поле_кода='functional_zone', поле_в_кварталах=None,
              правила=None),
    территория=[8346, 9366, 2059],
    кит=dict(значение=1.4, источник='ПЗЗ Санкт-Петербурга, зоны ТСМ и ТД1-1', строка_СП=None,
             процент_застройки_ПЗЗ=None, этажность_ПЗЗ=None),
    статистика=dict(работников=1472900, источник='Петростат, 2022 — работники организаций без малого бизнеса'),
    точный_расчёт=dict(включить=False, файл_OSM=None),
)
''', {},
        [('data/spb_full/blocks.geojson', 'blocks.geojson'), ('data/spb_full/buildings.geojson', 'buildings.geojson'),
         ('data/spb_full/functional_zones.geojson', 'functional_zones.geojson'), ('data/spb_full/services', 'services')]),
}
