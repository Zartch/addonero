# Fase 2: seguimiento de precios (Camel), plan de implementación

> **Para quien lo ejecute:** tarea a tarea (superpowers:executing-plans). Pasos con casillas `- [ ]`.

**Objetivo:** al seleccionar un objeto en la subasta, un panel con su historial resumido al estilo CamelCamelCamel; en la página del plan, el historial completo con rangos; y nombres para todos los objetos.

**Arquitectura:** Python calcula el resumen desde `work/archivo.sqlite` y escribe `Oroboros/Resumen.lua` (una cadena compacta por objeto y mercado). El addon la descomprime solo al mostrar un objeto (`Oroboros/PriceHistory.lua`). La página calcula rangos y cifras en JavaScript a partir del histórico diario que ya lleva el JSON del plan.

**Diseño:** `docs/hoja-de-ruta.md` (fase 2) y `docs/modelo-y-seguimiento.md` (fase 2).

## Restricciones globales

- Precio seguido = **valor de mercado diario** (`daily.mv`) en medias, gráficas, mínimo y máximo. Cobre entero.
- `Resumen.lua`: `OroborosResumen = { v = 1, t = <epoch>, markets = { ["<clave>"] = { [itemID] = "<cadena>" } } }`. Solo objetos con datos en los últimos 90 días. Va en `.gitignore` (`addons/Oroboros/Oroboros/Resumen.lua`), en el TOC el último. Si falta, el addon funciona igual.
- Cadena por objeto (orden fijo, campos separados por `;`, vacío = sin dato): `hoy;med7;med30;med90;min;diaMin;max;diaMax;franjaVenta;franjaBarata;semanas;dias;ultimoDia`. `semanas` son 13 valores y `dias` 14, separados por comas y del más antiguo al más reciente, con vacío si no hay dato. Los días van como `AAAAMMDD`. Las franjas, de 0 a 5, o vacío si no son fiables.
- Interfaz 16001, todo en `ns`. Python solo con biblioteca estándar.

## Foco de revisión

1. Objeto sin resumen, o `Resumen.lua` inexistente: el panel muestra solo el precio de hoy y «sin historial: genera el plan».
2. Personaje de otro mercado (otra facción): busca el apartado de su `ns.MarketKey()`; si no hay, como el punto 1.
3. Cadena con huecos (semanas sin datos): la gráfica salta esas barras sin errores.
4. Muchos objetos sin nombre al acabar un escaneo: se piden poco a poco sin congelar el juego.
5. Nombre con comillas o barras en `Resumen.lua`: el archivo sigue siendo Lua válido (las claves son números y los valores cadenas escapadas).

---

### Tarea 1: el addon pide los nombres que faltan

**Archivos:** `Oroboros/DB.lua`, `Oroboros/Scanner.lua`, `tests/mock_wow.lua`, `tests/run_tests.py`.

**Interfaces:** produce `DB.QueueMissingNames()`, que encola los `items` sin `n`, y el procesado en tandas de 100 por cada `C_Timer.After(0.2)` con `C_Item.RequestLoadItemDataByID`. Al recibir `GET_ITEM_INFO_RECEIVED(itemID, ok)`, llama a `DB.SetItemInfo(itemID)`. Se llama al acabar cada escaneo completo.

- [ ] Prueba (falla): tras un escaneo con 3 objetos sin nombre, la simulación recibe 3 peticiones. Al disparar `GET_ITEM_INFO_RECEIVED` (con `C_Item.GetItemInfo` devolviendo ya el nombre), `items[id].n` queda relleno. Con 250 sin nombre, la primera tanda pide 100.
- [ ] Implementar; pruebas en verde; commit.

### Tarea 2: resumen por objeto y `Resumen.lua`

**Archivos:** crear `tools/oroboros_summary.py`; `tests/run_tests.py`.

**Interfaces:** produce `item_summary(rows: list[(day, mv, min_low, min_high)], bands: list|None, today: date) -> str|None` (la cadena de arriba) y `write_resumen(archive_path: str, out_path: str, today: date|None = None) -> {"items": int, "bytes": int}`. Es ejecutable: `python tools/oroboros_summary.py work/archivo.sqlite [--out RUTA]`; por defecto `Oroboros/Resumen.lua`.

- [ ] Prueba (falla): con histórico diario a mano (valores conocidos), `item_summary` da medias de 7/30/90, mínimo y máximo con su día, 13 semanas (las vacías como hueco) y 14 días exactos. Un objeto sin datos en 90 días da `None`. `write_resumen` produce un archivo que lupa carga y cuya cadena coincide.
- [ ] Implementar (las medias, sobre los días con dato; las semanas ISO, con la media de `mv`; las franjas, de `oroboros_hours.summary`); pruebas en verde; commit.

### Tarea 3: panel en el juego

**Archivos:** crear `Oroboros/PriceHistory.lua`; `Oroboros/Oroboros.toc` (añadir `PriceHistory.lua` y, al final, `Resumen.lua`); `Oroboros/Core.lua` (`/oro precio`); `.gitignore`.

**Interfaces:** `PriceHistory.Parse(s) -> table` (campos con nombre; `weeks` y `days` como listas con `nil` en los huecos); `PriceHistory.Get(itemID) -> table|nil` (busca en `OroborosResumen.markets[ns.MarketKey()]`); `PriceHistory.Lines(itemID, live) -> {string}` (los textos del panel); `PriceHistory.Show(itemID, live)`.

- Panel: 260 × 210, anclado a la derecha de `AuctionHouseFrame` si existe (si no, en el centro), con el estilo de la ventana actual. Se cierra al cerrar la subasta.
  - Título: el nombre del objeto.
  - «Hoy» (en vivo) con su diferencia frente a la media de 30 días.
  - Mínimo y máximo históricos con su fecha `dd/mm`.
  - Medias de 7/30/90 días.
  - 13 barras semanales (texturas) y una fila de 14 puntos diarios.
  - La línea de franjas si existe.
- Se abre con `COMMODITY_SEARCH_RESULTS_UPDATED` / `ITEM_SEARCH_RESULTS_UPDATED` estando la subasta abierta. El precio en vivo es el primer resultado (unidad).

- [ ] Prueba (falla): `Parse` de una cadena con huecos; `Lines` con resumen («Hoy 1s 20c ▼ 12 % frente a 30 días», «Mínimo 95c (12/11)»…); sin resumen, «Sin historial: genera el plan»; un evento de búsqueda con la subasta abierta muestra el panel; `/oro precio 2589` lo muestra; con otro `MarketKey` no encuentra el resumen.
- [ ] Implementar; pruebas en verde; commit.

### Tarea 4: página del plan, historial completo

**Archivos:** `tools/planner_ui.html`.

- Pestaña Mercado:
  - Botones de rango «1 mes · 3 meses · 6 meses · 1 año · Todo» (por defecto, 3 meses).
  - La gráfica muestra el rango elegido.
  - Una tabla con mínimo y máximo del rango y totales (con fecha) y medias de 7/30/90 días.
  - El texto «últimos 14 días» pasa a indicar el rango.

- [ ] Prueba (falla): el HTML generado contiene los cinco rangos y la tabla de cifras.
- [ ] Implementar; pruebas en verde; commit.

### Tarea 5: integración, datos reales y documentación

- [ ] Exportador: con `--archive`, al acabar también escribe `Resumen.lua` (con `--resumen RUTA` para cambiar el destino y `--resumen no` para no escribirlo). Prueba: el exportador con archivo deja `Resumen.lua` válido.
- [ ] Datos reales: exportar, medir el tamaño de `Resumen.lua` (objetivo ≤ 1 MB) y generar el plan.
- [ ] README (panel, `/oro precio`, pestaña Mercado), hoja de ruta (fase 2 hecha, con lo aprendido) y lista de comprobaciones en el juego para el usuario (falta de `Resumen.lua`, panel con Auctionator). Commit.
