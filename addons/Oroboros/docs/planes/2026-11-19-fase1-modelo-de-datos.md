# Fase 1: modelo de datos, plan de implementación

> **Para quien lo ejecute:** se ejecuta tarea a tarea (superpowers:executing-plans). Pasos con casillas `- [ ]`.

**Objetivo:** que `work/archivo.sqlite` sea la única fuente de verdad de precios: normalizado, con histórico diario para siempre, escaneos en bruto 8 semanas y resúmenes semanales por franja, y que el plan salga de él.

**Arquitectura:** `tools/oroboros_archive.py` es dueño del esquema, la migración, la escritura de escaneos, el histórico diario y el resumen de lo viejo. `tools/oroboros_hours.py` calcula las franjas juntando datos en bruto y resúmenes. `tools/oroboros_export.py` lo orquesta y llena el SQLite del plan desde el archivo.

**Tecnología:** Python 3, solo biblioteca estándar; Lua 5.1 para el único cambio del addon; pruebas en `tests/run_tests.py`.

**Diseño:** `docs/modelo-y-seguimiento.md` (fase 1) y `docs/hoja-de-ruta.md`.

## Restricciones globales

- Retención en bruto: **8 semanas** (`KEEP_DAYS = 56`). La semana en curso no se resume nunca.
- `daily` y `weekly_band` se guardan para siempre. En `weekly_band` se guardan sumas (`gone_total`, `gone_cheap`, `hours`, `n`, `days`, `price_sum`, `price_n`) y además `price_med` de la semana; `week` = semana ISO `AAAA-Www`.
- Prioridad en `daily` para un mismo día: observaciones (`src = 'obs'`) > histórico del juego (`'oro'`) > Auctionator (`'atr'`).
- Auctionator solo entra en `daily`.
- Migración con copia `archivo.sqlite.bak` y versión en `meta` (`schema = 2`).
- `historyDays` del juego pasa de 30 a 14 **solo** en la última tarea, después de migrar los datos reales.

## Foco de revisión

1. Archivo viejo (tabla plana) con datos: la migración conserva todas las filas y el análisis de franjas da lo mismo antes y después.
2. Resumir lo viejo no cambia las franjas: `analyze` da las mismas cifras antes y después de `rollup`.
3. Exportar dos veces seguidas: ni duplica ni resume dos veces.
4. Día con datos de las tres fuentes: gana la observación; si no hay, el histórico del juego; si no, Auctionator.
5. Plan sin `--archive`: igual que hoy.

---

### Tarea 1: esquema nuevo, migración y escritura de escaneos

**Archivos:** `tools/oroboros_archive.py`; `tests/run_tests.py` (adaptar las pruebas de archivo y franjas al esquema nuevo).

**Interfaces:**
- Produce: `open_archive(path: str) -> sqlite3.Connection` (crea o migra el esquema 2); `market_id(con, key: str) -> int`; `insert_scan(con, market: str, t: int, rows: list[tuple], kind: str = "full") -> bool` (filas `(item_id, min, mv, qty, cheap, cheap_prev)`; devuelve False si ya existía); `upsert_items(con, db: dict, seen: dict[int, tuple[int, int]])`; `append_scans(path, db) -> {"added", "already", "scans", "gap"}` (misma salida que hoy).

- [ ] Prueba (falla): `append_scans` dos veces → `added > 0` y luego 0. `observations` guarda `(240, 40, 40)` para 2589. Hay una fila en `markets` y en `items` 2589 con nombre y `first_seen`/`last_seen`. El hueco se detecta como hoy. Migración: un archivo con la tabla plana vieja y 3 filas → tras `open_archive`, 3 observaciones, `meta.schema = '2'` y existe `archivo.sqlite.bak`.
- [ ] Implementar el esquema de `docs/modelo-y-seguimiento.md` (fase 1), con `observations` `WITHOUT ROWID` y `daily.src`. Migrar dentro de una transacción.
- [ ] Adaptar las pruebas de franjas y del plan con franjas para que escriban con `insert_scan`. `oroboros_hours.analyze` se adapta en la tarea 3; hasta entonces, consulta a `observations` unida con `scans` y `markets`.
- [ ] Pruebas en verde; commit.

### Tarea 2: histórico diario

**Archivos:** `tools/oroboros_archive.py`, `tools/auctionator_source.py`.

**Interfaces:**
- Produce: `update_daily(con, db: dict | None = None)`, que recalcula `daily` desde las observaciones de los días tocados y añade el histórico del juego (`db.markets[*].history`) con prioridad. `auctionator_source.to_daily(con, atr: dict, market: str) -> int` mete Auctionator en `daily` como `'atr'` sin pisar `obs` ni `oro`.
- Columnas de `daily` desde observaciones: `min_low` = mínimo del día, `min_high` = máximo de los mínimos, `mv` y `t` = los del último escaneo del día, `qty_max`. Desde el juego: `min_low` = `min_high` = `min`, `mv`, `qty_max` = `qty`, `t`. Desde Auctionator: `min_low` = `l` o `h`, `min_high` = `h`, `mv` = `h`, `qty_max` = `a`.

- [ ] Prueba (falla): el mismo día con las tres fuentes → `src = 'obs'`; sin observación → `'oro'`; solo Auctionator → `'atr'`; un segundo `update_daily` no cambia nada.
- [ ] Implementar; pruebas en verde; commit.

### Tarea 3: resumen semanal y retención de 8 semanas

**Archivos:** `tools/oroboros_archive.py`, `tools/oroboros_hours.py`.

**Interfaces:**
- Produce: `oroboros_hours.contributions(obs_rows) -> iterable[(item_id, week, band, gone_total, gone_cheap, secs, day)]` (la misma regla de hoy: pares seguidos a ≤ 6 h, reparto por tiempo, subida = 0); `oroboros_archive.rollup(con, now: int, keep_days: int = 56) -> int` (escaneos resumidos y borrados); `oroboros_hours.analyze(path, market=None)` con la misma salida que hoy, juntando `weekly_band` y el bruto.
- Regla de corte: se resumen las semanas ISO completas cuyo último día es anterior a `now − keep_days`. Un par cuenta en la semana de su escaneo **inicial**.
- `price_med` de varias semanas = mediana de las medianas semanales; `days` se suman.

- [ ] Prueba (falla): archivo con escaneos de hace 10 semanas y de esta semana → `analyze` antes de `rollup` == `analyze` después (gone/h, n, days, ok; precio con la mediana de medianas, igual en el caso de prueba). Tras `rollup` no quedan observaciones de más de 8 semanas y sí filas en `weekly_band`; `daily` de esos días sigue intacto. Un segundo `rollup` devuelve 0.
- [ ] Implementar; las pruebas de franjas existentes siguen en verde; commit.

### Tarea 4: el exportador usa el archivo para el plan

**Archivos:** `tools/oroboros_export.py`.

**Interfaces:**
- Consume: `open_archive`, `append_scans`, `update_daily`, `to_daily`, `rollup`.
- Con `--archive`: escaneos → `update_daily(con, db)` → Auctionator (si `--auctionator`) con `to_daily` → `rollup` → SQLite del plan. El SQLite del plan toma `history` de `daily` (`min` = `min_low`, `mv`, `qty` = `qty_max`, `src`, `t`) y `prices` de `Oroboros.lua` (trae profundidad). Los objetos sin precio en el juego se completan con su último dato del archivo. Sin `--archive`, todo igual que hoy.

- [ ] Prueba (falla): con los datos sintéticos, el plan exportado con `--archive` propone las mismas oportunidades (nombres y unidades) que sin él; `history` del plan sale de `daily`. La salida de consola resume escaneos, días y semanas resumidas.
- [ ] Implementar; pruebas en verde; commit.

### Tarea 5: datos reales, histórico del juego a 14 días y documentación

- [ ] Exportar los datos reales a `work/archivo.sqlite` con el exportador nuevo (migra el archivo actual y pasa los 30 días del juego y Auctionator a `daily`). Comprobar el número de días por objeto y que el plan sale.
- [ ] Después: `historyDays = 14` en `Oroboros/Core.lua` (`DEFAULTS`).
- [ ] README (archivo y retención), `docs/hoja-de-ruta.md` (fase 1 hecha, con lo aprendido), `docs/arquitectura.md`. Commit.
