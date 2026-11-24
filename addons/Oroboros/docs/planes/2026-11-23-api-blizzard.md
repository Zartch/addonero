# API de Blizzard y panel de escritorio: plan de implementación

> **Para quien lo ejecute:** tarea a tarea (superpowers:executing-plans). Pasos con casillas `- [ ]`.

**Objetivo:** leer la subasta de Forever cada hora con la API oficial de Blizzard, sin entrar al juego. Usarla para el seguimiento de precios y para estimar ventas. Y verlo todo en un panel de escritorio que se queda abierto (precios, ventas estimadas frente a reales, inventario, libro y plan).

**Diseño:** `docs/api-subasta-blizzard.md`. El apartado 0 es lo comprobado el 23/11: casa 111, una foto por hora hacia el minuto 23, `If-Modified-Since`, campos reales y tamaños.

## Decisiones

### Qué casas

- Por defecto, el grupo de nuestra casa: **111** (Alianza), **114** (Horda) y **117** (Aguasnegras). Se configura con `--casas 111,114,117`.
- Cada casa se asocia a una clave de mercado del archivo, para que el resto de herramientas la traten como un mercado más:
  - 111 → `CAMWOWEU5Realm5PvE-Alliance` (el mismo `market_id` que los escaneos del juego);
  - 114 → `CAMWOWEU5Realm5PvE-Horde`;
  - 117 → `CAMWOWEU5Realm5PvE-Neutral`.
- La asociación se guarda en la tabla `api_houses`. Que la 114 y la 117 sean de nuestro reino está sin comprobar (apartado 0): si un escaneo de la Horda dice otra cosa, se cambia una fila.

### Tablas nuevas en `work/archivo.sqlite`, separadas de los escaneos del juego

| Tabla | Qué guarda | Cuánto tiempo | Tamaño |
|---|---|---|---|
| `api_houses` | casa, nombre, facción, `market_id` | siempre | nada |
| `api_snaps` | una fila por foto: casa, `t` (de `last-modified`), subastas, unidades, objetos | siempre | ~26 000 filas al año |
| `api_live` | **solo la última foto** de cada casa, por subasta: `id`, objeto, cantidad, precio unitario, `time_left` y hora en que se vio por primera vez. Se sustituye cada hora | solo la última | ~330 000 filas, ~15 MB fijos |
| `api_item_hour` | por casa, foto y objeto: mínimo, valor de mercado (media del 15 % más barato, como el juego), unidades publicadas, subastas, y unidades **nuevas, vendidas, caducadas, canceladas y compradas en parte** desde la foto anterior | **14 días** | ~16 800 filas por hora; ~18 MB al día, **~250 MB fijos** |
| `api_band_week` | resumen permanente por casa, objeto, semana ISO y franja de 4 h: las mismas unidades sumadas, horas medidas, días y mediana de precio | siempre | ~126 000 filas por semana; **~20 MB al mes** |
| `daily` (ya existe) | una fila por mercado, objeto y día con origen `src = 'api'` | siempre | ~17 000 filas al día; **~20 MB al mes** |

**No se guarda en bruto** ni una foto ni un evento por subasta: serían unas 290 000 subastas por foto y unos 3,5 millones de altas y bajas al día. Se guarda la última foto (para comparar con la siguiente) y lo resumido por objeto.

**Total:** unos 265 MB fijos (`api_live` y 14 días de `api_item_hour`) más unos **40 MB al mes** de resúmenes permanentes. Pasado el primer mes, el archivo crece unos 40 MB al mes, sin límite pero de forma lenta y predecible. Si un día molesta, se pueden borrar semanas viejas de `api_band_week`, que es el 50 %.

Los 14 días de `api_item_hour` son lo que se pierde si cambia la regla de clasificación. Con 14 días se puede recalcular dos semanas. Si quieres más, cada semana adicional son ~125 MB más.

### Cada hora

1. Token (caché en `work/api/token.json`, renovado si le quedan menos de 5 min).
2. Por cada casa, `GET` normales y materiales con `If-Modified-Since` = su último `last-modified`. Si da 304, no se hace nada.
3. Si hay foto nueva, se compara con `api_live` y se sustituye. En una transacción se escriben `api_item_hour`, `api_snaps` y `daily`.
4. Se pregunta pasado el minuto 25. Si la casa da 304, se reintenta cada 5 min hasta el minuto 55.
5. Si falta una foto (hueco de más de 90 min entre la nueva y la anterior), las desaparecidas en el hueco **no se clasifican**: solo se apuntan como `hueco`. El informe avisa de que con un hueco todo se mezcla.
6. Una vez al día: borrar `api_item_hour` de más de 14 días (resumiéndolo antes en `api_band_week`) y pedir los nombres que falten a la ruta de objetos (`static-forever-eu`), como mucho 2000 por día.

### Estimación de ventas (apartado 4a del informe)

Por cada `id` de la foto anterior:

- **Desaparece:**
  - si le quedaba `SHORT` → **caducada**;
  - si no, y su precio unitario era mayor que mínimo del objeto × 1,25 en la foto anterior (el mismo «barato» que `oroboros_hours`) → **cancelada**;
  - si no → **vendida**.
  - Se suman sus unidades.
- **Sigue pero con menos cantidad:** la diferencia es **compra parcial**, que cuenta como vendida.
- **Es nueva:** sus unidades son **nuevas**.

Resultado: unidades por objeto, casa y foto (`api_item_hour`), por franja y semana (`api_band_week`) y por día (`daily` no las lleva; se calculan de `api_item_hour` o `api_band_week`).

**Comparación con tus ventas reales** (el libro del correo, `ledger` con `op = 'SELL'`, en `oroboros.sqlite`). Por cada venta tuya en la Alianza se busca en `api_item_hour` de la 111 el intervalo entre fotos que la contiene (con ±1 h de margen, porque la hora del correo no es exacta) y se mira cómo se clasificó ese objeto:

- **Cobertura**: tus unidades vendidas que la estimación ve como vendidas en ese intervalo. Debería ser casi el 100 %.
- **Proporción**: de lo vendido estimado del objeto, cuánto fuiste tú.

Sale en el panel (pestaña Ventas) y con `oroboros_api.py --calibrar`. No se corrige nada automáticamente: con datos suficientes se decide si hace falta cambiar el umbral de cancelada.

**Ojo:** las cifras de la fase A son muy altas («vendidas» ~15 000 subastas normales por hora en la 111), y seguramente incluyen recolocaciones. Por eso se calibra antes de que el plan se fíe de ellas. Hasta que haya **3 días** de API y la calibración dé una cobertura del 80 % o más, el plan marca las ventas de la API como estimadas, con confianza baja.

### Quién gana cuando hay dato del juego y de la API

| Dónde | Regla |
|---|---|
| `daily` (precio del día) | **Gana la API** (`src = 'api'`): 24 fotos al día de toda la subasta. El escaneo del juego (`obs`) solo cuenta los días sin API. Orden: `api` > `obs` > `oro` > `atr` |
| Precio «de ahora» del plan (`prices`) | **El más reciente**. Si la última foto de la API es posterior al último escaneo, el plan usa su mínimo, valor de mercado, cantidad y profundidad (que la API sí tiene) |
| Ventas por día (`stats()["vol"]`) | Con 3 días o más de API, **la API**: media diaria de vendidas, incluidas las compras parciales. Sin ellos, como hoy (`daily_drops`) |
| Franjas (`oroboros_hours.analyze`) | Por objeto y franja, si la API tiene al menos 3 mediciones en 2 días, **la API** (vendidas por hora y mediana de precio). Si no, los escaneos como hoy. Se marca de dónde sale (`src`) |

### `oroboros_summary.py` y `Resumen.lua`

- Salen solos con la API, porque `daily` y las franjas ya la traen. Además habrá un apartado por mercado de Horda y de Aguasnegras si se descargan.
- Se añade un campo al final de la cadena de cada objeto: **vendidas por día** (media de 7 días de la API, vacío si no hay). El panel del juego lo enseña debajo del precio («≈ 42 vendidas/día»). Cambia poco en `PriceHistory.lua`, que ya ignora los campos que no conoce; hay que comprobar que no rompe con un `Resumen.lua` antiguo.

### El panel de escritorio (`tools/oroboros_panel.py`)

Un solo programa (Python estándar) que:

1. **Descarga cada hora** con el bucle de arriba, en un hilo. Después regenera `Resumen.lua` y, si hay `Oroboros.lua`, el plan (como el vigilante).
2. **Sirve una página local** en `http://127.0.0.1:8737` (solo en tu PC, nunca en la red).
3. **Abre una ventana** con Edge en modo aplicación (`msedge --app=…`): ventana propia sin barra de direcciones. Si no hay Edge, el navegador por defecto.
4. **Una sola copia**, con un mutex de Windows como el lanzador. Abrirlo otra vez solo abre la ventana. Cerrar la ventana **no** para la descarga; se para con el botón «Parar» del panel.

La página es la del plan (`planner_ui.html`) con **dos pestañas nuevas**, que piden los datos al programa (`fetch`) en vez de llevarlos incrustados:

- **Subasta**: estado (última foto de cada casa, próxima descarga, errores) y buscador de objetos. Por objeto:
  - precio en las tres casas;
  - gráfica de precio por hora (14 días) y por día (todo);
  - vendidas, caducadas y canceladas por franja;
  - y, si lo tienes, cuántos tienes y dónde.
- **Ventas**: lo más vendido (estimado) por día; comparación con tus ventas del libro (cobertura y tus ventas encima de la estimación).

Las pestañas que ya existen (Resumen, Ruta, Recetas, Aprender, Ideas, Cartera con el libro, Inventario, Horas, Mercado y Farmear) se ven igual, con el plan más reciente. `plan.html` abierto como archivo sigue funcionando; las dos pestañas nuevas dicen entonces «abre el panel».

Rutas del servidor (JSON, solo lectura salvo «parar» y «descargar ahora»):

- `GET /` → la página con el plan incrustado;
- `GET /api/estado`;
- `GET /api/buscar?q=`;
- `GET /api/objeto/{id}`;
- `GET /api/ventas?dias=7`;
- `GET /api/calibrar`;
- `POST /api/descargar`;
- `POST /api/parar`.

### Cómo se lanza

- **El panel hace el bucle de cada hora**: no hace falta otra tarea.
- En el README se documenta (no se crea) una tarea de Windows **al iniciar sesión** que arranca el panel con `pythonw.exe` (sin consola) y `--sin-ventana`, y un acceso directo «Oroboros» para abrir la ventana.
- `oroboros_api.py --una-vez` descarga una vez y sale, para quien prefiera la tarea programada cada hora sin panel.
- El vigilante y el lanzador no cambian. Si el panel está abierto, el lanzador no hace falta para el plan, pero se puede seguir usando.

## Restricciones globales

- La API solo lee. Nada actúa en el juego.
- Python solo con biblioteca estándar. La página, sin bibliotecas externas (como hoy).
- Credenciales en `BNET_CLIENT_ID` y `BNET_CLIENT_SECRET` o en `work/bnet.env`. Nunca en git, nunca en la salida ni en los registros. El token, en `work/api/`.
- El servidor escucha **solo en 127.0.0.1**.
- No se suben datos reales: fotos, `work/`, `Resumen.lua`.
- Las pruebas no usan la red: fotos sintéticas pequeñas y un `fetch` falso.

## Foco de revisión

1. Clasificación: `SHORT` → caducada antes que nada; compra parcial dentro del mismo `id`; una subasta que sube de cantidad (no debería pasar) no cuenta.
2. Hueco de más de 90 min: no clasifica.
3. 304 no toca nada; un error de red o un 5xx se registra y se reintenta, sin romper el bucle.
4. Retención: lo que se borra de `api_item_hour` está antes en `api_band_week`, y las franjas dan lo mismo antes y después (como la prueba de la fase 1).
5. Credenciales: ninguna salida, registro ni excepción las muestra.
6. Prioridad en `daily`: un día con API no se pisa con un escaneo del juego, y al revés sí.

---

### Tarea 1: descarga y tablas (`tools/oroboros_api.py`)

**Archivos:** crear `tools/oroboros_api.py`; `tests/run_tests.py`.

**Interfaces:**
- `load_creds(work_dir) -> (id, secreto)` y `Client(creds, opener=urllib.request.urlopen, clock=time.time)`. Con `.token()` y `.get(ruta, ims=None) -> (status, last_modified, dict | None)`.
- `open_api(con)`: crea las tablas `api_*` si no existen.
- `ingest(con, house, t, auctions) -> dict`: compara con `api_live`, escribe `api_item_hour`, `api_snaps` y `daily`, y sustituye `api_live`. Devuelve los recuentos.
- `classify(prev, cur, mins) -> {item: {new, sold, expired, cancelled, partial}}`: pura, para probarla sola.
- `run_once(archive, client, houses) -> [resultado por casa]`.
- Ejecutable: `python tools/oroboros_api.py [--casas 111,114,117] [--una-vez] [--work work]`.

- [ ] Prueba (falla), con fotos sintéticas de 3 o 4 subastas:
  - primera foto: todo «nuevo»;
  - segunda: una `SHORT` desaparece → caducada; una cara → cancelada; una barata → vendida; un material baja de 20 a 15 → 5 parciales;
  - 304 no cambia nada;
  - hueco de 3 h → sin clasificar;
  - `daily` con `src = 'api'` no se pisa con `update_daily` del juego;
  - el cliente nunca pone el secreto en una excepción ni en el registro.
- [ ] Implementar; pruebas en verde; commit.

### Tarea 2: retención y nombres

**Archivos:** `tools/oroboros_api.py`; `tests/run_tests.py`.

- `rollup_api(con, now, keep_days=14)`: resume en `api_band_week` y borra.
- `fill_names(con, client, limit=2000)`: pide a la ruta de objetos los que no tengan nombre y rellena `items` (`name`, `quality`, `vendor_sell`).

- [ ] Prueba (falla): tras el resumen, las franjas de la API dan lo mismo; `fill_names` con un cliente falso rellena y respeta el límite.
- [ ] Implementar; pruebas en verde; commit.

### Tarea 3: el plan, las franjas y `Resumen.lua` usan la API

**Archivos:** `tools/oroboros_hours.py`, `tools/oroboros_plan.py`, `tools/oroboros_archive.py` (`plan_from_archive`: precio de la API si es más reciente), `tools/oroboros_summary.py`, `Oroboros/PriceHistory.lua`, `tests/run_tests.py`.

- [ ] Prueba (falla):
  - con API y escaneos, las franjas salen de la API donde hay datos suficientes (y lo dicen) y de los escaneos donde no;
  - `stats()["vol"]` usa las vendidas de la API con 3 días;
  - el precio de ahora es el más reciente;
  - `Resumen.lua` lleva el campo de vendidas/día;
  - el panel del juego lo enseña y no falla con un resumen sin ese campo.
- [ ] Implementar; pruebas en verde; commit.

### Tarea 4: calibración con el libro

**Archivos:** `tools/oroboros_api.py` (`calibrate(archive, plan_db, house=111) -> dict`, `--calibrar`); `tests/run_tests.py`.

- [ ] Prueba (falla): una venta del libro dentro de un intervalo con vendidas → cubierta; una venta en un intervalo donde el objeto salió como cancelado → no cubierta; el informe da la cobertura y la proporción.
- [ ] Implementar; pruebas en verde; commit.

### Tarea 5: el panel

**Archivos:** crear `tools/oroboros_panel.py`; `tools/planner_ui.html` (pestañas Subasta y Ventas); `tests/run_tests.py`.

**Interfaces:**
- `make_server(archive, work_dir, port=8737) -> ThreadingHTTPServer`, solo en 127.0.0.1;
- `Scheduler(run, clock, sleep)`: decide cuándo descargar (minuto 25, reintentos);
- `open_window(url)`: Edge en modo aplicación, o el navegador por defecto.
- Ejecutable: `pythonw tools/oroboros_panel.py [--sin-ventana] [--casas …] [--find "<WoW>"]`.

- [ ] Prueba (falla), sin red y con un archivo sintético:
  - las rutas JSON responden con lo esperado (estado, buscar, objeto, ventas y calibrar);
  - el planificador pide a :25 y reintenta tras un 304;
  - `POST /api/parar` cierra el servidor;
  - la página sirve el plan incrustado y las pestañas nuevas existen.
- [ ] Implementar; pruebas en verde; commit.
- [ ] Probarlo de verdad en tu PC: abrir el panel, esperar a una descarga y mirar las pestañas.

### Tarea 6: documentación

- [ ] README:
  - credenciales;
  - `oroboros_api.py`;
  - el panel: abrirlo, acceso directo y tarea al iniciar sesión documentada sin crearla;
  - cuánto ocupa.
- [ ] `CLAUDE.md`: herramientas nuevas y estado.
- [ ] `docs/hoja-de-ruta.md`: la API sale de «Ideas para después» y entra como hecha, con lo aprendido.
- [ ] `docs/api-subasta-blizzard.md`: qué se construyó y la calibración con los primeros días.
- [ ] Commit.

## Fuera de este plan (para después)

- Apagar el escaneo automático en el juego cuando hay foto de la API reciente (`/oro set autoscan`).
- Comparar precios entre facciones y avisar de diferencias (arbitraje con Aguasnegras).
- Alertas de precio desde el panel.
