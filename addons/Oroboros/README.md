# Oroboros

Addon del proyecto [Addonero](../../README.md).

Addon de subasta para **WoW Forever** y planificador de oro. Versión 0.5.0.

El addon escanea la subasta, guarda precios, recetas, inventario y compras, y ejecuta una ruta de compra, fabricación y venta con un clic por acción. El planificador (fuera del juego) lee esos datos y calcula qué fabricar, qué comprar, qué aprender y qué apuestas hacer, y genera la ruta que pegas en el addon.

> **Estado:** la lógica está probada fuera del juego con una simulación de la API de WoW y con datos sintéticos (84 comprobaciones). **Todavía no se ha probado en el cliente real.** La primera sesión en el juego es de validación.

## Índice

1. [Cómo funciona](#cómo-funciona)
2. [Instalación](#instalación)
3. [Primer uso](#primer-uso)
4. [Subasta sin entrar al juego: API de Blizzard y panel](#subasta-sin-entrar-al-juego-api-de-blizzard-y-panel)
5. [Varios personajes y banquero](#varios-personajes-y-banquero)
6. [La ventana del addon](#la-ventana-del-addon)
7. [Comandos](#comandos)
8. [Formato de ruta](#formato-de-ruta)
9. [Qué guarda el addon](#qué-guarda-el-addon)
10. [Planificador](#planificador)
11. [La página del plan](#la-página-del-plan)
12. [Ideas de especulación](#ideas-de-especulación)
13. [Cartera](#cartera)
14. [catalog.json](#catalogjson)
15. [Base de datos SQLite](#base-de-datos-sqlite)
16. [Referencia de funciones del addon](#referencia-de-funciones-del-addon)
17. [Límites conocidos](#límites-conocidos)
18. [Problemas frecuentes](#problemas-frecuentes)
19. [Pruebas](#pruebas)

## Cómo funciona

```
 EN EL JUEGO                         FUERA DEL JUEGO
 ┌─────────────────────┐  /reload   ┌──────────────────────┐
 │ Addon: escanea y     │──────────▶│ oroboros_export.py    │
 │ guarda en            │ Oroboros  │  → oroboros.sqlite    │
 │ SavedVariables       │   .lua    └──────────┬───────────┘
 └─────────▲───────────┘                       ▼
           │ pegar ruta             ┌──────────────────────┐
           └────────────────────────│ oroboros_plan.py      │
                                    │  → plan.html + rutas  │
                                    └──────────────────────┘
```

Dos reglas del juego condicionan el diseño:

- **Un clic por acción.** Comprar, publicar y fabricar exigen un clic o una tecla. Automatizarlo del todo es *botting* y se castiga con baneo. El addon prepara y comprueba cada acción; tú pulsas **Siguiente**.
- **El addon no tiene red ni escribe archivos.** Solo guarda `SavedVariables`, que el juego escribe al hacer `/reload` o al salir. Por eso los datos salen por ese archivo y la ruta entra pegándola.

## Instalación

1. Copia la carpeta `Oroboros/` en `World of Warcraft/_forever_/Interface/AddOns/`, o enlázala para que los cambios se vean con `/reload` (en Windows, sin ser administrador: `mklink /J "<WoW>\_forever_\Interface\AddOns\Oroboros" "<repo>\addons\Oroboros\Oroboros"`).
2. El TOC declara `## Interface: 16001, 120105` (Forever usa 16001; cliente 1.60.1). Compruébalo en el juego con `/dump select(4, GetBuildInfo())`; si no coincide, cambia la línea `## Interface:` de `Oroboros.toc` o activa "Cargar addons desactualizados".
3. Escribe `/oro` para ver la ayuda.
4. Para el planificador necesitas Python 3.8 o posterior. No hay dependencias que instalar.

## Primer uso

| Paso | Dónde | Qué hacer |
|---|---|---|
| 1 | Subasta | Al abrirla aparece la ventana. Pulsa **Escaneo completo** (uno cada 15 minutos como mucho). Con Auctionator y su escaneo completo activado, escanea él y Oroboros lee el mismo resultado (ver «Con Auctionator»). |
| 2 | Cada profesión | Ábrela una vez con cada personaje. Se lee sola. |
| 3 | Vendedores de materiales | Ábrelos una vez (hilo, viales…). |
| 4 | Banco | Ábrelo una vez con cada personaje. |
| 5 | Correo | Ábrelo: las ventas de subasta cobradas se anotan. |
| 6 | Cualquier sitio | `/reload` o salir del juego, para que se escriba el archivo. |
| 7 | Fuera del juego | `python tools/oroboros_export.py --find "<carpeta WoW>" --sqlite oroboros.sqlite` |
| 8 | Fuera del juego | `python tools/oroboros_plan.py --db oroboros.sqlite --html plan.html --routes rutas` |
| 9 | Navegador | Abre `plan.html`, ve a **Ruta** y pulsa **Copiar ruta completa**. |
| 10 | Juego | **Importar ruta** → pegar (Ctrl+V) → **Cargar ruta** → pulsar **Siguiente**. |

Cuantos más días escanees, mejor: el planificador necesita histórico para calcular medianas, tendencias y ventas por día. Con menos de 4 días la confianza sale baja; las ideas de especulación piden entre 7 y 13 días.

Para probar sin jugar:

```
python tools/make_synthetic.py --out Oroboros.lua
python tools/oroboros_export.py Oroboros.lua --sqlite oroboros.sqlite
python tools/oroboros_plan.py --db oroboros.sqlite --html plan.html --routes rutas --synthetic
```

## Con Auctionator

Si Auctionator está instalado, Oroboros no escanea dos veces (detalle en `docs/fuentes-de-precios.md`):

- **En el juego.** Activa en Auctionator el escaneo completo (opciones avanzadas: escaneo con `ReplicateItems`). Cuando Auctionator escanea, Oroboros lee el mismo resultado: mínimo, valor de mercado, cantidad y profundidad, sin pedir otro escaneo. Su botón **Escaneo completo** solo te lo recuerda; `/oro scan forzar` lanza el propio, respetando el límite de 15 minutos de los dos. Sin Auctionator, todo sigue como antes.
- **Fuera del juego.** `oroboros_export.py --auctionator` añade los precios y el histórico de 21 días que guarda Auctionator. Rellena los días y objetos que Oroboros no tiene; si los dos tienen dato del mismo día, gana el de Oroboros (trae profundidad).
- **Lo que no da Auctionator:** profundidad y valor de mercado. Con sus precios el planificador estima la profundidad y no da confianza alta.

## Franjas horarias

Para saber a qué horas se vende más cada objeto (diseño en `docs/franjas-horarias.md`):

1. **Escanea varias veces al día**, en distintas franjas, y haz `/reload` después de cada escaneo. El addon guarda los últimos 12 escaneos completos; al llegar uno nuevo sale el más antiguo. `/oro stats` y el pie de la ventana muestran «sin exportar: N/12»: el exportador apunta en `Resumen.lua` hasta qué escaneo está archivado, y el juego lo lee al entrar o con `/reload`. Solo se pierde un escaneo si hay más de 12 sin exportar; con el vigilante en marcha no pasa.
2. **Exporta antes de tener 12 sin exportar**, o se perderá el más antiguo. Los escaneos se van añadiendo a un archivo permanente que nunca se borra:
   ```
   python tools/oroboros_export.py --find "<carpeta WoW>" --auctionator --archive work/archivo.sqlite --sqlite work/oroboros.sqlite
   ```
3. **Genera el plan con el archivo**: `python tools/oroboros_plan.py --db work/oroboros.sqlite --archive work/archivo.sqlite --html work/plan.html --routes work/rutas`. Las ventas dirán en qué franja desaparece más el objeto, las compras en cuál está más barato, y la pestaña **Horas** muestra todas las franjas.
4. Para mirarlo por consola: `python tools/oroboros_hours.py work/archivo.sqlite` (o `--item <id>`).

**El archivo** (`work/archivo.sqlite`) es la única fuente de verdad de los precios: productos, mercados, escaneos y observaciones relacionados entre sí, sin repetir nombres. Guarda los escaneos en bruto 8 semanas; después los resume por semana y franja y los borra. El histórico diario de cada producto se guarda para siempre (de los escaneos; si no hay, del histórico del juego, y si no, de Auctionator). Con `--archive` y `--sqlite`, el plan toma su histórico del archivo. El juego guarda solo 14 días. Si el archivo es de antes del 19/11, se convierte solo la primera vez y deja una copia `.bak`.

Se cuentan dos cosas entre escaneos seguidos (como mucho 6 h): lo que desaparece en total y lo que desaparece **barato** (a ≤ mínimo × 1,25, con el mismo umbral en los dos escaneos), que es lo que más probablemente se ha vendido. Una franja necesita 3 mediciones en 2 días distintos para darse por fiable.

## Automatización

**Escaneo automático.** Al abrir la subasta, si han pasado 15 minutos desde el último escaneo (propio o de Auctionator), Oroboros lanza el escaneo completo solo. Se ve igual que si hubieras pulsado el botón:

- el botón aparece pulsado y desactivado con «Escaneando…»;
- la línea de estado muestra el avance («Escaneo automático: 3000 / 7000»);
- el chat avisa al empezar y al acabar.

Si Auctionator tiene su escaneo completo activado, no se lanza el propio: se lee el suyo. Se apaga con `/oro set autoscan 0`.

**Lanzador (recomendado).** `tools/oroboros_launch.py` abre Battle.net con WoW Forever, espera a que arranque y, mientras juegas, no consume nada (Windows le avisa cuando se cierra el juego). Al cerrar el juego, exporta al archivo, escribe `Resumen.lua` y genera el plan **una sola vez**, y termina. No hay ningún proceso vigilando cuando no juegas.

Accesos directos para el escritorio:
- **Jugar a Forever con Oroboros**: destino `pythonw.exe "<repo>\addons\Oroboros\tools\oroboros_launch.py" --find "<WoW>\_forever_" --log "<repo>\addons\Oroboros\work\lanzador.log"`. Abre Battle.net con WoW Forever (`--game=wowf`; `wowf` es su código en Battle.net). Con `--modo nada`, solo abre Battle.net.
- **Oroboros: procesar ahora**: destino `"<repo>\addons\Oroboros\tools\oroboros_procesar.bat" --find "<WoW>\_forever_"`. Procesa al momento y enseña el resultado.

Si entras al juego desde Battle.net directamente, no pasa nada: usa «procesar ahora», o se procesará la próxima vez.

**Vigilante (alternativa).** `tools/oroboros_watch.py` mira `Oroboros.lua` cada 30 s. Cuando el juego lo guarda (al salir o con `/reload`) y lleva 10 s sin cambiar, exporta al archivo (con Auctionator), escribe `Resumen.lua` y genera `work/plan.html` y las rutas. No toca nada del juego.

```
python tools/oroboros_watch.py --find "F:/World of Warcraft/_forever_"          # vigilar (Ctrl+C para parar)
python tools/oroboros_watch.py --find "F:/World of Warcraft/_forever_" --once   # procesar ya, una vez
```

Para que arranque solo al iniciar sesión en Windows, sin ventana, crea una tarea programada desde un `cmd` (ajusta las rutas si las tuyas son otras):

```
schtasks /Create /TN "Oroboros vigilante" /SC ONLOGON /TR "\"C:\Users\<usuario>\AppData\Local\Programs\Python\Python310\pythonw.exe\" \"<repo>\addons\Oroboros\tools\oroboros_watch.py\" --find \"F:\World of Warcraft\_forever_\" --log \"<repo>\addons\Oroboros\work\vigilante.log\""
```

Lo que hace queda en `work/vigilante.log`. Para quitarla: `schtasks /Delete /TN "Oroboros vigilante"`.

## Subasta sin entrar al juego: API de Blizzard y panel

Blizzard publica cada hora una foto de toda la subasta de Forever en su API oficial (la que usan TSM y las webs de subasta). Oroboros la lee **sin entrar al juego** y la guarda en `work/archivo.sqlite`. Solo lee: no toca el juego ni la cuenta. Lo comprobado y por qué se hace así está en `docs/api-subasta-blizzard.md` (apartado 0); el plan, en `docs/planes/2026-11-23-api-blizzard.md`.

**Qué da:**
- Precio, valor de mercado, cantidad y profundidad de cada objeto, cada hora, de tu casa (**111**, Alianza) y de la Horda (**114**) y Aguasnegras (**117**) del mismo grupo.
- **Ventas estimadas**: cada subasta tiene su número, así que entre dos fotos se sabe cuál desapareció. Si le quedaba poco tiempo (`SHORT`), cuenta como caducada; si era cara (más de mínimo × 1,25) o sigue viva otra más barata del mismo objeto y variante (quien compra, compra primero lo más barato), como cancelada; si no, como vendida. En materiales, la bajada de cantidad de una misma subasta cuenta como compra.
- Los nombres de los objetos que faltaban.

**Qué no da:** histórico (solo la foto actual; el histórico lo construye Oroboros desde que lo pones en marcha), tu inventario, tus profesiones ni tus ventas reales (eso sigue saliendo del addon).

### Credenciales (una vez)

1. Crea un cliente gratis en `https://develop.battle.net` (*API Access*). Te da un *Client ID* y un *Client Secret*.
2. Escríbelos en `addons/Oroboros/work/bnet.env` (la carpeta `work/` no va a git):
   ```
   BNET_CLIENT_ID=...
   BNET_CLIENT_SECRET=...
   ```
   También valen las variables de entorno `BNET_CLIENT_ID` y `BNET_CLIENT_SECRET`. Nunca se muestran en pantalla ni en los registros.

### El panel de escritorio

```
pythonw tools/oroboros_panel.py --find "F:/World of Warcraft/_forever_"
```

- Abre una ventana propia (Edge en modo aplicación) en `http://127.0.0.1:8737`, que solo se ve desde tu PC.
- Descarga cada hora (pasado el minuto 25, cuando Blizzard ya ha publicado la foto; si una casa aún no la tiene, reintenta cada 5 min). Si no ha cambiado, no baja nada.
- Con `--find`, cada foto nueva regenera también el plan y `Resumen.lua`, como el vigilante; sin `--find`, solo `Resumen.lua`.
- Una vez al día resume lo viejo, pide los nombres que falten y calibra las ventas con tu libro.
- Pestañas:
  - **Inicio** (la primera): descargas de la API (última foto de cada casa, cuenta atrás hasta la próxima y las últimas 24 h con los huecos sin foto en rojo), el juego (último escaneo completo, último guardado, cada personaje con su oro y cuándo se leyó su banco) y lo importante (oro, beneficio e inversión del plan, lo que te sobra y lo más vendido en tu casa, que solo se muestra cuando las ventas estimadas están comprobadas con tu libro);
  - todas las del plan;
  - **Subasta**: estado de la descarga, buscador, precio en las tres casas, gráficas por hora (14 días) y por día (todo), franjas, lo que tienes y tus compras y ventas de ese objeto;
  - **Ventas**: lo más vendido (estimado) en cada casa y la calibración.
- Aspecto: el de la subasta moderna del juego (ventana casi negra, etiquetas doradas, botones planos y pestañas colgando abajo; las del plan, con borde dorado). Solo CSS y una fuente libre (Tenor Sans): nada copiado del juego.
- Cerrar la ventana **no** para la descarga. Para pararla, botón «Parar el panel». Abrirlo otra vez mientras sigue en marcha solo abre la ventana.
- Acceso directo «Oroboros»: destino `pythonw.exe "<repo>\addons\Oroboros\tools\oroboros_panel.py" --find "<WoW>\_forever_" --log "<repo>\addons\Oroboros\work\panel.log"`.

Para que descargue desde que inicias sesión, sin ventana, crea una tarea desde un `cmd` (ajusta las rutas). No se crea sola:

```
schtasks /Create /TN "Oroboros panel" /SC ONLOGON /TR "\"C:\Users\<usuario>\AppData\Local\Programs\Python\Python310\pythonw.exe\" \"<repo>\addons\Oroboros\tools\oroboros_panel.py\" --sin-ventana --find \"F:\World of Warcraft\_forever_\" --log \"<repo>\addons\Oroboros\work\panel.log\""
```

Luego el acceso directo solo abre la ventana. Para quitarla: `schtasks /Delete /TN "Oroboros panel"`.

### Sin panel: `oroboros_api.py`

```
python tools/oroboros_api.py --una-vez            # una descarga (para una tarea programada cada hora)
python tools/oroboros_api.py                      # cada hora, en esta consola
python tools/oroboros_api.py --calibrar           # ventas estimadas frente a tus ventas reales del libro
python tools/oroboros_api.py --importar work/api  # meter fotos guardadas (grp_<UTC>_<casa>_<norm|mat>.json.gz)
```

Opciones: `--casas 111,114,117` y `--reino CAMWOWEU5Realm5PvE` (la clave de mercado es `<reino>-<facción>`).

### Qué gana cuando hay dato del juego y de la API

| Dónde | Gana |
|---|---|
| Precio del día (`daily`) | La API. El escaneo del juego cubre los días sin API |
| Precio de ahora del plan | El más reciente (la última foto de la API trae profundidad real) |
| Ventas por día del plan | Comprobada (ver abajo), la API. Sin comprobar: si tus escaneos miden las ventas, mandan ellos y la API solo puede bajarlas; si no, la API con 3 días de medición cuenta como **estimada** y el plan propone lotes de prueba |
| Franjas horarias | La API en cada franja con 3 mediciones en 2 días. Si no, los escaneos |
| `Resumen.lua` | Lleva «vendidas al día» de la API. Solo los mercados con datos del juego (la Horda y Aguasnegras, en el panel) |

### Cuidado con las ventas estimadas

Las primeras fotos dan cifras muy altas: en la 111, unas 15 000 subastas normales «vendidas» por hora, y el Paño de lino, decenas de miles al día. Seguramente buena parte son recolocaciones: alguien retira una subasta barata y la vuelve a poner un poco más barata, y eso parece una venta. Por eso:
- una subasta barata que desaparece y reaparece en la misma foto con la misma cantidad, al mismo precio o hasta un 20 % más barata, cuenta como cancelada (recolocación). Las ventas por día solo usan las fotos clasificadas con esta regla (desde el 25/11); las de antes no entran;
- el plan no se fía de ellas hasta que la **calibración** lo confirma con dos cosas: que tus ventas del correo aparezcan entre las vendidas (5 ventas tuyas y al menos el 80 %) y que la casa no salga vendida más de una vez al día (rotación: vendidas al día entre lo que hay a la venta). La primera sola no basta: el 24/11 se cumplía con la casa «vendiéndose» 4,7 veces al día;
- los «días de fotos» son tiempo medido: 24 fotos seguidas son un día, caigan en las fechas que caigan;
- en la pestaña Ventas y con `--calibrar` ves qué parte de tus ventas reales ve la estimación y cuánto fuiste tú del total.

### Cuánto ocupa

En `work/archivo.sqlite`:
- `api_live` (la última foto de las tres casas): ~730 000 filas, unos 22 MB fijos;
- `api_item_hour` (precio y movimientos por objeto y hora): unos 18 MB al día, que se guardan 14 días: unos 250 MB fijos (las franjas ya se acumulan al meter cada foto, así que borrar el detalle no pierde nada);
- lo permanente (`api_band_week` por franja y semana, `daily` por día): unos 40 MB al mes.

## Historial de precios (al estilo CamelCamelCamel)

- **En la subasta**: al seleccionar un objeto, a la derecha de la subasta aparece un panel con:
  - el precio de hoy en vivo y si está por encima o por debajo de su media de 30 días;
  - el mínimo y el máximo históricos con su fecha;
  - las medias de 7, 30 y 90 días;
  - 13 barras semanales y 14 diarias;
  - las franjas en las que más se vende y en las que está más barato, si hay datos fiables.

  Funciona con la subasta de Blizzard y con Auctionator. `/oro precio <id o enlace>` lo abre en cualquier sitio.

  Desde la 0.8.0, el panel es oscuro y plano:
  - cabecera con el icono del objeto;
  - el precio de hoy en grande, en verde si está barato o en rojo si está caro;
  - cifras con su etiqueta;
  - gráficas con escala, fechas, leyenda y detalle al pasar el ratón.

  El precio en vivo es el más barato de otros vendedores. `/oro precio debug` muestra en el chat lo que devolvió el juego en la última búsqueda.
- **Sin estar en la subasta**:
  - **Alt + clic** en cualquier objeto (bolsas, banco, enlaces del chat…) abre el mismo panel.
  - El tooltip del objeto muestra su precio con iconos y la diferencia frente a su media de 30 días.
  - **Lo que tienes** (`/oro inventario` o el botón de la ventana) muestra todo lo de tus personajes como las bolsas del juego: iconos grandes con la cantidad en la esquina y el borde del color de la calidad, ordenados por valor (rueda del ratón para bajar). Pestañas **Todo**, **Bolsas**, **Banco** (el último visto) y **Banda**, y buscador. Al pasar el ratón sale el tooltip del objeto con cuántas tienes, cuánto valen y en qué personaje y sitio están. Un punto verde o rojo en la esquina indica si está barato o caro frente a su media de 30 días. Clic: historial de precios; Mayús+clic: enlazarlo en el chat.
- **De dónde salen los datos**: el exportador con `--archive` escribe `Oroboros/Resumen.lua` (unos 0,8 MB; git lo ignora). El juego lo carga al entrar o con `/reload` y solo lo lee, sin engordar `Oroboros.lua`. Con `--resumen RUTA` se cambia el destino y con `--resumen no` no se escribe. A mano: `python tools/oroboros_summary.py work/archivo.sqlite`. Si no existe, el panel muestra solo el precio de hoy.
- **En la página del plan**: la pestaña **Mercado** muestra el historial completo con rangos de 1 mes, 3 meses, 6 meses, 1 año y todo, y una tabla con el mínimo y el máximo del rango e históricos (con fecha) y las medias de 7, 30 y 90 días.
- **Nombres**: tras cada escaneo completo, el addon pide en tandas los nombres de los objetos que el juego aún no le ha dado.

## Dónde farmear

Oroboros propone dónde farmear criaturas de mundo abierto (sin élites ni zonas de élites) y dónde recolectar, según el nivel del personaje. Diseño en `docs/farmeo.md`.

- **Lo que mides manda.** Con Oroboros activo, el addon apunta cada cadáver que despojas (una muerte), su botín (también el equipo) y el tiempo activo, por subzona. Las criaturas que no sueltan nada no cuentan. Al hacer `/reload` o salir, el exportador lo lleva a `work/archivo.sqlite`. Con 30 muertes de una criatura, lo medido sustituye a la estimación; con menos, pesa muertes/30.
- **Estimación inicial para sitios nuevos:** la base del mundo de AzerothCore (servidor libre de WotLK). Solo cuenta oro y materiales, no el equipo, y el botín de Forever cambió, así que es aproximada. Se descarga una vez (≈ 48 MB, a `work/fuentes/azerothcore/`, que git ignora):

  ```
  python tools/oroboros_farm.py --descargar
  ```

  AzerothCore no trae la zona de cada criatura: los sitios son cuadrículas de 400 m. Quedan fuera las ciudades y los campamentos (muchos PNJ con servicios).
- **Recolección:** los nodos de GatherMate2_Data (carpeta Forever), valorados con lo que suelta cada nodo. Solo cuenta los nodos de tu nivel de Botánica o Minería, con la tabla `tools/gather_skill.json` (niveles del juego clásico, sin comprobar en Forever). El Loto negro no se estima, porque aparece de vez en cuando en uno de muchos sitios.
- **En la página del plan**, pestaña **Farmear**, por personaje: «Donde ya has farmeado» (oro por hora real), «Por explorar» (las 10 mejores a tu nivel) y «Recolección» (las 5 mejores).
- **En el juego:** el plan escribe `Oroboros/Farmeo.lua` (unos 40 KB; git lo ignora) y el addon lo lee al entrar. `/oro farmear` abre el panel con lo medido, lo que puedes explorar a tu nivel y la recolección. Al entrar en un sitio de la lista, una línea en el chat: «Farmeo aquí: ≈ X/h (estimado)».
- **Nombres de los sitios:** el juego traduce las coordenadas de cada sitio a zona y coordenadas del mapa, en español, y las guarda en `OroborosDB.farmPlaces`. Después del siguiente `/reload` y exportación, la página los muestra.
- El vigilante y el lanzador regeneran todo esto al cerrar el juego, si AzerothCore está descargado. A mano: `oroboros_plan.py … --azerothcore work/fuentes/azerothcore --wow "<ruta de Oroboros.lua>" --farmeo Oroboros/Farmeo.lua`.

## Varios personajes y banquero

Los datos del addon son **de la cuenta**: lo que lee un personaje lo ven todos. Un personaje de nivel bajo parado en la subasta conoce las recetas de los demás.

1. Entra una vez con cada artesano y abre sus profesiones y su banco. Repítelo cuando aprenda recetas. El plan avisa si las de alguien tienen más de una semana.
2. Con el personaje de la subasta escribe `/oro banquero`. Desde entonces el planificador le da **todas** las compras y ventas.
3. La ruta **Todos** (`ruta_todo.txt`) lleva una sección `CHAR Nombre` por personaje. La pegas **una vez** con cualquiera y cada uno ve su parte al entrar.

Reparto del trabajo con banquero:

| Quién | Qué hace |
|---|---|
| Banquero, primera parte | Compra en la subasta y envía los materiales por correo. |
| Artesanos | Recogen el correo, compran al vendedor, fabrican y devuelven lo fabricado. Va antes el que fabrica para otro artesano. |
| Banquero, segunda parte | Recoge y vende. También vende el stock sobrante de los demás y las apuestas de la cartera que toca cerrar. |

Sin banquero marcado, cada personaje compra y vende lo suyo. `--banker Nombre` lo fuerza desde el planificador y `--banker none` lo desactiva.

Solo se comparten datos entre personajes de la **misma cuenta de WoW** (la misma carpeta `WTF/Account/<CUENTA>`).

## La ventana del addon

Se abre sola al abrir la subasta, a su derecha. También con `/oro show`. Se cierra con Escape.

| Elemento | Función |
|---|---|
| **Escaneo completo** | Lee toda la subasta. El pie indica cuánto falta para el siguiente, o «lo hace Auctionator». |
| **Importar ruta** | Abre el cuadro para pegar una ruta. **Cargar ruta** sustituye la que hubiera; **Añadir a la ruta** suma pasos sin borrar (úsalo para la ruta de ideas); **Vaciar** limpia el cuadro. |
| Línea de estado | Dice qué va a hacer el siguiente clic o por qué no puede. |
| **Siguiente** | Ejecuta el paso actual. Se puede asignar a una tecla en *Opciones → Atajos → Oroboros*. |
| **Saltar** | Pasa al paso siguiente sin hacer el actual. |
| Lista | Los pasos de la ruta de este personaje, con los hechos marcados, y los personajes que tienen pasos pendientes. |
| Pie | Estado del escaneo, hora del último escaneo completo y tu oro. |

Qué hace **Siguiente** según el paso:

- **Comprar un material apilable** (3 clics): busca → calcula cuántas unidades hay por debajo de tu máximo → inicia la compra → el servidor da el precio final → si sigue por debajo del máximo, confirmas; si ha subido, se cancela sola.
- **Comprar equipo** (2 clics): busca → compra la subasta más barata por debajo del máximo.
- **Vender** (2 clics): busca → pone 1 cobre menos que el más barato de otro jugador (no compite con tus propias subastas). Si ese precio queda por debajo de tu mínimo, **no publica**. El equipo se publica de una subasta en una.
- **Fabricar** (1 clic): con la ventana de esa profesión abierta.
- **Nota** (1 clic): paso manual; el clic solo lo marca como hecho.
- **Apuesta** (1 clic): anota la apuesta para la cartera.

El tooltip de cada objeto muestra el precio guardado y qué personaje tuyo lo fabrica.

## Comandos

`/oroboros` y `/oro` son equivalentes.

| Comando | Qué hace |
|---|---|
| `/oro` | Muestra la ayuda. |
| `/oro show` | Muestra u oculta la ventana. |
| `/oro scan` | Escaneo completo (con la subasta abierta). Con Auctionator escaneando, avisa y no lanza otro. |
| `/oro set autoscan 0` | Apaga el escaneo automático al abrir la subasta (`1` lo vuelve a encender). |
| `/oro scan forzar` | Escaneo propio aunque Auctionator haga el suyo (respeta el límite de 15 minutos de los dos). |
| `/oro precio <itemID o enlace>` | Panel con el historial de precios del objeto. |
| `/oro inventario` | Lo que tienes en todos tus personajes, como las bolsas: iconos grandes, tooltip, valor y tendencia. |
| `/oro farmear` | Dónde farmear a tu nivel: lo que has medido, lo que puedes explorar y la recolección. |
| `/oro cliente` | Versión, interfaz, reino, conjunto de reglas y clave de mercado. También se guarda al entrar en `OroborosDB.client`. |
| `/oro price <itemID o enlace>` | Precio guardado: mínimo, valor de mercado, cantidad y hora. |
| `/oro prof` | Profesiones de todos tus personajes, con recetas aprendidas y vistas. |
| `/oro quien <itemID o enlace>` | Qué personaje tuyo lo fabrica. |
| `/oro banquero` | Marca o desmarca este personaje como banquero. |
| `/oro import` | Abre el cuadro para pegar una ruta. |
| `/oro compras` | Últimas 10 compras y ventas registradas. |
| `/oro stats` | Objetos conocidos y precios por mercado. |
| `/oro set <clave> <valor>` | Cambia la configuración. |

Configuración (`/oro set`):

| Clave | Por defecto | Significado |
|---|---|---|
| `historyDays` | 30 | Días de histórico diario que se conservan por objeto. |
| `mvPercent` | 0.15 | Fracción más barata de lo publicado que se usa para el valor de mercado. |
| `postDuration` | 3 | Duración de las subastas. En Forever, 1 = 2 h, 2 = 8 h, 3 = 24 h (el máximo); no son las 12/24/48 h del juego normal. Al publicar, la línea de estado dice cuánto dura. |
| `undercut` | 1 | Cobre que se rebaja respecto al más barato de otro jugador. |
| `ahCut` | 0.05 | Comisión de la subasta, para el neto que muestra la línea de estado. |

## Formato de ruta

Una acción por línea. `#` empieza un comentario. Los precios van en cobre (`12345`) o como `1g23s45c`.

```
# comentario
CHAR  Zartbank                 # lo que sigue es para ese personaje
BUY   2589 200 45              # itemID, cantidad, precio MÁXIMO por unidad
SELL  2996 40 3s50c            # itemID, cantidad, precio MÍNIMO por unidad
CRAFT 2963 100                 # recipeID, veces
NOTE  Envía por correo a Zartch: 200× Linen Cloth
HOLD  2592 600 7s98c 2s52c 2026-12-06 3s15c
```

| Línea | Campos | Qué hace |
|---|---|---|
| `CHAR` | nombre del personaje | Abre una sección. Todo lo que sigue se guarda para ese personaje. Una ruta sin `CHAR` es para el personaje con el que la pegas. |
| `BUY` | itemID, cantidad, precio máximo por unidad | Compra hasta ese precio. Si no hay nada por debajo, lo dice y no compra. |
| `SELL` | itemID, cantidad, precio mínimo por unidad | Publica lo que tengas en las bolsas, sin bajar del mínimo. |
| `CRAFT` | recipeID, veces | Fabrica. Necesita la ventana de esa profesión abierta. |
| `NOTE` | texto libre | Paso manual: banco, correo, vendedor. |
| `HOLD` | itemID, cantidad, objetivo, stop, fecha (AAAA-MM-DD), entrada (opcional) | Anota una apuesta: lo que guardas, a qué precio venderlo, a qué precio rendirte y hasta cuándo. |

Las líneas que el addon no entiende se ignoran y se avisan en el chat.

## Qué guarda el addon

Todo va en `WTF/Account/<CUENTA>/SavedVariables/Oroboros.lua`, en la variable `OroborosDB`.

| Dato | Cuándo se lee | Detalle |
|---|---|---|
| Precios | Escaneo completo o búsqueda de un objeto | Por objeto: mínimo, valor de mercado (media del 15 % más barato de lo publicado), cantidad, número de subastas y profundidad (unidades a ≤ mínimo ×1,10 / 1,25 / 1,5 / 2). |
| Histórico | Con cada escaneo | Una foto por día y objeto, 30 días. |
| Recetas | Al abrir una profesión | Aprendidas **y no aprendidas**: materiales, objeto resultante, dificultad, de dónde se aprende y enfriamiento. |
| Precios de vendedor | Al abrir un vendedor | Solo artículos de stock ilimitado y pagados en oro. |
| Personaje | Al entrar y al cambiar el oro | Oro, nivel, clase y mercado. |
| Bolsas | Cada vez que cambian | Objetos y huecos libres. |
| Banco y banco de banda | Con el banco abierto | Objetos y huecos libres. |
| Libro de compras | Al comprar en subasta | Objeto, cantidad y precio real, con la ruta o a mano. |
| Libro de ventas | Al abrir el correo | Ventas de subasta cobradas, una sola vez cada una. |
| Depósitos | Al vender con la ruta | El depósito real que pide el juego, con duración y cantidad (los últimos 300). |
| Apuestas | Al ejecutar un `HOLD` | Cantidad, entrada, objetivo, stop y fecha. |
| Rutas | Al importar | Una por personaje, con el progreso. |
| Información de objetos | Al verlos | Nombre, calidad, nivel de objeto, tamaño de pila y precio de venta al vendedor. |

El **mercado** es la combinación de reino y facción. Los precios se guardan por mercado.

## Planificador

### oroboros_export.py

Convierte el archivo del addon en SQLite y JSON.

```
python tools/oroboros_export.py <ruta a Oroboros.lua> --sqlite oroboros.sqlite --json oroboros.json
python tools/oroboros_export.py --find "<carpeta WoW>" --sqlite oroboros.sqlite
python tools/oroboros_export.py --find "<carpeta WoW>" --auctionator --sqlite oroboros.sqlite
```

| Opción | Significado |
|---|---|
| `path` | Ruta al `Oroboros.lua` de SavedVariables. |
| `--find <carpeta>` | Busca el archivo dentro de la carpeta de WoW. Si hay varios, usa el más reciente. |
| `--sqlite <archivo>` | Escribe la base SQLite. |
| `--json <archivo>` | Escribe el contenido en JSON. |
| `--archive <archivo>` | Añade los escaneos guardados en el juego a un SQLite permanente (franjas horarias). |
| `--auctionator [archivo]` | Añade al SQLite los precios de Auctionator. Sin ruta, busca `Auctionator.lua` junto a `Oroboros.lua`. |

### oroboros_plan.py

Calcula el plan.

```
python tools/oroboros_plan.py --db oroboros.sqlite --html plan.html --routes rutas
```

| Opción | Por defecto | Significado |
|---|---|---|
| `--db` | obligatorio | SQLite del exportador. |
| `--html <archivo>` | — | Escribe la página del plan. |
| `--json <archivo>` | — | Escribe el plan en JSON. |
| `--routes <carpeta>` | — | Escribe `ruta_todo.txt`, `ruta_<personaje>.txt`, `ideas_todo.txt` e `ideas_<personaje>.txt`. |
| `--horizon` | 48 | Horas que cubre la ruta. |
| `--budget` | 0.8 | Fracción del oro total que puede gastar la ruta. |
| `--spec` | 0.15 | Fracción del oro total para apuestas, solo de lo que sobra tras la ruta. |
| `--banker <nombre>` | el de `/oro banquero` | Personaje que compra y vende. `none` lo desactiva. |
| `--brief <archivo>` | — | Resumen del mercado en Markdown para pedir más ideas a un LLM. |
| `--catalog <archivo>` | `tools/catalog.json` | Catálogo con lo que el juego no da. |
| `--synthetic` | — | Marca el plan como hecho con datos inventados. |
| `--now` | ahora | Hora de referencia (ISO o segundos). Sirve para pruebas reproducibles; `make_synthetic.py` también la acepta. |

Cómo decide:

- **Coste de cada material:** lo más barato entre vendedor, subasta o fabricarlo con tus recetas, en cadena (hasta 4 niveles) y entre personajes.
- **Precio de venta prudente:** el de hoy, pero nunca más de un 15 % por encima de la mediana de 7 días. Si hoy no hay nadie vendiendo, la mediana.
- **Cuántas hacer:** lo que el mercado absorbe en el horizonte, como mucho el 30 % de lo publicado, y el enfriamiento de la receta.
- **Lote de prueba:** mientras no haya días de escaneo suficientes para medir las ventas por día, como mucho 20 unidades o 1 oro por receta o reventa, y lo de confianza baja no pasa del 30 % del presupuesto. Escanea una o dos veces al día y las cantidades crecerán solas.
- **Qué aprender:** primero las recetas a tu alcance; las que tienen el nivel sin comprobar (en Forever el juego no lo da) van en un grupo aparte.
- **Con [ProfessionDB](https://www.curseforge.com/wow/addons/libprofessiondb) instalada** (licencia MIT), el exportador lee sus datos de Forever desde la carpeta de WoW, sin cargarla en el juego. Así:
  - cada receta tiene su nivel requerido real y «te faltan N puntos»;
  - se sabe dónde se aprende: instructor, vendedor con su nombre y precio, misión, contenedor, botín o «con la profesión»;
  - el coste de aprender se usa para calcular en cuántos días se paga;
  - las recetas que nunca existieron se descartan;
  - «si cambiaras de profesión» propone las mejores 30 recetas de las profesiones que no tienes.

  Si un nivel viene de Vanilla, lo avisa. `--professiondb RUTA` cambia la carpeta y `--professiondb no` la desactiva.
- **Riesgo:** de ese 30 %, lo que no es lote de prueba (sobre todo las reventas) usa como mucho la mitad, y el resto queda para lotes de prueba de fabricación.
- **Ventas por día:** se estiman con las bajadas de cantidad publicada entre un día y el siguiente.
- **Margen mínimo:** 8 % sobre el coste. Por debajo, la receta sale como no rentable, con el motivo.
- **Aguasnegras → tu casa:** lista aparte en la pestaña Ideas. Compra en la subasta neutral (sin comisión para el comprador) lo que deja al menos un 15 % vendiéndolo en tu casa por debajo de lo más barato de allí y sin pasar de su mediana de 7 días. Solo materiales que se apilan y con ventas comprobadas en tu casa; como mucho, la mitad de lo que se vende en el horizonte. Entra primero lo que más gana en total (no el % de margen), con el oro libre de todos tus personajes tras la ruta y las ideas; lo que no cabe entero se reduce a lo que cabe. **Nada que gane menos que farmear:** cada objeto tiene que dar más de lo que sacas farmeando en un minuto (y al menos 20 platas), y el viaje, después de pagar los vuelos, más que el farmeo de ese rato. Minutos y vuelos en `catalog.json` (`neutral_trip`: 14 minutos y 60 platas, ida y vuelta desde Ventormenta). El ritmo de farmeo es el de la norma (abajo). Da las líneas `BUY` para pegar allí (foto de menos de 3 h).
- **Tu parte de las ventas:** el lote de una fabricación no pasa de la mitad de lo que se vende en el horizonte, igual que las reventas.
- **Prueba de esfuerzo del depósito:** si con la mitad de las ventas estimadas el depósito perdido al republicar se come el margen, el lote se encoge hasta que no dé pérdidas, y lo dice.
- **Techo de reventa:** una reventa (también desde Aguasnegras) no cuenta con vender más de un 15 % por encima de lo más barato de cada uno de los últimos 7 días. Si cada día vuelve a haber género al precio de hoy, ese es su precio.
- **Ideas:** el rebote se mide con lo más barato de cada día y no entra si el precio lleva días bajando; la sequía no entra si hoy ya ha saltado un 25 % sobre su mediana; si el depósito es grande para lo que ganas, la idea avisa.
- **No se compra lo que viene bajando:** una reventa (también desde Aguasnegras) o un rebote no entran si lo más barato de cada día va cuesta abajo, lleva tres días seguidos bajando o ayer ya estaba al precio de hoy.
- **Precio de venta de las recetas:** tiene el mismo techo que las reventas (un 15 % sobre lo más barato de cada día).
- **Ideas:** el beneficio de cada idea cuenta un depósito perdido.
- **Qué tienes, a subasta:** cada objeto que conviene vender en subasta dice a qué precio publicarlo, por debajo de qué no bajar y cuántas se venden al día.
- **Libranzas del artesano:** al abrir la ventana de la misión, el addon apunta la recompensa (`OroborosDB.questItems`, sin aceptar nada). El plan dice si cumplirla o vender la libranza: lo que da, menos lo que cuesta fabricar o comprar lo que pide, frente a lo que sacas vendiéndola. Sin recompensa apuntada, te pide que abras la misión, salvo que cumplirla ya cueste más que venderla.
- **Iconos:** el panel pide a la API de Blizzard (ruta de medios de objetos, `static-forever-eu`) el icono de cada objeto, hasta 500 por vuelta y primero lo que llevan tus personajes, y guarda solo su número en `api_icons` del archivo. «Qué tienes» lo enseña; la imagen se carga desde `render.worldofwarcraft.com`.
- **Qué aprender, con tu oro:** no cuenta con fabricar al día más de lo que tu oro compra; si no llega ni para una, lo dice. Una profesión que no tienes no lleva plazo (subirla no está contado) y no sale en la portada.
- **Farmeo medido:** con menos de 10 muertes y 5 minutos, confianza baja y por detrás de lo medido con muestra.
- **Qué aprender:** el beneficio al día cuenta con la mitad de lo que se vende (como la ruta), no con todo el mercado. Es un techo con los precios de hoy.
- **Ideas con suelo de vendedor:** si el vendedor paga más de lo que sacarías vendiendo al stop, la pérdida máxima se calcula con el precio del vendedor.
- **Enfriamientos:** una receta con enfriamiento se valora en «qué aprender» como renta diaria: beneficio por uso × usos al día, con un máximo de 2 usos al día. Las que comparten enfriamiento (`cooldown_groups` del catálogo) no se suman: en la ruta, por personaje se queda la que más da.
- **Norma: nada que gane menos que farmear el mismo rato** (28/11). El ritmo es todo lo medido por el addon (no hay que activar nada: cuenta cada cadáver y cada nodo que despojas fuera de mazmorras): oro y botín de criaturas más plantas y minerales. **El tiempo no es solo el activo:** se amortizan los descansos y movimientos (la parte activa de la sesión: el addon mide la sesión con los huecos de hasta 10 minutos; con poco medido se mezcla con un supuesto del 60 % activo, con el peso de una hora) y los viajes a vender y reparar (10 minutos por hora). La primera muerte de cada sesión, que no tiene tiempo, cuenta lo que suele costar una muerte. Supuestos en `catalog.json` (`farm_overhead`). Se usa aunque haya poco; con menos de media hora medida es de confianza baja y con dos horas o más, alta. La página lo dice junto al reparto (criaturas, plantas) y lo que sería solo matando y recogiendo. Sin nada medido, 5 oro a la hora supuestos. Cuenta 3 s por fabricación (también las intermedias), 15 s por material comprado en la subasta, 5 s por material del vendedor y 15 s por publicar. Se aplica a cada fabricación, a cada oportunidad entera de la ruta y a Aguasnegras. Lo que no llega sale con su motivo: cuánto ganas, cuánto tardas y cuánto sacarías farmeando.
- **Confianza** (alta, media, baja): según la volatilidad, las ventas por día y los días de histórico.
- **Qué entra en la ruta:** primero lo que más gana en total, ponderado por la confianza, hasta agotar el presupuesto. El % de margen no ordena: el tiempo cuesta lo mismo para 30 platas que para 10 oro.
- **Tu stock primero:** bolsas → banco → banco de banda → banquero → otro personaje. La ruta añade los pasos de banco y correo.
- **Oro:** si a un personaje no le llega, la ruta incluye que otro se lo envíe.
- **Reventa:** con la lista completa de subastas de la API, por escalones: comprar todo lo que hay por debajo de un salto de precio del 25 % o más y volver a ponerlo justo bajo el escalón siguiente, sin pasar de la mediana de 7 días, sin comprar más de lo que vas a poder vender (la mitad de las ventas del horizonte) y con un 15 % de margen después de comisión y depósitos. Sin API, la regla anterior: el mínimo un 25 % por debajo de su mediana de 7 días. El equipo con variantes («del bandido», «de la ballena») no se revende: su precio por número de objeto mezcla productos distintos.
- **Depósito:** el 60 % del precio de vendedor por cada publicación de 24 h (5 % a 2 h y 20 % a 8 h; mínimo 1 cobre). Se devuelve al vender y se pierde al caducar. El plan cuenta con que te llevas la mitad de las ventas del día: lo que no cabe se vuelve a publicar y pierde su depósito. Son cifras de guías; el addon apunta el depósito real al publicar y, con 3 mediciones, el plan usa el porcentaje medido.
- **Stock sobrante:** propone venderlo, salvo que sea material de una receta con enfriamiento, de una receta que te conviene aprender, o que ese día haya señal de compra.

### make_synthetic.py

Crea un `Oroboros.lua` inventado para probar: tres personajes (un banquero y dos artesanos), 14 días de precios, bancos, compras y apuestas.

```
python tools/make_synthetic.py --out Oroboros.lua --seed 7
```

## La página del plan

`plan.html` es un archivo único que se abre en cualquier navegador.

| Pestaña | Qué muestra |
|---|---|
| **Resumen** | Beneficio estimado, inversión, rentabilidad, avisos, lo que vas a hacer y el orden entre personajes. |
| **Ruta** | La ruta completa (**Todos**) o la de cada personaje, con botón de copiar. |
| **Qué ganas y por qué** | Cada receta rentable: unidades, coste, venta, margen, confianza y gráfica. Al pulsar una fila salen la explicación en frases y de dónde sale cada material. Debajo, las que sabes y no compensan, con el motivo. |
| **Transformaciones** | Para cada cosa que sabes fabricar: coste de fabricarla frente a comprarla, ahorro, valor añadido y consejo. |
| **Qué aprender** | Recetas que no sabes: beneficio por día, coste de aprender, días en pagarse y puntos que te faltan. Incluye recetas de profesiones que no tienes. |
| **Ideas** | Apuestas a varios días, con su ruta aparte. |
| **Cartera** | Apuestas abiertas y últimas compras y ventas. |
| **Qué tienes** | Bolsas, banco y banco de banda de cada personaje: valor, huecos, valor por hueco y qué hacer con cada objeto. |
| **Mercado** | Precio y cantidad publicada de cada objeto en 14 días. |

Qué hacer con cada objeto de **Qué tienes**:

| Etiqueta | Significado |
|---|---|
| la usa la ruta | La ruta de hoy lo gasta. |
| guardar | Es material de una receta con enfriamiento, de una que te conviene aprender, o hay señal de compra. |
| vender en subasta | Te sobra y el mercado lo absorbe. Ya está en la ruta. |
| vender más tarde | Te sobra, pero vender más hoy hundiría el precio. |
| al vendedor | Vale más en el vendedor o vale muy poco. |
| apuesta abierta | Está en la cartera; manda lo que diga la cartera. |

## Ideas de especulación

Compras de hoy para vender más adelante. Usan solo el oro que sobra después de la ruta. Los objetivos son **escenarios, no predicciones**.

| Tipo | Señal | Riesgo |
|---|---|---|
| Despensa | Un material que la ruta ya compra está al menos un 8 % por debajo de su mediana de 14 días. Compra para 5 días más. | bajo |
| Rebote | Precio al menos un 15 % por debajo de su mediana, con 3 ventas al día o más. | medio |
| Ciclo semanal | Un día de la semana caro y otro barato, coincidentes en las dos semanas y con un 15 % de diferencia. | medio |
| Oferta que se seca | Lo publicado cae un 30 % en dos semanas y el precio sube. | medio |
| Evento | Una fecha de `catalog.json` a entre 3 y 35 días y los objetos que deberían subir. | medio |
| Progresión del servidor | Material de nivel bajo que se publica cada vez menos (−12 % o más) y cuyo precio ha dejado de bajar en los últimos 5 días. Si no cumple las dos cosas, queda en vigilancia con el motivo. | alto |

La **fase del servidor** se lee en el mercado: cómo cambian la oferta y el precio de los materiales de nivel bajo frente a los de nivel alto. No depende de cuánta gente haya a nivel máximo.

Cada idea trae:

- La razón en frases y las demás señales que la apoyan.
- Cuánto comprar: el mínimo entre el 35 % del presupuesto de apuestas, lo que hay cerca del precio mínimo, el 25 % de las ventas de una semana y los huecos libres.
- Dónde guardarlo.
- Fecha y precio objetivo, precio a partir del cual no pierdes, y stop (un 20 % por debajo de la entrada).
- Si sabes fabricarlo más barato que comprarlo, la idea es fabricarlo.

La ruta de ideas va aparte (`ideas_todo.txt`). Pégala con **Añadir a la ruta** para no borrar la ruta normal.

Con `--brief mercado.md` el planificador escribe una tabla del mercado y las ideas ya encontradas, con una petición lista para pegar en un LLM y pedirle ideas que estas reglas no ven.

## Cartera

Cada línea `HOLD` que ejecutas en el juego abre una apuesta. En la siguiente pasada, el planificador la cruza con el libro de compras y con el inventario.

| Estado | Condición | Qué hace el plan |
|---|---|---|
| objetivo | El precio de hoy llega al objetivo. | Añade la venta a la ruta. |
| stop | El precio de hoy cae hasta el stop. | Añade la venta a la ruta. |
| vencida | Ha pasado la fecha. | Añade la venta si estás en beneficio; si no, solo avisa. |
| espera | Nada de lo anterior. | Nada. |
| cerrada | Ya no lo tienes. | Nada. |

- **Precio de compra:** la media de lo que pagaste según el libro. Si no hay compras registradas (lo fabricaste o lo compraste sin el addon), el previsto en el plan.
- **Cantidad:** lo planeado menos lo vendido, sin pasar de lo que tienes en bolsas y bancos.
- No se propone una idea nueva sobre un objeto con apuesta abierta.

## catalog.json

Completa lo que el juego no da al addon, con **datos reales de Forever** (revisado el 24/11/2026). Las pruebas usan su propio catálogo inventado, `tests/catalogo_sintetico.json`.

| Sección | Contenido |
|---|---|
| `facts` | Lo que el catálogo da por cierto de Forever: `text`, `source` (fuente), `verified` (comprobado en nuestros datos o en una nota oficial) y `how` (cómo se comprobó). La pestaña Ideas los enseña con su marca. |
| `price_caps` | Techo de precio por itemID: `cap` (en cobre), `note`, `source` y `verified`. Si un vendedor da el objeto a precio fijo, el objetivo de una idea no pasa de ahí. Trae Loto negro y Cristal Arcano a 50 oro (mercado negro, sin comprobar). |
| `server` | `raid_reset_weekday`: día del reinicio semanal de las bandas (lunes = 0; trae 2, miércoles, sin comprobar). `launch`: apertura del servidor, el 4/11/2026. `low_level_max_ilvl`: nivel de objeto hasta el que un material cuenta como de nivel bajo (40). `progression_horizon_days`: plazo de las apuestas de progresión (21). |
| `recipes` | Enfriamiento de recetas en horas (`cooldown_h`), con `source` y `verified`. Trae las transmutaciones: arcanita y legionita 47 h, esencias 23 h, hierro a oro y mitril a veraplata 1 h, y la tela lunar, 95 h (sin comprobar). Vale también para recetas de profesiones que no tienes. También admite `skill`, `learn_cost` y `learn_note`, que mandan sobre ProfessionDB. |
| `cooldown_groups` | Recetas que comparten enfriamiento, por grupo. Trae `transmutar` (sin confirmar en Forever). |
| `events` | Fechas que mueven la demanda: `name`, `date`, `items`, `uplift` (multiplicador supuesto) y `note`. Trae la apertura del 9/12/2026 (Barrow Deeps 10, Hyjal Summit 20 y Onyxia's Lair 40) en tres eventos: pociones y hierbas, elixires (con los 13 nuevos de nivel 55) y frascos (con los cuatro naturales); y aparte la protección contra el fuego para Onyxia. Un objeto va en un solo evento. Las dos tandas de 2027 se añadirán cuando tengan fecha. |
| `progression` | Por itemID de nivel bajo: `note` (para qué se sigue usando a nivel 60) y `scenario` (multiplicador supuesto). |
| `professions` | Opcional. Recetas de profesiones que no tienes; se usa solo si ProfessionDB no está instalada. |

Los multiplicadores (`uplift`, `scenario`) son suposiciones: el planificador los usa como escenario con stop, nunca como predicción. Las fechas y los objetos son reales.

## Base de datos SQLite

| Tabla | Contenido |
|---|---|
| `items` | Nombre, calidad, venta al vendedor, pila, si es apilable en subasta, compra al vendedor, nivel de objeto. |
| `prices` | Por mercado y objeto: mínimo, valor de mercado, cantidad, subastas, hora, profundidad (`d110`, `d125`, `d150`, `d200`) y origen (`src`: `oro` Oroboros, `atr` Auctionator, `api` API de Blizzard). |
| `history` | Por mercado, objeto y día: mínimo, valor de mercado, cantidad y origen (`src`). Con Auctionator, «valor de mercado» es el mínimo más alto del día. |
| `characters` | Mercado, oro, nivel, clase. |
| `inventory` | Por personaje y zona (`bags`, `bank`, `warband`): objeto y cantidad. |
| `slots` | Huecos totales y libres por personaje y zona. |
| `professions` | Nivel y máximo por personaje y profesión. |
| `recipes` | Por personaje: receta, aprendida o no, objeto resultante, cantidades, dificultad, origen, enfriamiento. |
| `reagents` | Materiales de cada receta. |
| `deposits` | Depósitos reales al publicar: hora, objeto, duración, cantidad y depósito. |
| `ledger` | Compras y ventas: hora, personaje, objeto, cantidad, precio por unidad, total. |
| `positions` | Apuestas: cantidad, entrada, objetivo, stop, fecha. |
| `config` | Configuración del addon, incluido el banquero. |
| `recipe_cost` (vista) | Coste por material: vendedor si existe; si no, el mínimo de subasta. |

Ejemplo, beneficio bruto por receta aprendida:

```sql
SELECT rc.name, p.mv AS venta,
       SUM(c.qty * c.unit_cost) AS coste,
       p.mv * 0.95 - SUM(c.qty * c.unit_cost) AS margen
FROM recipes rc
JOIN recipe_cost c ON c.recipe_id = rc.recipe_id
JOIN prices p ON p.item_id = rc.output_item
WHERE rc.learned = 1
GROUP BY rc.char, rc.recipe_id
ORDER BY margen DESC LIMIT 20;
```

Con varios mercados, filtra por `market`.

## Referencia de funciones del addon

El addon se reparte en siete archivos que comparten una tabla privada `ns`. Solo `Oroboros_Next()` y la variable `OroborosDB` son globales.

### Core.lua — utilidades, eventos y comandos

| Función | Qué hace |
|---|---|
| `ns.Print(...)` | Escribe en el chat con el prefijo del addon. |
| `ns.Money(cobre)` | Formatea un precio como `12g 34s 56c`. |
| `ns.Today()` | Fecha de hoy, `AAAA-MM-DD`. |
| `ns.MarketKey()` | Clave del mercado: reino y facción. |
| `ns.CharKey()` | Clave del personaje: nombre y reino. |
| `ns.Cfg(clave)` | Valor de configuración, o el valor por defecto. |
| `ns.On(evento, función)` | Registra un manejador. Si el evento no existe en esta versión del juego, lo ignora sin romper la carga. |

### DB.lua — base de datos

| Función | Qué hace |
|---|---|
| `DB.Init(defaults)` | Crea o migra `OroborosDB` y limpia el histórico antiguo. |
| `DB.Market(mk)` | Devuelve (y crea) los datos de un mercado. |
| `DB.SetItemInfo(itemID, nombre, calidad, apilable)` | Guarda lo que se sabe del objeto. |
| `DB.ItemName(itemID)` | Nombre del objeto. |
| `DB.IsCommodity(itemID)` | Si se vende por cantidad en la subasta. |
| `DB.Aggregate(listados)` | De una lista de `{precio, cantidad}` saca mínimo, valor de mercado, cantidad, número de subastas y profundidad. |
| `DB.RecordPrices(porObjeto, completo, mk)` | Guarda precios e histórico. Con `completo`, lo que no aparece queda con cantidad 0. |
| `DB.GetPrice(itemID, mk)` | Último precio guardado. |
| `DB.PruneHistory()` | Borra el histórico más antiguo que `historyDays`. |
| `DB.SetVendorPrice(itemID, precio)` | Guarda el precio de compra al vendedor. |
| `DB.Char()` | Datos del personaje actual. |
| `DB.SnapshotCharacter()` | Guarda oro, nivel, clase y mercado. |
| `DB.ReadContainers(ids)` | Lee contenedores: objetos y huecos. |
| `DB.SnapshotBags()` | Guarda las bolsas. |
| `DB.SnapshotBank()` | Guarda el banco y el banco de banda (con el banco abierto). |
| `DB.AddLedger(op, itemID, cantidad, unidad, total, origen)` | Anota una compra o una venta. |
| `DB.SetPosition(acción)` | Abre o amplía una apuesta. |
| `DB.PrintStats()` | Imprime el tamaño de la base de datos. |

### Scanner.lua — subasta y vendedores

| Función | Qué hace |
|---|---|
| `Scanner.CanFullScan()` | Si se puede escanear ya y cuántos segundos faltan (cuenta también el último escaneo de Auctionator). |
| `Scanner.FullScan(force)` | Lanza el escaneo completo y lo procesa por tandas para no congelar el juego. Si Auctionator hace el escaneo completo, no lo lanza salvo con `force`. |
| `Scanner.AuctionatorLoaded()` / `Scanner.AuctionatorReplicates()` | Si Auctionator está cargado / si tiene activado su escaneo completo. |

Cuando otro addon pide `ReplicateItems`, el evento `REPLICATE_ITEM_LIST_UPDATE` llega también a Oroboros, que lee ese resultado (una vez cada 5 minutos como mucho).
| `Scanner.Search(itemID, callback)` | Busca un objeto, guarda su precio y devuelve las filas ordenadas por precio. |

También guarda los precios de los vendedores al abrirlos.

### Professions.lua — recetas

| Función | Qué hace |
|---|---|
| `Professions.Scan()` | Lee la profesión abierta: nivel, recetas, materiales, origen y enfriamientos. Ignora profesiones enlazadas o de otros. |
| `Professions.Crafters(itemID)` | Qué personajes de la cuenta saben fabricar un objeto. |
| `Professions.PrintSummary()` | Resumen de profesiones de todos los personajes. |

También añade al tooltip el precio guardado y quién fabrica el objeto.

### Ledger.lua — compras y ventas reales

No expone funciones. Escucha:

- La confirmación y el éxito de una compra por cantidad, para anotar objeto, cantidad y precio final.
- La puja y la compra completada de una subasta de equipo.
- Las facturas de venta del correo, sin repetir ninguna.

### Queue.lua — ruta

| Función | Qué hace |
|---|---|
| `Queue.ParseMoney(texto)` | Convierte `12345` o `1g23s45c` a cobre. |
| `Queue.Parse(texto)` | Convierte un texto en acciones y lista de líneas no entendidas. |
| `Queue.ResolveChar(nombre)` | Encuentra la clave de un personaje por su nombre. |
| `Queue.Split(texto)` | Parte una ruta con líneas `CHAR` en secciones por personaje. |
| `Queue.Import(texto, añadir)` | Guarda la parte de cada personaje. Con `añadir`, suma a lo que hubiera. |
| `Queue.Items()` | Acciones del personaje actual. |
| `Queue.Current()` | Acción pendiente y su posición. |
| `Queue.Pending()` | Otros personajes con acciones pendientes. |
| `Queue.Skip()` | Salta la acción actual. |
| `Queue.Describe(acción)` | Texto de una acción para la lista. |
| `Queue.Next()` | Ejecuta el siguiente paso. Solo debe llamarse desde un clic o una tecla. |
| `Queue.Phase()` | Fase del paso en curso. |

### UI.lua — ventana

| Función | Qué hace |
|---|---|
| `UI.Toggle()` | Muestra u oculta la ventana. |
| `UI.OnAuctionHouse(abierta)` | Coloca la ventana junto a la subasta o la oculta. |
| `UI.SetStatus(texto)` | Cambia la línea de estado. |
| `UI.Refresh()` | Repinta la lista de pasos. |
| `UI.UpdateFooter()` | Repinta el pie. |
| `UI.ShowImport()` | Abre el cuadro para pegar una ruta. |
| `Oroboros_Next()` | Función global del atajo de teclado; equivale al botón **Siguiente**. |

## Límites conocidos

- **Sin probar en el juego real.** Lo que más necesita verse: la lectura del banco (Forever puede usar pestañas o el sistema clásico; el addon prueba los dos), la compra de equipo en el libro, las facturas del correo y el tooltip.
- **Sin API oficial de precios** para Forever: los datos salen del escaneo en el juego, propio o de Auctionator.
- **Auctionator no guarda profundidad ni valor de mercado:** con sus precios, la profundidad es una estimación.
- **Ventas por día estimadas** y a la baja. Más escaneos al día dan mejor estimación.
- **Correo y vendedor no automatizados:** son pasos `NOTE`.
- **El correo solo da el nombre del objeto:** la venta se anota si el addon ya conoce ese objeto.
- **Lo fabricado no pasa por el libro de compras:** en la cartera su coste es el previsto.
- **En catalog.json, los multiplicadores de eventos y progresión son suposiciones**; las fechas y los objetos son reales.
- **Las subastas duran como mucho 24 h en Forever**: lo que no se venda en ese tiempo vuelve por correo y hay que publicarlo otra vez (el plan cuenta con 48 h para vender).
- **Encantamientos sobre equipo:** no se evalúan, porque no producen un objeto vendible.
- **Farmeo:** la estimación de sitios nuevos sale de AzerothCore (WotLK), solo con materiales. Los niveles de profesión de los nodos son los del clásico. Lo que mides corrige las dos cosas.

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| El addon no aparece en la lista | La carpeta debe llamarse `Oroboros` y contener `Oroboros.toc`. Revisa el número de `## Interface:`. |
| El exportador dice que no hay `OroborosDB` | No se ha escrito el archivo: haz `/reload` o sal del juego. |
| "Escaneo completo disponible en…" | El juego limita el escaneo completo a uno cada 15 minutos, contando también el de Auctionator. |
| "El escaneo completo lo hace Auctionator…" | Escanea con Auctionator: Oroboros lee su resultado. Para el propio, `/oro scan forzar`. |
| El plan no usa las recetas de un personaje | Entra con él y abre cada profesión; luego `/reload`. |
| "Nada por debajo de…" al comprar | El precio ha subido desde el escaneo. Salta el paso o vuelve a planificar. |
| "El mercado está por debajo de tu mínimo" al vender | Alguien ha bajado el precio. No publica para no vender a pérdida. |
| No fabrica | Abre la ventana de esa profesión antes de pulsar. |
| La ruta de otro personaje no aparece al entrar | Se guarda al salir del personaje con el que la pegaste. Sal de forma normal, sin cerrar el juego a la fuerza. |
| Confianza baja en todo | Faltan días de histórico. |

## Pruebas

```
pip install -r tests/requirements.txt
python tests/run_tests.py
```

Carga el addon en Lua 5.1 con una simulación de la API de WoW, simula escaneos, compras, ventas, correo, banco y varios personajes, y ejecuta de extremo a extremo datos sintéticos → exportador → planificador → rutas, que se pasan por el lector de rutas del addon.
