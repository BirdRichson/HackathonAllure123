# Контракты данных и API

Единый источник форматов для бэкенда, фронтенда, симулятора и импорта. **Любое изменение — сначала здесь, потом в коде обеих сторон.**

Статус: ✅ реализовано · ⏳ запланировано (номер этапа).

## Общие правила

- Время — ISO 8601 с поясом `+05:00` (Костанай), например `2026-10-05T10:30:00+05:00`. Это **время завода** (модели), а не часы компьютера.
- Доли — числа от 0 до 1 (`0.852`); проценты делает интерфейс.
- Длительности — в минутах (`duration_min`, `*_min`), время работы — в часах (`run_hours`, `run_h`) или минутах (`run_min`).
- `id` участков и оборудования — ASCII (`WELD`, `CAM-02`); `name` — как в данных организаторов («Камера-02»).
- `source` у участков и оборудования: `data` — из данных организаторов, `assumption` — допущение модели.

## Справочники

- **Участки** (`area_id`): `WH` склад комплектующих → `WELD` сварка → `PAINT` окраска → `ASSY` сборка → `QC` контроль качества → `FG` склад готовой продукции.
- **Линии** (`line_id`, как в данных): `Сварка-1`, `Окраска-1`, `Сборка-1`.
- **Оборудование:** `config/plant.yaml` → `equipment`.
- **Модели** (`model`): `Chevrolet Onix`, `Chevrolet Cobalt`, `JAC J7`.

**Состояния** (`state`) участков и оборудования:

| Код | Подпись | Цвет |
|---|---|---|
| `running` | Работает | зелёный |
| `starved` | Нет входа | жёлтый |
| `blocked` | Выход занят | жёлтый |
| `idle` | Ожидание: участок остановлен другим оборудованием (только у оборудования) | жёлтый |
| `down` | Авария (у участка — и микроостановка) | красный |
| `maintenance` | ТО | синий |
| `setup` | Переналадка | синий |
| `offline` | Вне смены | серый |

**Причины простоя** (`reason`): `config/reasons.yaml`. Коды: `breakdown`, `consumables`, `planned_maintenance`, `starved`, `blocked`, `no_material`, `changeover`, `quality_hold`, `operator`, `other`. К коду прилагаются исходный текст `reason_text` («Обрыв цепи») и признак `planned`. Справочник для формы — `GET /api/reasons`.

## Сущности

### KPI ✅
```json
{"availability":0.963,"performance":0.954,"quality":0.948,"oee":0.871,
 "plan_units":120,"fact_units":116,"good_units":110,"defects":6,"defect_rate":0.052,
 "run_min":462.0,"planned_min":480.0,
 "lost_min":{"down":10.0,"maintenance":0,"setup":0,"starved":8.0,"blocked":0},
 "targets_ok":{"oee":true,"defect_rate":false},"level":"ok|warn|bad"}
```
- **Плановое время** — прошедшая часть смены или суток. **Идеальный цикл** — 3,8 мин (D2).
- **OEE завода** (`plant`) — среднее OEE сварки, окраски и сборки. **Выпуск завода** (`output`) — кузова, прошедшие контроль качества.

### Отчёт о простое ✅
```json
{"id":"R-000187","equipment_id":"CAM-02","area_id":"PAINT","ts_start":"...","ts_end":"...","duration_min":40.5,
 "source":"machine|operator_form|telegram|import","status":"draft|completed",
 "reason":"consumables","description":"камера встала, фильтр забит","actions_taken":"заменили фильтры",
 "reporter_role":"оператор|наладчик|мастер","machine_reason_text":"Замена фильтра",
 "ai_subtype":"фильтр","ai_reason":"consumables","ai_confidence":0.97,"ai_source":"ml|llm|rules",
 "ai_component":"фильтры потолка","ai_mismatch":false,"ai_note":null}
```
- Поля `ai_*` — разметка ИИ по тексту отчёта. Подтипы: `датчик, цепь, горелка, калибровка, фильтр, плановое ТО, микроостановка`.
- `ai_mismatch` — причина, выбранная рабочим, не совпадает с текстом (уверенность ИИ ≥ 0,6). Микроостановку с «Прочим» за ошибку не считаем.
- `ai_note` — совет мастеру; его даёт только LLM.
- Станок остановился — появляется `draft` (`source: machine`). Рабочий заполняет причину и текст — отчёт становится `completed`.
- `machine_reason_text` — причина, которую зафиксировал станок или журнал.
- Истинные причины симулятора (`true_reason`, `true_subtype`) хранятся в БД для оценки ИИ и **через API не отдаются**.
- `ts_end = null` — простой ещё идёт.

### Инцидент ✅
```json
{"id":"INC-00135","ts_start":"...","ts_end":null,"status":"open|closed","severity":"info|warning|critical",
 "type":"downtime|quality|threshold|oee|prediction","area_id":"PAINT","equipment_id":null,
 "title":"Окраска: брак 9,7% при норме 2%","details":"Смена 1: 3 из 31 кузовов с дефектами."}
```

Правила (цели — `config/targets.yaml`):

| Тип | Когда | Важность |
|---|---|---|
| `downtime` | авария оборудования; открыт, пока стоит | critical для критического оборудования |
| `quality` | брак участка за смену > 2% (после 40 кузовов и 3 дефектов); закрывается в конце смены | critical, если > 4% |
| `threshold` | незапланированный простой критического оборудования за сутки ≥ 45 мин | warning; > 60 мин — critical |
| `oee` | OEE участка за закрытую смену < 85% | warning; < 75% — critical |
| `prediction` | ИИ видит предвестник отказа: риск LightGBM выше порога 2 оценки подряд (конвейеры) или разброс температуры ×2 (печь). Закрывается: «Сбылось…» при отказе, при ТО или когда риск падает вдвое | warning |

### Статус ТО ✅
```json
{"equipment_id":"CAM-02","name":"Камера-02","interval_h":160,"hours_since":131.5,"hours_left":28.5,"progress":0.82,
 "due":false,"duration_min":40,"last_done_ts":"...","next_due_ts":"...","window":"in_shift|night"}
```
`next_due_ts` — оценка: оставшиеся моточасы раскладываются по ближайшим сменам.

### Телеметрия ✅
```json
{"ts":"...","temperature":61.2,"vibration":4.8,"current":12.1,"cycle_time":232.0,"filter_dp":null}
```
Единицы: °C, мм/с, А, секунды, Па. `filter_dp` есть только у камер окраски.

### Вывод ИИ ✅
```json
{"id":"paint_filters","kind":"quality","severity":"critical","area_id":"PAINT","equipment_ids":["CAM-01","CAM-02"],
 "title":"Брак окраски растёт вместе с засорением фильтров камер",
 "summary":"При перепаде на фильтрах 300 Па и выше брак окраски 8,3%, при чистых фильтрах — 2,4%. …",
 "evidence":["1 752 из 4 640 кузовов за 30 дней окрашены при перепаде ≥300 Па", "…"],
 "recommendation":"Менять фильтры по состоянию: … в ближайшую ночь, в нерабочее окно 00:00–08:00.",
 "effect":{"cars_month":50,"defects_month":113,"minutes_month":201,"text":"≈ −113 дефектов окраски в месяц …"},
 "cost":"фильтры будут меняться чаще — расход ≈ +46%","assumptions":["…"],
 "confidence":"высокая|средняя","source":"llm|rules","rank":1}
```
- `id` — вид вывода: `paint_filters`, `maintenance_night`, `wear_failures`, `robot_sensors`, `reports_quality`, `month_plan`.
- **Цифры (`evidence`, `effect`) всегда считает код** по данным за 30 дней до конца последней закрытой смены.
- LLM переписывает только `title`, `summary`, `recommendation` и порядок. Числа в её тексте сверяются с расчётом; если есть лишнее число, остаётся шаблон, `source: rules`.

Состояние выводов (`GET /api/insights`):
```json
{"generated_at":"...","period":{"from":"...","to":"...","workdays":20},"summary":"…","summary_source":"llm|rules",
 "items":[…],"llm":{"provider":"groq","model":"openai/gpt-oss-120b","label":"Groq · openai/gpt-oss-120b",
 "cached":false,"latency_ms":2300,"rejected_by_guard":0},
 "llm_status":"ok|pending|offline|error","llm_error":null,
 "reports":{…сводка по отчётам…},"loss_by_area":{"Сварка":957.0}}
```

### Прогноз отказа ✅
Элемент `GET /api/predictions` → `items[]`, по одному на оборудование. Вид зависит от `kind`.

| `kind` | Оборудование | Поля |
|---|---|---|
| `ml` | конвейеры (LightGBM) | `risk` (0–1, отказ в ближайшие 2 ч), `threshold`, `alert`, `factors[]` |
| `rule` | печь (разброс температуры) | `indicator` (×к норме), `threshold`, `alert`, `factors[]` |
| `filter` | камеры окраски | `dp`, `rate_pa_h`, `hours_to_swap`, `hours_to_limit`, `limit_ts` |
| `base_rate` | роботы, стенды (случайные сбои) | `risk` — фоновая вероятность по частоте, `per_month` |

```json
{"equipment_id":"CONV-03","name":"Конвейер-03","area_id":"ASSY","type":"conveyor","status":"ok","kind":"ml",
 "risk":0.976,"level":"low|medium|high","alert":true,"threshold":0.7,"risk_ts":"...","failure":"Обрыв цепи",
 "factors":[{"feature":"vib_15","label":"Вибрация, 15 мин","value":"+39% к норме","weight":7.75}],
 "note":"Модель LightGBM по току, вибрации и наработке"}
```
Ответ целиком: `{"horizon_min":120,"updated":"...","model_loaded":true,"items":[…],
"stats_30d":{"failures":4,"predicted":4,"mean_lead_min":77}}`.

### Прогноз месяца ✅
`GET /api/plan/forecast`:
```json
{"as_of":"...","month":"2026-10","target":5500,"plan_models":4800,"output_mtd":505,
 "p10":5063,"p50":5106,"p90":5148,"prob_target":0.0,"shift_mean":115.9,"shift_std":3.1,
 "shifts_left":39.7,"shifts_total":44,"required_per_shift":125.9,"max_theoretical":5558,
 "band":[{"date":"2026-10-05","p10":…,"p50":…,"p90":…}],"actual":[{"date":"2026-10-01","cum":118}],
 "by_model":[{"model":"Chevrolet Onix","plan":2500,"mtd":329,"forecast":2473,"share":0.466}]}
```

## WebSocket ✅ `/ws/live`

Сообщения `{"type": "...", "payload": {...}}`:

| Тип | Когда | Содержимое |
|---|---|---|
| `snapshot` | при подключении и после сброса | всё состояние — как `GET /api/state` |
| `tick` | каждые ~0,5 с | `sim_time, speed, paused`; текущие `areas` и `equipment` (состояние, причина, последняя телеметрия); изменения за шаг: `events`, `units` (для анимации кузовов), `reports`, `incidents` |
| `kpi` | каждые ~2 с | как `GET /api/kpi` |
| `status` | после смены скорости или паузы | `sim_time, speed, paused, speeds, seed` |
| `predictions` | когда пересчитан риск (раз в 5 мин модели), не чаще 1 раза в 2 с | как `GET /api/predictions` |
| `insights` | новые выводы (после каждой смены), ответ LLM, обновление | как `GET /api/insights` |

## REST

| Метод и путь | Назначение | Статус |
|---|---|---|
| `GET /api/health` | `{status, version, data_mode, time}` | ✅ |
| `GET /api/plant` | модель завода из `plant.yaml` | ✅ |
| `GET /api/targets` | цели из `targets.yaml` | ✅ |
| `GET /api/state` | полный снимок: статус, смена, участки (с буферами), оборудование (состояние, телеметрия, ТО), KPI, инциденты, последние отчёты, `predictions`, `ai` (`llm_online`, `llm_label`, `failure_model`) | ✅ |
| `GET /api/kpi` | KPI смены, суток (по участкам и заводу) и выпуск месяца против цели | ✅ |
| `GET /api/kpi/history?area=&shifts=12` | KPI закрытых смен участка | ✅ |
| `GET /api/areas/{id}` | страница цеха: участок, оборудование с ТО, KPI (смена, сутки, история), Парето простоев за 30 дней, отчёты, инциденты | ✅ |
| `GET /api/equipment/{id}?hours=8` | карточка: состояние, телеметрия за N часов, норма сигналов, остановки за 30 дней, отчёты | ✅ |
| `GET /api/events?hours=8&area=&scope=` | события состояний за N часов: `initial` (состояние на начало окна) и `events` — для временной шкалы | ✅ |
| `GET /api/maintenance` | статус ТО по всему оборудованию | ✅ |
| `GET /api/downtime/pareto?area=&days=30` | причины и оборудование по минутам простоя | ✅ |
| `GET /api/incidents?status=&area=&limit=` | инциденты | ✅ |
| `GET /api/reconciliation?days=7` | по сменам: потеря времени, записанные простои и незаписанные минуты | ✅ |
| `GET /api/reasons` | справочник причин для формы | ✅ |
| `GET /api/reports?area=&equipment=&status=&limit=` | журнал отчётов о простоях | ✅ |
| `POST /api/reports` | отчёт рабочего; если по станку есть черновик — дополняет его | ✅ |
| `PATCH /api/reports/{id}` | дополнить отчёт | ✅ |
| `POST /api/ingest` (multipart `files`) | загрузка docx / xlsx / csv, разбор и находки | ✅ |
| `GET /api/ingest/latest` | последний импорт; при первом запуске подгружается `data/raw/*.docx` | ✅ |
| `POST /api/sim/control` | `{speed, paused, reset, seed}`; скорости 1, 10, 60, 300 | ✅ |
| `GET /api/insights?area=` | выводы ИИ за 30 дней; `area` — только выводы цеха | ✅ |
| `POST /api/insights/refresh?force=` | пересчитать; `force=true` — заново спросить LLM, не из кэша | ✅ |
| `GET /api/predictions` | риск отказа по оборудованию | ✅ |
| `GET /api/plan/forecast` | прогноз месяца против 5500 | ✅ |
| `GET /api/reports/analysis?days=30&area=` | сводка ИИ по отчётам: незаполненные, неверные причины, повторы | ✅ |
| `POST /api/reports/suggest` | `{equipment_id, description, actions_taken, reason, use_llm}` → подсказка причины и `mismatch` | ✅ |
| `POST /api/assistant/ask` | `{question, area_id}` → `{answer, follow_up[], source}`; без LLM — `{answer: null, error}` | ✅ |
| `GET /api/ai/status` | провайдеры LLM, кэш, последний вызов, метрики моделей, проверка разметки на истине симулятора | ✅ |
| `GET /api/scenarios`, `POST /api/scenarios/{name}/trigger` | сценарии демо: `sensor_fault` (ABB-01), `chain_break` (Конвейер-03, предвестник ~40 мин, ИИ предупреждает заранее), `filter_clog` (Камера-02) | ✅ |
| `POST /api/whatif`, `GET /api/bottlenecks` | после 8.10 | — |

## Импорт данных организаторов ✅

Вход — docx тестовых данных (таблицы через python-docx), xlsx или CSV. Таблица распознаётся по заголовкам — русским, как в docx, или нормализованным.

| Таблица | Колонки |
|---|---|
| `lines` | `date, line_id, plan_units, fact_units, run_hours, load_pct` |
| `downtime` | `date, area, equipment, reason_text, duration_min` → дополняется `equipment_id, area_id, reason, planned` |
| `plan_models` | `model, plan_month_units` |
| `quality` | `date, area, produced, defects, defect_pct` |

Что учитывается при разборе:
- даты `ДД.ММ.ГГГГ` переводятся в ISO;
- десятичный разделитель бывает запятой и точкой;
- оборудование сопоставляется по названию из `plant.yaml`;
- неизвестная причина записывается как `other` с предупреждением;
- цели берутся из текста «Дополнительных вводных», схема участков — из строки со стрелками.

Ответ:
- `rows`, `tables`, `downtime`;
- `kpi_rows` — A/P/Q/OEE по каждой строке, с циклом 3,8 мин и с плановым тактом;
- `reconciliation`, `bottlenecks`, `targets`, `scheme`;
- `findings` — находки по целям с важностью;
- `warnings`.

## История симуляции ✅

`make seed` → `data/synthetic/` (в git не попадает, генерируется за ~10 с). Время в UTC+5.

| Файл | Колонки |
|---|---|
| `events.parquet` | `ts, scope (area/equipment), id, area_id, state, reason, reason_text, planned` |
| `telemetry.parquet` | `ts, equipment_id, temperature, vibration, current, cycle_time, filter_dp` — раз в минуту в рабочее время |
| `units.parquet` | `ts, unit_id, model, area_id, defect_code, result` — кузов закончил цикл на участке |
| `reports.parquet` | отчёт о простое плюс `true_reason`, `true_subtype`, `machine_reason_text`, `duration_min` |
| `shifts.parquet` | `date, shift, area_id, plan_units, fact_units, defects, defect_rate, run_h, down_min, maintenance_min, setup_min, starved_min, blocked_min, lost_min, registered_min` |
| `meta.json` | seed, период, число строк, пометка «демо-данные» |

Хуки сценариев в `PlantSim`:
- `schedule_failure(equipment_id, mode_id, in_op_min, lead_min)`;
- `set_filter_remaining(equipment_id, remaining_h)`;
- `manual_reports` — по этому оборудованию отчёт заполнит человек;
- `maintenance_window = "night"`.

## Настройки ИИ (переменные окружения, файл `.env`)

| Переменная | Значение |
|---|---|
| `GROQ_API_KEY` | ключ Groq (бесплатно: console.groq.com/keys) |
| `GEMINI_API_KEY` | ключ Google Gemini (бесплатно: aistudio.google.com/apikey) |
| `GROQ_MODEL`, `GEMINI_MODEL` | модели через запятую; по умолчанию `openai/gpt-oss-120b,llama-3.3-70b-versatile` и `gemini-3.5-flash,gemini-3.1-flash-lite` |
| `ALLUR_LLM_PROVIDER` | `auto` (по умолчанию) · `groq` · `gemini` · `off` |
| `ALLUR_LLM_ORDER` | порядок для `auto`, по умолчанию `groq,gemini` |
| `ALLUR_LLM_TIMEOUT` | таймаут запроса, с (25) |
| `ALLUR_AI_CACHE_DIR` | папка кэша ответов (по умолчанию `data/ai_cache`) |
