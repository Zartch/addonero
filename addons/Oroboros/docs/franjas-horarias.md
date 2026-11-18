# Franjas horarias: cuándo se vende y cuándo está barato cada objeto

Diseño del 18/11/2026. Estado: **implementado** (19/11/2026, plan en `docs/planes/2026-11-19-franjas-horarias.md`). El análisis se calcula al generar el plan leyendo el archivo, en vez de guardar una tabla `hours` en el SQLite del plan, para que nunca esté desfasado.

## Para qué

El usuario escanea varias veces al día, en distintas franjas, para saber a qué horas se consume (vende) más cada objeto y a qué horas está más barato. La idea es suya: sacar los datos en bruto del juego a un SQLite y analizarlos fuera, quedándose solo con lo importante.

Hoy esa información se pierde. El histórico guarda una fila por objeto y día, y cada escaneo sobrescribe la anterior: el 18/11 hubo al menos 3 escaneos y solo queda el de las 21:18.

## Objetivos

- No perder ningún escaneo completo: cada uno llega a un archivo SQLite permanente.
- Análisis por franja horaria: ventas estimadas por hora y precio mínimo típico de cada franja.
- Que el plan lo diga: para lo que vendes, la mejor franja para publicar; para lo que compras, la franja más barata.

## Fuera de alcance (por ahora)

- Que la ruta cambie sola según la hora: el plan informa y tú decides cuándo hacerla.
- Usar el archivo para mejorar las ventas por día del planificador (y salir antes de los lotes de prueba). Es el siguiente paso natural, pero va aparte.
- Búsquedas puntuales (`Scanner.Search`): solo cuentan los escaneos completos.

## Lo que sería un fracaso

- Que `Oroboros.lua` crezca tanto que el juego tarde en cargar o en hacer `/reload`.
- Dar como cierta una franja con pocos datos: con menos de 3 mediciones en al menos 2 días distintos, la franja sale «sin datos suficientes».

## Enfoques considerados

| | Enfoque | Por qué sí o no |
|---|---|---|
| **A (elegido)** | El juego guarda los últimos escaneos en bruto; el exportador los añade a un SQLite permanente; el análisis se hace fuera | Elegido por el usuario: datos en bruto, se pueden volver a analizar como se quiera |
| B | Resúmenes por franja calculados dentro del juego | Pequeño, pero no se puede volver a analizar |
| C | Como A, solo con los objetos de recetas y plan | Más ligero, pero no descubre objetos nuevos |

## Diseño

### 1. Addon: buffer de escaneos (`DB.lua`, `Scanner.lua`)

- Tras cada escaneo completo (propio o leído de Auctionator), se añade a `OroborosDB.markets[mercado].scans` un registro `{ t = hora, data = "itemID,min,mv,qty,b,bp;…" }`:
  - `qty`: total publicado.
  - `b`: unidades **baratas**, a ≤ mínimo de este escaneo × 1,25.
  - `bp`: unidades a ≤ el umbral barato del **escaneo anterior** (mínimo anterior × 1,25). Sale de `prices`, que todavía guarda el escaneo previo al procesar el nuevo. Así la bajada de lo barato se mide con el mismo umbral en los dos escaneos; si se usara el mínimo de cada escaneo, al venderse lo más barato el umbral subiría y la bajada no se vería.
- Va en una cadena compacta (unos 150 KB por escaneo) y no en tablas, para que el archivo pese menos y cargue más rápido.
- Se guardan los **últimos 12**; al llegar el 13.º se descarta el más antiguo.
- El addon no puede saber qué se ha exportado ya, porque el juego no lee archivos. Por eso `/oro stats` y el pie de la ventana muestran «escaneos guardados: N/12», y con 12 avisan de que hay que exportar antes del siguiente.
- Tamaño previsto: unos 200 KB por escaneo, hasta ~2,5 MB más en `Oroboros.lua`.

### 2. Exportador: archivo permanente (`oroboros_export.py --archive`)

- `--archive work/archivo.sqlite` añade los escaneos del buffer a una tabla `scans(market, t, item_id, min, mv, qty, cheap, cheap_prev)`, con clave `(market, t, item_id)`.
- Exportar dos veces el mismo escaneo no duplica nada. Este archivo **nunca se borra**: es distinto del SQLite del plan, que se rehace cada vez.
- Avisa si entre el último escaneo archivado y el más antiguo del buffer falta alguno (se perdió por pasar de 12 sin exportar).

### 3. Análisis (`tools/oroboros_hours.py`)

- **Franjas**: 6 de 4 horas, en hora local: 0–4, 4–8, 8–12, 12–16, 16–20, 20–24.
- **Dos cuentas de lo que desaparece** (idea del usuario), entre dos escaneos seguidos separados como mucho 6 h:
  - **Total**: `qty` anterior − `qty` actual.
  - **Baratas**: `cheap` anterior − `cheap_prev` actual, es decir, cuánto ha bajado lo que estaba a ≤ el umbral barato anterior, medido con ese mismo umbral. Es lo que más probablemente se ha vendido.
  - En las dos, si sube cuenta 0 (publicaciones nuevas, que no se pueden separar de las ventas): se infravalora por igual en todas las franjas. Lo desaparecido se reparte entre las franjas que cubre el intervalo.
  - **Comparación** («a ver si vemos algo»): el análisis muestra las dos cuentas lado a lado por franja y, para cada objeto, qué parte de lo desaparecido era barato. Si lo barato explica casi toda la bajada, es venta real; si no, hay cancelaciones o caducadas de por medio. Con los datos se decide cuál usa el plan; mientras tanto, el plan usa **baratas**.
- **Precio**: mediana del mínimo en los escaneos hechos dentro de cada franja.
- **Fiabilidad**: una franja necesita al menos 3 mediciones repartidas en 2 días distintos; si no, sale «sin datos suficientes».
- **Salida**: una tabla `hours(market, item_id, band, gone_total_h, gone_cheap_h, price_med, n, days)` dentro del SQLite del plan. También se puede ejecutar sola y muestra un resumen por consola.

### 4. Plan (`oroboros_plan.py`, `planner_ui.html`)

- Cada venta (`SELL`, fabricación o reventa) que tenga datos fiables añade: «Se vende más de 20 a 24 h (≈12/h, frente a 3/h de media). Publica antes de esa franja».
- Cada compra añade: «Suele estar más barato de 4 a 8 h (−9 % frente a la media)».
- En `plan.html`, una pestaña nueva **Horas**: para los objetos del plan y de tus recetas, una fila por objeto con las 6 franjas coloreadas (ventas por hora y precio).

### 5. Pruebas

Escaneos simulados a distintas horas en `tests/run_tests.py`:

- El buffer se queda en 12.
- El archivo no duplica escaneos y detecta huecos.
- El reparto de lo desaparecido entre franjas, con las dos cuentas, se comprueba con un caso calculado a mano. Incluye el caso de un mínimo que sube al venderse lo barato: con `cheap_prev` se ve la bajada, con el mínimo de cada escaneo no.
- Una franja con pocos datos sale como «sin datos suficientes».
- El texto del plan aparece solo cuando hay datos fiables.

## Decisiones del constructor (propuestas, se pueden cambiar)

- 12 escaneos en el buffer y franjas de 4 horas.
- «Barato» = a ≤ mínimo × 1,25 (el mismo escalón que ya usa la profundidad, `d125`).
- Intervalo máximo de 6 h entre escaneos para medir ventas.
- Mínimo de 3 mediciones en 2 días por franja.
- Cadena compacta en vez de tablas.
- El archivo vive en `work/archivo.sqlite`, que git ignora: lleva datos de tu mercado.
