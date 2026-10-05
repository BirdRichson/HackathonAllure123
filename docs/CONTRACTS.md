# Контракты данных и API

Единый источник форматов для бэкенда, фронтенда, симулятора и импорта. **Любое изменение — сначала здесь, потом в коде обеих сторон.**

Статус: ✅ реализовано · ⏳ запланировано (номер этапа).

## Общие правила

- Время — ISO 8601 с поясом `+05:00` (Костанай), например `2026-10-12T08:15:00+05:00`.
- Доли — числа от 0 до 1 (`0.852`); проценты делает интерфейс.
- Длительности — в минутах (`duration_min`), время работы — в часах (`run_hours`).
- `id` участков и оборудования — ASCII (`WELD`, `CAM-02`); `name` — как в данных организаторов («Камера-02»).
- `source`: `data` — из данных организаторов, `assumption` — допущение модели.

## Справочники

**Участки** (`area_id`): `WH` склад комплектующих → `WELD` сварка → `PAINT` окраска → `ASSY` сборка → `QC` контроль качества → `FG` склад готовой продукции.

**Линии** (`line_id`, как в данных): `Сварка-1`, `Окраска-1`, `Сборка-1`.

**Оборудование:** `config/plant.yaml` → `equipment`.

**Модели** (`model`): `Chevrolet Onix`, `Chevrolet Cobalt`, `JAC J7`.

**Состояния оборудования** (`state`):

| Код | Подпись | Цвет |
|---|---|---|
| `running` | Работает | зелёный |
| `starved` | Нет входа | жёлтый |
| `blocked` | Выход занят | жёлтый |
| `down` | Авария | красный |
| `maintenance` | ТО | синий |
| `setup` | Переналадка | синий |
| `offline` | Отключено | серый |

**Причины простоя** (`reason`): `config/reasons.yaml`. Это коды `breakdown`, `consumables`, `planned_maintenance`, `starved`, `blocked`, `no_material`, `changeover`, `quality_hold`, `operator`, `other`, плюс исходный текст `reason_text` и признак `planned`.

## Сущности

### Событие состояния ⏳ (этап 1)
```json
{"ts":"2026-10-12T08:15:00+05:00","type":"state_change","equipment_id":"ABB-01","area_id":"WELD","line_id":"Сварка-1",
 "state":"down","reason":"breakdown","reason_text":"Ошибка датчика","planned":false}
```

### Телеметрия ⏳ (этап 1)
```json
{"ts":"...","equipment_id":"CONV-03","temperature":61.2,"vibration":4.8,"current":12.1,"cycle_time":232.0}
```
Для камер окраски (`paint_booth`) добавляется `filter_dp` — перепад давления на фильтре, Па. Единицы: °C, мм/с, А, секунды.

### Выпуск и качество ⏳ (этап 1)
```json
{"ts":"...","area_id":"PAINT","unit_id":"U-000123","model":"Chevrolet Onix","result":"ok|defect|rework_ok","defect_code":"PAINT_DIRT"}
```

### План
- Смена: `{"date":"2026-10-12","shift":1,"line_id":"Сборка-1","planned_units":120}`
- Месяц: `{"month":"2026-10","model":"Chevrolet Onix","planned_units":2500}`

### KPI ⏳ (этап 2)
```json
{"scope":"plant|area|equipment","id":"PAINT","period":"shift|day|month","from":"...","to":"...",
 "availability":0.963,"performance":0.954,"quality":0.948,"oee":0.871,"load_time":0.963,
 "plan_units":120,"fact_units":116,"good_units":110,"defect_rate":0.052,"downtime_min":18,
 "targets_ok":{"oee":true,"defect_rate":false}}
```

### Инцидент ⏳ (этап 2)
```json
{"id":"INC-0042","ts_start":"...","ts_end":null,"status":"open|closed","severity":"info|warning|critical",
 "type":"downtime|quality|threshold|prediction|reconciliation","area_id":"PAINT","equipment_id":"CAM-02",
 "title":"Превышен допустимый брак: 5,2% при норме 2%","details":"..."}
```

### Прогноз отказа ⏳ (этап 4)
```json
{"ts":"...","equipment_id":"CONV-03","failure_prob_4h":0.78,"top_factors":["current_trend_60m","vibration_trend_60m"],
 "recommendation":"Заменить/натянуть цепь Конвейера-03 в пересменку"}
```

### Отчёт о простое ⏳ (этапы 1–2)
Второй источник данных — люди. Станок остановился — система создаёт `draft` с временем и оборудованием. Рабочий указывает причину и описание с планшета или через Telegram, и отчёт становится `completed`.
```json
{"id":"R-000187","equipment_id":"CAM-02","area_id":"PAINT","ts_start":"...","ts_end":"...",
 "source":"machine|operator_form|telegram|import","reporter_role":"оператор|наладчик|мастер",
 "reason":"consumables","description":"камера встала, фильтр забит, давление в красной зоне",
 "actions_taken":"заменили фильтр, 40 мин","status":"draft|completed"}
```

### Статус ТО ⏳ (этап 2)
```json
{"equipment_id":"CAM-02","interval_h":160,"hours_since":131.5,"hours_left":28.5,
 "next_due_ts":"...","last_done_ts":"..."}
```

### Вывод ИИ ⏳ (этап 4)
```json
{"id":"INS-0012","ts":"...","scope":"plant|area|equipment","target_id":"CAM-02",
 "kind":"recurring|quality_link|maintenance|misclassified|failure_risk|plan_risk",
 "title":"Фильтр Камеры-02 забивается раньше интервала ТО",
 "explanation":"...","evidence":[{"type":"report","ref":"R-000187"},{"type":"metric","ref":"PAINT.defect_rate"}],
 "recommendation":"Менять фильтр в пересменку каждые 110 моточасов",
 "expected_effect":{"units_month":95,"downtime_min_month":160},
 "confidence":0.8,"source":"llm|ml|rules"}
```

### Узкое место ⏳ (после 8.10)
```json
{"ts":"...","area_id":"PAINT","score":0.86,"horizon_min":120,"reason":"наибольший активный период, буфер перед участком заполнен на 90%"}
```

## WebSocket ⏳ (этап 2)

`/ws/live` — сообщения `{"type": "...", "payload": {...}}`. Типы: `snapshot` | `event` | `kpi` | `alert` | `prediction` | `report` | `insight`. При подключении сначала приходит `snapshot` (полное состояние), затем дельты.

## REST

| Метод и путь | Назначение | Статус |
|---|---|---|
| `GET /api/health` | `{status, version, data_mode, time}` | ✅ |
| `GET /api/plant` | модель завода из `plant.yaml` | ✅ |
| `GET /api/targets` | целевые показатели из `targets.yaml` | ✅ |
| `GET /api/areas/{id}` | сводка для страницы цеха: оборудование, ТО, KPI, простои, отчёты, выводы ИИ | ⏳ 2 |
| `GET /api/kpi?scope=&id=&from=&to=` | KPI | ⏳ 2 |
| `GET /api/incidents?status=` | инциденты | ⏳ 2 |
| `GET /api/equipment/{id}` | карточка оборудования с телеметрией | ⏳ 2 |
| `GET /api/maintenance` | статус планового ТО по оборудованию | ⏳ 2 |
| `GET /api/reports?area=&equipment=&status=` | журнал отчётов о простоях | ⏳ 2 |
| `POST /api/reports` | новый отчёт рабочего | ⏳ 2 |
| `PATCH /api/reports/{id}` | дополнить черновик причиной и описанием | ⏳ 2 |
| `GET /api/insights?scope=&id=` | выводы ИИ | ⏳ 4 |
| `POST /api/insights/refresh` | пересчитать выводы ИИ | ⏳ 4 |
| `GET /api/predictions` | прогнозы отказов | ⏳ 4 |
| `GET /api/plan/forecast?month=` | прогноз выпуска на конец месяца против цели, по моделям | ⏳ 4 |
| `GET /api/reconciliation?from=&to=` | сверка потерь времени с простоями | ⏳ 2 |
| `POST /api/sim/control` | `{speed, pause, reset, seed}` | ⏳ 2 |
| `POST /api/scenarios/{name}/trigger` | запуск сценария демо | ⏳ 5 |
| `POST /api/ingest` | загрузка docx / xlsx / csv | ⏳ 2 |
| `GET /api/report/shift?date=&shift=` | отчёт смены | после 8.10 |
| `GET /api/bottlenecks` | узкие места | после 8.10 |
| `POST /api/whatif` | «что если»: потери выпуска с интервалом | после 8.10 |
| `POST /api/assistant/ask` | вопрос LLM-ассистенту | после 8.10 |

## Импорт данных организаторов ⏳ (этап 2)

Вход — docx тестовых данных (таблицы через python-docx), xlsx или CSV с теми же колонками. Выход — 4 нормализованные таблицы (формат как в `data/test/*.csv`):

| Таблица | Колонки |
|---|---|
| `lines` | `date, line_id, area, plan_units, fact_units, run_hours, load_pct` |
| `downtime` | `date, area, equipment, reason_text, duration_min` → дополняется `equipment_id, reason, planned` |
| `plan_models` | `model, plan_month_units` |
| `quality` | `date, area, produced, defects, defect_pct` |

Что учитывает разбор:
- даты `ДД.ММ.ГГГГ` переводятся в ISO;
- десятичный разделитель бывает и запятой (`1,7`), и точкой (`7.8`);
- названия оборудования кириллицей сопоставляются по `name` в `plant.yaml`;
- неизвестная причина простоя записывается как `other` с предупреждением.

Ответ — отчёт валидации: сколько строк загружено, предупреждения, найденные расхождения (сверка потерь времени с простоями).

## История симуляции ✅ (этап 1)

`make seed` → `data/synthetic/` (в git не попадает, генерируется за ~10 с). Время везде в UTC+5.

| Файл | Колонки |
|---|---|
| `events.parquet` | `ts, scope (area/equipment), id, area_id, state, reason, reason_text, planned` — смены состояний |
| `telemetry.parquet` | `ts, equipment_id, temperature, vibration, current, cycle_time, filter_dp` — раз в минуту в рабочее время; `filter_dp` только у камер окраски |
| `units.parquet` | `ts, unit_id, model, area_id, defect_code, result` — кузов закончил цикл на участке; `defect_code` пустой = годный |
| `reports.parquet` | отчёт о простое (см. выше) плюс скрытые поля `true_reason`, `true_subtype`, `machine_reason_text` — истина для оценки ИИ, в интерфейс не отдаются; `duration_min` |
| `shifts.parquet` | `date, shift, area_id, plan_units, fact_units, defects, defect_rate, run_h, down_min, maintenance_min, setup_min, starved_min, blocked_min, lost_min, registered_min` |
| `meta.json` | seed, период, число строк, пометка «демо-данные» |

Хуки сценариев в `PlantSim`:
- `schedule_failure(equipment_id, mode_id, in_op_min, lead_min)` — отказ через заданную наработку, с предвестником;
- `set_filter_remaining(equipment_id, remaining_h)` — фильтр засорится через заданное время;
- `maintenance_window = "night"` — плановое ТО переносится в нерабочее окно.
