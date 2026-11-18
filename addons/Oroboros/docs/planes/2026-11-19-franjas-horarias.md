# Franjas horarias: plan de implementación

> **Para quien lo ejecute:** se ejecuta tarea a tarea (superpowers:executing-plans). Pasos con casillas `- [ ]`.

**Objetivo:** que ningún escaneo completo se pierda y que el plan diga, por objeto, en qué franja horaria desaparece más (total y barato) y cuándo está más barato.

**Arquitectura:** el addon guarda los últimos 12 escaneos como cadenas compactas en `OroborosDB.markets[mk].scans`; el exportador (`--archive`) los añade a un SQLite permanente; `tools/oroboros_hours.py` analiza ese archivo por franjas y el planificador (`--archive`) lo usa en textos y en una pestaña «Horas».

**Tecnología:** Lua 5.1 (addon), Python 3 solo con biblioteca estándar, pruebas con lupa en `tests/run_tests.py`.

**Diseño:** `docs/franjas-horarias.md` (aprobado el 18/11/2026).

## Restricciones globales

- Buffer: 12 escaneos (`SCAN_BUFFER = 12`). Franjas: 6 de 4 h en hora local (0–4 … 20–24). Intervalo máximo entre escaneos para medir: 6 h. Fiabilidad: ≥ 3 mediciones en ≥ 2 días por franja.
- Barato = a ≤ mínimo × 1,25.
- Formato de un escaneo: `{ t = <epoch>, data = "id,min,mv,qty,b,bp;..." }`; `min`/`mv` vacíos si el objeto desapareció del todo.
- Textos en español. El addon no escribe archivos ni tiene red. Sin dependencias nuevas en Python.
- `work/archivo.sqlite` nunca se borra ni se sube a git.

## Foco de revisión

1. Objeto que se agota entre dos escaneos: debe contar como desaparecido entero (`qty` 0 en el escaneo nuevo), no ignorarse.
2. Primer escaneo de un objeto (sin escaneo anterior): `bp` usa el umbral del propio escaneo; no rompe ni inventa bajadas.
3. Escaneos separados más de 6 h, o un hueco por pasar de 12 sin exportar: ese intervalo no mide nada y el exportador avisa del hueco.
4. Exportar dos veces el mismo `Oroboros.lua`: el archivo no duplica filas.
5. Plan sin `--archive`, o con archivo sin datos fiables: el plan sale igual que hoy, sin textos de franja.

---

### Tarea 1: buffer de escaneos en el addon

**Archivos:** modificar `Oroboros/DB.lua` (`DB.RecordPrices`, nuevo `DB.ScanCount`, `DB.PrintStats`), `Oroboros/UI.lua` (`UI.UpdateFooter`). Pruebas en `tests/run_tests.py`.

**Interfaces:**
- Produce: `OroborosDB.markets[mk].scans`, una lista de `{t=number, data=string}` con como mucho 12 entradas, la más antigua primero. `DB.ScanCount(mk) -> n, SCAN_BUFFER`.

- [ ] Prueba (falla): tras el escaneo completo de la simulación, `scans` tiene 1 entrada. La línea del lino (2589) es `"2589,30,32,240,40,40"`: listados de 30×20, 35×20 y 50×200; barato = ≤ 37,5, o sea 40 unidades; `bp` = 40 porque no hay precio previo. 14 escaneos dejan 12. En un escaneo en el que 2589 no aparece, su entrada es `"2589,,,0,0,0"`. Si sube el mínimo (escaneo con solo 35×20 y 50×200, con el anterior a 30), `b` = 20 (≤ 43,75) y `bp` = 20 (≤ 37,5).
- [ ] Implementar en `DB.RecordPrices(byItem, full, mk)`: solo con `full`, antes de sobrescribir `m.prices[id]`, calcular `bp` con el `min` previo × 1,25 sobre `listings`. `b` es `depth[2]`. Añadir los objetos de `m.prices` que no vienen en el escaneo con qty 0. Unir con `table.concat`. Recortar a 12.
- [ ] `/oro stats` y el pie de la ventana muestran «escaneos guardados: N/12»; con 12, «exporta antes del siguiente escaneo».
- [ ] Pruebas en verde; commit.

### Tarea 2: archivo permanente en el exportador

**Archivos:** crear `tools/oroboros_archive.py`; modificar `tools/oroboros_export.py` (opción `--archive RUTA`).

**Interfaces:**
- Produce: `append_scans(archive_path: str, db: dict) -> dict` con `{"added": int, "already": int, "gap": bool}`. Tabla `scans(market TEXT, t INTEGER, item_id INTEGER, min REAL, mv REAL, qty INTEGER, cheap INTEGER, cheap_prev INTEGER, PRIMARY KEY(market, t, item_id))`.

- [ ] Prueba (falla): exportar dos veces el `Oroboros.lua` de prueba con `--archive` → la segunda vez `added == 0`. Si el escaneo más antiguo del buffer es posterior al último archivado y el buffer está lleno (12), `gap == True` y la salida dice «se han perdido escaneos».
- [ ] Implementar con `INSERT OR IGNORE`; un hueco es posible solo con el buffer lleno y sin solape con lo ya archivado. Imprimir un resumen.
- [ ] Pruebas en verde; commit.

### Tarea 3: análisis por franjas

**Archivos:** crear `tools/oroboros_hours.py` (también ejecutable: `python tools/oroboros_hours.py work/archivo.sqlite [--item ID]`).

**Interfaces:**
- Produce: `BANDS = [(0,4),(4,8),(8,12),(12,16),(16,20),(20,24)]`; `analyze(archive_path: str, market: str|None) -> dict[int, list[dict]]`, que por objeto da 6 dicts `{"band": i, "gone_total_h": float|None, "gone_cheap_h": float|None, "price_med": float|None, "n": int, "days": int, "ok": bool}`; `summary(bands) -> dict|None`, con `{"sell_band", "sell_rate", "avg_rate", "cheap_band", "cheap_pct", "cheap_share"}` o `None` si no hay franjas `ok`.

- [ ] Prueba (falla) con un caso calculado a mano: escaneos a las 10:00 y 14:00 del mismo día. qty 100→60 y cheap 30, cheap_prev 10 → total 40 en 4 h, partido a medias entre las franjas 8–12 y 12–16 (20 cada una, 10/h); barato 20 → 5/h en cada franja. Un intervalo de 7 h no cuenta. Si qty sube, cuenta 0. Con 3 mediciones en un solo día la franja no es `ok`; con 3 en 2 días sí.
- [ ] Implementar: recorrer los pares consecutivos por objeto; repartir por minutos solapados con cada franja (los intervalos que cruzan la medianoche se parten bien); `n` es el número de intervalos que tocan la franja, `days` los días distintos. El precio, mediana del `min` de los escaneos cuya hora cae en la franja. Mercado: el que se pase, o el que tenga más filas.
- [ ] Pruebas en verde; commit.

### Tarea 4: el plan usa las franjas

**Archivos:** modificar `tools/oroboros_plan.py` (opción `--archive`, textos en `evaluate`/`find_flips`/compras, `items[...]["hours"]`) y `tools/planner_ui.html` (pestaña «Horas»).

**Interfaces:**
- Consume: `oroboros_hours.analyze`, `oroboros_hours.summary`.
- Produce: `Data.hours: dict[int, list[dict]]` (vacío sin `--archive`); en el JSON del plan, `items[id]["hours"]` con las 6 franjas.

- [ ] Prueba (falla): con un archivo sintético en el que el objeto vendido desaparece sobre todo de 20 a 24, el `why` de su oportunidad contiene «de 20 a 24 h»; sin `--archive`, ningún `why` contiene «h (≈». El HTML contiene la pestaña «Horas».
- [ ] Implementar. Venta: «Desaparece sobre todo de A a B h (≈X/h barato, frente a Y/h de media): publica antes de esa franja.» Compra (reactivos de la ruta): «Suele estar más barato de A a B h (−P % frente a la media).» Solo si la diferencia es ≥ 10 %. Pestaña con una fila por objeto del plan y de tus recetas, y celdas coloreadas por `gone_cheap_h`, con el precio debajo.
- [ ] Pruebas en verde; commit.

### Tarea 5: documentación y prueba con datos reales

- [ ] README: comandos `--archive`, `oroboros_hours.py`, «escaneos guardados» y la pestaña Horas. Diseño: estado «implementado».
- [ ] Exportar los datos reales a `work/` con `--archive` y comprobar que el plan sale (la franja dirá «sin datos» hasta tener días). Commit.

**Decisión del constructor:** el análisis se calcula al generar el plan, leyendo el archivo, en vez de guardar una tabla `hours` en el SQLite del plan. Así nunca está desfasado.
