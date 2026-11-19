# Modelo de datos, seguimiento de precios y automatización

Diseño del 19/11/2026. Estado: **aceptado como base el 19/11**; cada fase se planifica al empezarla. Resumen y estado de las fases en `docs/hoja-de-ruta.md`. Sustituye y amplía, para el almacenamiento, a `docs/franjas-horarias.md` (implementado el 19/11).

## Para qué

El usuario quiere tres cosas, que dependen unas de otras:

1. **Un modelo de datos sin repeticiones**: cada producto una vez, los escaneos relacionados con los productos, y lo viejo resumido para que nada crezca sin límite.
2. **Seguimiento de precios al estilo CamelCamelCamel**: historial de cada objeto con mínimos, máximos, medias y gráfica. En la página del plan, completo. En el juego, al seleccionar un objeto en la subasta, un panel con un resumen, como hace la extensión de Camel en Amazon.
3. **Menos trabajo manual**: que el escaneo y el procesado fuera del juego ocurran solos, en lo que se pueda sin botting.

Y sobre todo eso, **cálculos más ricos**: aprovechar todos los escaneos aunque estén separados muchas horas (unos días se escanea varias veces y otros dos), día de la semana, caducadas, velocidad de rebaja y relación entre precio y ventas.

## Situación de partida (medida el 19/11 con datos reales)

| Dónde | Qué | Problema |
|---|---|---|
| `Oroboros.lua` (2,7 MB) | `items` 346 KB, `prices` 827 KB, `history` 1160 KB (30 días), `scans` 328 KB (12 escaneos) | El último escaneo está tres veces (`prices`, fila de hoy de `history`, `scans`). `history` es lo más grande y no lo usa ninguna función del addon: solo el exportador |
| `work/oroboros.sqlite` | Copia de trabajo para el plan, se rehace en cada exportación | Ninguno (es desechable) |
| `work/archivo.sqlite` | Tabla plana `scans(market, t, item_id, …)` | Nombre de mercado repetido en cada fila; sin tablas de escaneos ni de productos; crecería ~10 M filas al año sin resumir nada |

Medido entre dos escaneos separados 10 h: **el 99 % de los productos cambia en algo** (el 5 % mantiene la cantidad). Guardar solo los cambios no ahorra; lo que ahorra es no repetir lo fijo y resumir lo viejo.

## Objetivos

- Archivo SQLite **normalizado y única fuente de verdad** de precios. El SQLite del plan se genera a partir de él.
- Escaneos en bruto durante **8 semanas** (decisión del usuario); después, resumidos por día y por semana × franja, y borrados.
- Historial diario por objeto **para siempre**, en el archivo.
- Panel en el juego con el resumen al estilo Camel y gráfica de 13 semanas, servido desde un archivo de datos generado fuera, sin engordar `Oroboros.lua`.
- Página del plan con el historial completo y rangos (1 mes, 3 meses, 6 meses, 1 año, todo).
- Escaneo automático al abrir la subasta y procesado automático fuera del juego.
- Franjas calculadas con todos los intervalos, también los largos.

## Fuera de alcance

- Alertas de precio («avísame si baja de X»). Es la otra mitad de Camel; queda como idea para después.
- Cualquier cosa que actúe en el juego sin ti: abrir la subasta, mover al personaje, comprar o publicar. Es botting.
- Precios de otros servidores o regiones.

## Lo que sería un fracaso

- Que el juego tarde más en cargar o en hacer `/reload` que hoy.
- Perder datos en bruto antes de resumirlos (por ejemplo, borrar escaneos sin haberlos pasado a `daily` y `weekly_band`).
- Que la migración rompa el plan o pierda el histórico que ya hay (Auctionator, días de Oroboros y los escaneos ya archivados).
- Subir a git datos reales (`work/`, el archivo de resumen generado).

## Restricciones

- Addon: Lua 5.1, interfaz 16001, todo en la tabla privada `ns`, sin red ni escritura de archivos; solo SavedVariables, que se escriben con `/reload` o al salir. Acciones protegidas, siempre de un clic.
- Python: solo biblioteca estándar.
- Windows es el sistema del usuario.
- Pruebas fuera del juego en `tests/run_tests.py`, en verde antes de cada commit.
- El addon está enlazado (unión) a la carpeta del repositorio: lo que se genere dentro de `Oroboros/` aparece en el repo y hay que ignorarlo en git.

## Enfoques considerados

**Almacenamiento**

| Enfoque | Decisión |
|---|---|
| Tabla plana (la actual) | Descartado: repite el mercado en cada fila, no relaciona productos y crece sin límite |
| Guardar solo lo que cambia entre escaneos | Descartado: medido, el 99 % cambia entre escaneos |
| **Tablas relacionadas + resumen de lo viejo (8 semanas en bruto)** | **Elegido** |

**Cómo llega el resumen al juego**

| Enfoque | Decisión |
|---|---|
| Más histórico en `Oroboros.lua` | Descartado: ~10 MB para 90 días; el juego lo carga y lo reescribe al salir |
| Calcularlo dentro del juego | Descartado: duplicaría en Lua los cálculos de Python y solo tendría lo que el addon ha visto |
| **Archivo de datos generado fuera y cargado por el addon** (como la aplicación de escritorio de TradeSkillMaster) | **Elegido**: ~0,7 MB, solo lectura, un único sitio de cálculo |

**Cuánta historia en el juego**: elegido el **resumen**, unas 25 cifras por objeto, frente a historial diario de varios meses.

## Diseño por fases

Cada fase se puede usar sola y deja las pruebas en verde.

### Fase 1: modelo de datos

**Archivo `work/archivo.sqlite`**, nuevo esquema:

```
markets      (market_id INTEGER PK, key TEXT UNIQUE)
items        (item_id PK, name, quality, stack, commodity, ilvl, vendor_sell, vendor_buy,
              first_seen, last_seen)                                   -- un producto, una fila
scans        (scan_id INTEGER PK, market_id, t, kind TEXT, n_items,    -- kind: 'full' | 'partial'
              UNIQUE(market_id, t))
observations (scan_id, item_id, min, mv, qty, cheap, cheap_prev,
              PRIMARY KEY (scan_id, item_id)) WITHOUT ROWID             -- solo números
daily        (market_id, item_id, day, min_low, min_high, mv, qty_max, src,
              PRIMARY KEY (market_id, item_id, day))                    -- para siempre
weekly_band  (market_id, item_id, week, band, gone_total, gone_cheap, hours, n, days,
              price_med, price_sum, price_n,
              PRIMARY KEY (market_id, item_id, week, band))             -- para siempre
meta         (key PK, value)                                            -- versión del esquema, etc.
```

- **Sumas, no medias**, en `weekly_band` (`gone_*`, `hours`, `n`, `days`, `price_sum`/`price_n`): así se pueden juntar semanas resumidas con datos en bruto recientes y la media sale exacta. `days` son los días distintos con medición en esa semana y franja; como cada semana tiene días distintos, se suman y se sigue pudiendo exigir «≥ 3 mediciones en ≥ 2 días». `price_med` es la mediana de la semana; varias semanas se combinan por la mediana de sus medianas (aproximación aceptada). `week` es la semana ISO, `AAAA-Www`.
- Lo que alimenta `weekly_band` es lo mismo que hoy: escaneos seguidos a ≤ 6 h, repartidos por tiempo entre franjas. La fase 4.1 trabaja solo sobre las 8 semanas en bruto (sus ecuaciones necesitan intervalos enteros) y no cambia este esquema.
- **`daily`** se alimenta de tres fuentes, por este orden de preferencia: observaciones del archivo (`oro`), histórico diario del juego (`oro`, para días anteriores al archivo) y Auctionator (`atr`). Para un mismo día gana la primera que exista. **Auctionator solo entra en `daily`**: su base fuera del juego da un precio y una cantidad por día, sin baratas. Cuando Oroboros lee en el juego el escaneo completo de Auctionator, es un escaneo normal (`scans`).
- **Resumen de lo viejo**: al exportar, las observaciones de más de 8 semanas ya incluidas en `daily` y `weekly_band` se borran. Los totales de la semana se cierran antes de borrar. La semana en curso nunca se borra.
- **Migración**: si existe la tabla plana anterior, se convierte al esquema nuevo dentro de una transacción y se deja una copia `archivo.sqlite.bak`. Se registra la versión en `meta`.
- **Exportador**: `--archive` escribe en el esquema nuevo y mantiene `items` (alta y actualización de nombre, `first_seen`/`last_seen`). El SQLite del plan toma `prices` (última observación por objeto) e `history` (de `daily`) **del archivo**; el estado de los personajes (inventario, recetas, libro…) sigue saliendo de `Oroboros.lua`. Sin `--archive` todo funciona como hoy.
- **Franjas** (`oroboros_hours.py`): leen las observaciones de las 8 semanas más `weekly_band` para lo anterior, con las mismas cifras que hoy.
- **En el juego**: `historyDays` por defecto pasa de 30 a **14** días (lo justo para no perder días si no se exporta en un tiempo). `scans` se queda en 12. **Orden obligatorio**: este cambio es el último paso de la fase 1 y se aplica solo después de exportar los datos reales del usuario con el exportador nuevo, que pasa los 30 días actuales a `daily`; si no, se perderían.

### Fase 2: seguimiento de precios (Camel)

**Resumen por objeto** (`tools/oroboros_summary.py`), calculado desde `daily`, las observaciones y las franjas:

- hoy, media de 7/30/90 días y diferencia de hoy frente a la de 30 días;
- mínimo y máximo históricos, con su fecha;
- 13 puntos semanales (media del valor de mercado de cada semana) y 14 puntos diarios;
- mejor franja para vender y franja más barata, si son fiables.

**Archivo de datos para el juego**: `Oroboros/Resumen.lua`, con una tabla global `OroborosResumen = { v = 1, t = <generado>, markets = { ["<clave>"] = { [id] = "<cadena compacta>" } } }`. Un apartado por mercado (hoy la clave lleva la facción): el panel busca el de `ns.MarketKey()` del personaje que juega.

- Una cadena por objeto, que se descomprime solo al seleccionarlo; así carga rápido.
- Solo lleva objetos con actividad en los últimos 90 días.
- Se genera con números y cadenas escapadas: nunca se escribe en él texto sin escapar.
- Va en `.gitignore`.
- El TOC lo carga después de los archivos del addon. **Si no existe**, el addon funciona igual y el panel dice «sin resumen: genera el plan».

**Panel en el juego** (`Oroboros/PriceHistory.lua`, nuevo):

- Se abre al seleccionar un objeto en la subasta, aprovechando la búsqueda que lanza el propio juego (`COMMODITY_SEARCH_RESULTS_UPDATED` / `ITEM_SEARCH_RESULTS_UPDATED`, que ya escucha `Scanner`). Va anclado al lado derecho de la ventana de subasta. También con `/oro precio <objeto>`.
- Muestra el precio de hoy en vivo (de esa búsqueda), las cifras del resumen y la gráfica (13 barras semanales y la línea de los últimos 14 días), dibujada con texturas y líneas del juego.
- Sin resumen para ese objeto, muestra solo el precio de hoy.
- Funciona igual con la subasta de Blizzard o con Auctionator, porque ambos lanzan la misma búsqueda.

**Página del plan**: la pestaña **Mercado** pasa a mostrar el historial completo desde `daily`, con rangos de 1 mes, 3 meses, 6 meses, 1 año y todo; líneas de mínimo y valor de mercado; y una tabla de mínimo y máximo históricos y medias.

### Fase 3: automatización

- **Escaneo al abrir la subasta** (`Scanner`): si han pasado 15 minutos desde el último escaneo (propio o de Auctionator), lanza el escaneo completo solo. Si Auctionator tiene su escaneo completo activado, no lanza el propio: lee el de Auctionator, como ahora. Se apaga con `/oro set autoscan 0`. Aceptado por el usuario el 19/11: escanear no es una acción protegida y la subasta la abre él.
- **Tiene que verse claramente** (petición del usuario): el escaneo automático se ve igual que si se hubiera pulsado el botón. El botón «Escaneo completo» aparece pulsado y desactivado mientras dura, con el texto «Escaneando…». La línea de estado muestra el mismo avance que hoy («Escaneo completo: 3000 / 7000»), indicando que es automático («Escaneo automático: …»). Y el chat avisa al empezar y al terminar. Cuando acaba, el botón vuelve a su estado normal.
- **Vigilante** (`tools/oroboros_watch.py`): comprueba cada 30 s la fecha de `Oroboros.lua`. Cuando cambia y lleva 10 s sin cambiar (el juego terminó de escribir), ejecuta exportar → archivar → plan → `Resumen.lua`. Se arranca a mano en una consola o con el Programador de tareas de Windows al iniciar sesión (documentado en el README). No toca nada del juego.

### Fase 4: cálculos

Cada uno se hace cuando haya datos suficientes para comprobarlo, con su propio diseño corto antes de programarlo:

1. **Franjas con intervalos largos**: cada intervalo de hasta 24 h dice cuánto desapareció en total; eso es la suma de lo que se vende en cada franja que cubre. Con intervalos variados se despejan las 6 tasas resolviendo un sistema de ecuaciones con resultados no negativos (6 incógnitas por objeto, sin dependencias externas). Sustituye al reparto proporcional actual cuando haya suficientes ecuaciones.
2. **Día de la semana**: tasa de desaparición y precio por día de la semana desde `weekly_band` y `daily`.
3. **Caducadas**: separar lo caro que desaparece en bloque a ~24 h de su aparición de lo que se vende de verdad.
4. **Velocidad de rebaja**: tiempo hasta que el mínimo baja después de un escaneo, por objeto.
5. **Precio y ventas**: relación entre el precio relativo y la velocidad a la que desaparece lo barato, para proponer el precio que más gana.

## Decisiones que deja el diseño al constructor (con propuesta)

- Formato exacto de la cadena compacta de `Resumen.lua` (propuesta: cifras separadas por comas en orden fijo y documentado, en cobre entero).
- Algoritmo de mínimos cuadrados no negativos de la fase 4 (propuesta: Lawson-Hanson implementado a mano).
- Colores y medidas del panel, siguiendo el estilo de la ventana actual del addon.
- Nombres de funciones y archivos de Python, salvo los fijados aquí.
- Entregas: cada fase es una entrega con sus pruebas y commits; la fase 4 tiene un diseño corto por cálculo.
- Si el panel también se ofrece en el tooltip (propuesta: no, solo una línea de «▼ 12 % frente a su media», si cabe).

## Por verificar en el juego

- Qué hace el cliente si un archivo listado en el TOC no existe (`Resumen.lua` en una instalación nueva): ¿error visible o se ignora? Si da error, el addon se distribuye con un `Resumen.lua` vacío y el generado lo sustituye.
- Que el panel no tapa ni rompe la ventana de Auctionator.
