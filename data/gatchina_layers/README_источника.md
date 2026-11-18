# `data/gatchina/` — сценарий «Гатчина»

> Этот файл упаковывается в архив `gatchina-data.zip` (см. `data/manifest.json`).
> Контрольные суммы и размер пересчитываются скриптом `scripts/package_data.py`.

## Что внутри

| Файл / каталог | Размер | Назначение |
|---|---|---|
| `data/blocks_with_services.gpkg` | 0.5 МБ | Кварталы (351) + population + land_use + share + `capacity_<service>` + `count_<service>` для 46 сервисов. **Контракт `load_blocks` готов.** |
| `data/acc_mx.pickle` | 0.25 МБ | Матрица доступности 351×351, float16. **Времена по drive-графу** (копия `acc_mx_drive.pickle`). |
| `data/acc_mx_drive.pickle` | 0.25 МБ | Исходный файл матрицы (оставлен для прозрачности происхождения). |
| `data/service_type.json` | 67 КБ | Каталог нормативов сервисов (98 записей, как в СПб) |
| `data/services/*.geojson` | 46 файлов, 0.8 МБ | POI по сервисам |
| `data/boundaries.geojson` | — | Сырьё: граница территории |
| `data/buildings.geojson` | 4.9 МБ | Сырьё: здания |
| `data/functional_zones.geojson` | 1.6 МБ | Сырьё: функциональные зоны |
| `data/roads.gpkg` | 1.7 МБ | Сырьё: дороги |

## Совместимость с инструментами

| Инструмент | Работает? | Примечание |
|---|---|---|
| `load_blocks` | ✅ | CRS EPSG:32636, `land_use` в формате `LandUse.RESIDENTIAL` (нормализуется через `_parse_land_use`) |
| `load_accessibility_matrix` | ✅ | 351×351 float16, индекс совпадает с кварталами |
| `list_service_types`, `list_key_services` | ✅ | 46 `capacity_*` колонок; `atm` и `attraction` есть в данных, но отсутствуют в каталоге нормативов |
| `compute_service_provision`, `compute_scenario_provision` | ⚠️ | Работают, но матрица **drive-based**: нормативы accessibility (мин пешком) применяются к временам на машине — обеспеченность систематически завышена |
| `recommend_blocks_for_services` | ⚠️ | То же ограничение по drive-матрице |
| `compute_road_congestion` | ❌ | нет `graph_drive.graphml` + `blocks_to_nodes.pickle` + `nodes_to_nodes.pickle` |

## Как запустить

```bash
DATA_DIR=data/gatchina/data python -m blocksnet_agent
```

Пример:
```bash
DATA_DIR=data/gatchina/data python -c "
import sys, json, time; sys.path.insert(0, '.')
from blocksnet_mcp.tools_mcp import analyze_urban_question
start = time.time()
result = analyze_urban_question('Какие кварталы имеют наименьшее покрытие школами?', max_iterations=4)
print(f'Elapsed: {time.time()-start:.1f}s')
print(json.loads(result))
"
```

## Известные ограничения

- `acc_mx.pickle` построена по **drive-графу** (исходное имя — `acc_mx_drive.pickle`).
  Для walk-provision матрицу нужно пересобрать: MCP-tool `prepare_accessibility_matrix`.
- `compute_road_congestion` требует отдельной подготовки (`prepare_road_congestion_inputs`).

## Контрольные суммы

| Файл | SHA256 |
|---|---|
| `gatchina-data.zip` | `см. data/manifest.json` |
