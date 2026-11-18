# Fuentes de precios: Auctionator como fuente y escaneo propio como alternativa

> **Decidido e implementado (16/11/2026, v0.6.0).** El usuario activa en Auctionator su escaneo completo. Eso cambia la propuesta del apartado 6 a mejor: el resultado de `ReplicateItems` llega por `REPLICATE_ITEM_LIST_UPDATE` a todos los addons, así que **Oroboros lee el escaneo de Auctionator** sin pedir otro. Conserva mínimo, valor de mercado, cantidad y profundidad, y no hace falta leer la tabla interna de Auctionator desde el juego. Hecho:
> - `Scanner.FullScan` no llama a `ReplicateItems` si Auctionator tiene el escaneo completo activado; `/oro scan forzar` sí. El tiempo de espera cuenta también el último escaneo de Auctionator (`AUCTIONATOR_SAVEDVARS.TimeOfLastReplicateScan`).
> - Lectura pasiva del resultado ajeno, como mucho una vez cada 5 minutos.
> - `oroboros_export.py --auctionator`: mezcla `Auctionator.lua` en el SQLite (columna `src`). Gana Oroboros si tiene dato del mismo día.
> - El planificador marca la profundidad estimada (`depth_est`) y no da confianza alta con ella.
> - TOC: `## Interface: 16001, 120105` y `## OptionalDeps: Auctionator`.
> - Pruebas en Windows sin `PYTHONUTF8`.
>
> Comprobado el 18/11 en el cliente real: interfaz 16001 (cliente 1.60.1.70959), carga y escaneo completo propio (~6900 objetos con profundidad). `/oro cliente`: reino interno `CAMWOWEU5Realm5PvE`, nombres regionales `true`, `GetRegionalRulesetName()` = `nil`, sin reinos conectados. La clave `"PvE"` de Auctionator no se puede reproducir con esos datos; Oroboros mantiene `Reino-Facción`.
>
> Pendiente: validar en el juego la lectura pasiva; la clave de mercado (`"PvE"`) cuando se confirme; la búsqueda puntual de los objetos de la ruta (apartado 6c) solo hace falta si no hay escaneo completo.

Informe del 16/11/2026. Todo lo de abajo está comprobado en los archivos de la instalación (solo lectura), salvo lo marcado como **sin verificar**. Las rutas de Auctionator son relativas a `Interface/AddOns/Auctionator/`.

## 1. Lo que hay instalado

| Dato | Valor |
|---|---|
| Instalación | `F:\World of Warcraft\_forever_\` (no está en `Program Files`) |
| Cliente (`.build.info`) | versión **1.60.1.70938**, producto `wowf`, región EU, esES |
| Addon de subasta | **Auctionator 341** (13/10/2026). No hay Auctioneer ni TradeSkillMaster |
| Otros de economía | **Goblinomics v1.3.0** (13 módulos: Flips, Ledger, Workshop, Insights, Vault… y conectores para Auctionator, TSM y CraftSim). No tiene SavedVariables en `WTF`, así que no se ha cargado nunca con un personaje. No he leído su código |
| Copia previa de Oroboros/Addonero en `AddOns` | ninguna |

### Número de interfaz: nuestro TOC no coincide

- Los addons hechos para Forever declaran `## Interface: 16001` (ProItemForever, ForeverLootSparkles, NodeSight, OpenMap, Spoken, Kaliel's Tracker…). Encaja con la versión del cliente (1.60.1 → 16001).
- Los multi-versión listan los dos: Auctionator `120100, 120105, 16001, …`, Goblinomics `120100, 120105, 16001`.
- Oroboros declara solo `120105`. **Propuesta: `## Interface: 16001`** (o `120105, 16001`). Sin verificar en el juego si con 120105 carga o sale como «desactualizado». `CLAUDE.md` y `arquitectura.md` dicen «interfaz 120105»: habría que corregirlo.
- Sufijos de TOC: aparecen `_Camelot.toc` (3 addons; dos de ellos —EllesmereUIForeverEssentials y MapUtils— solo tienen ese TOC) y `_Forever.toc` (1, Offhand, que además tiene TOC base). Auctionator usa `[AllowLoadGameType camelot]` (`Auctionator.toc`, última línea). El nombre interno del sabor parece ser **camelot**. A Oroboros no le hace falta sufijo.
- Auctionator carga en Forever su código `Source_ModernAH` y de `Source_Forever` solo cambia las duraciones a **2/8/24 h** (`Source_Forever/Constants.lua:1-5`). Confirma la subasta moderna (`C_AuctionHouse`), pero nuestro `postDuration` asume 12/24/48 h (`Core.lua:9`): a validar en el juego.

## 2. Cómo escanea Auctionator

Tiene dos escaneos y **por defecto no usa `ReplicateItems`**:

| Escaneo | Cuándo | Llamada | Qué obtiene |
|---|---|---|---|
| Resumen («incremental») | opción `replicate_scan_3 = false` (por defecto, `Source/Config/Main.lua:89`) | `SendBrowseQuery` con búsqueda vacía + `RequestMoreBrowseResults` (`Source_ModernAH/IncrementalScan/Mixins/Frame.lua:65` y `:133`) | por objeto: `minPrice` y `totalQuantity` (`:117`) |
| Completo | opción activada (`Source_ModernAH/Tabs/Auctionator/Mixins/ScanButton.lua:4`) | `C_AuctionHouse.ReplicateItems()` (`Source_ModernAH/FullScan/Mixins/Frame.lua:29`), límite de 15 min (`:46`) | todas las subastas, pero solo guarda mínimo y suma de cantidad (`Source/Database/Mixin.lua:122-132`) |

Además, cualquier búsqueda normal en la subasta actualiza los precios de lo que aparece (`IncrementalScan/Mixins/Frame.lua:32-43`).

**Tu configuración** (`AUCTIONATOR_CONFIG`): `replicate_scan_3 = false`, `autoscan_2 = true`, `autoscan_interval = 15`. Es decir: al abrir la subasta hace solo el escaneo resumen si han pasado 15 min (`Source_ModernAH/Core/Mixin.lua:18-24`).

Consecuencia: **hoy Auctionator y Oroboros no chocan por el límite de `ReplicateItems`**, porque Auctionator no lo usa. Chocarían solo si activas su «escaneo completo». Sigue sin tener sentido escanear dos veces por rutina, pero el escaneo propio queda disponible sin coste cuando haga falta.

## 3. Qué guarda

Por objeto (`Source/Database/Mixin.lua:15-55`):

| Campo | Significado |
|---|---|
| `m` | último precio mínimo visto (cobre, por unidad) |
| `h[día]` | el mínimo **más alto** visto ese día |
| `l[día]` | el mínimo **más bajo** de ese día; solo se guarda si difiere de `h` |
| `a[día]` | la **mayor** cantidad total publicada vista ese día |

- Histórico: **21 días** (`price_history_days`, `Source/Config/Main.lua:111`); lo anterior se borra al escribir (`Mixin.lua:57-79`).
- `día` = días desde el 1/1/2020 en hora local (`Source/Constants/Main.lua:14`). Se calcula **una vez al cargar el addon** (`Mixin.lua:7`): si la sesión cruza la medianoche, lo escaneado después se apunta al día anterior. Comprobado: tu último escaneo fue el 15/11 a la 01:56 y está guardado como día 14.
- Claves: `"itemID"`; equipo con nivel de objeto ≥ 168 también como `"g:itemID:nivel"`; mascotas `"p:especie"` (`Source_ModernAH/Utilities/DBKeyFromBrowseResult.lua:6-16`). En tus datos las 6519 claves son `itemID` simple.
- **No guarda**: valor de mercado, número de subastas, profundidad, hora del escaneo por objeto ni ventas.
- Aparte: `AUCTIONATOR_VENDOR_PRICE_CACHE` (339 precios de venta al vendedor), `AUCTIONATOR_POSTING_HISTORY` (lo que publicas tú: `{time, price, quantity}`) y `AUCTIONATOR_SAVEDVARS.TimeOfLastBrowseScan` (inicio del último escaneo resumen).

### Reino y facción

La base es `AUCTIONATOR_PRICE_DATABASE[<clave>]`. En Forever la clave es el nombre del conjunto de reglas regional (`GetRegionalRulesetName()`, `Source_ModernAH/Variables/Main.lua:12-16`): en tu archivo es **`"PvE"`**, sin reino ni facción. Oroboros usa `Reino-Facción` (`DB.lua:55`). Si la subasta de Forever es única por región y reglas, nuestra clave parte en varios mercados lo que es uno solo: **a validar en el juego**.

### En disco

`WTF/Account/<CUENTA>/SavedVariables/Auctionator.lua` (250 KB). La carpeta de personaje solo tiene `AUCTIONATOR_CHARACTER_CONFIG`. Al salir o hacer `/reload`, la base del reino actual se guarda como **una cadena CBOR**, no como tabla Lua (`Source/Variables/Main.lua:113-119`); en tu archivo son 235 088 bytes. La he decodificado entera con un decodificador propio de 40 líneas.

Ejemplos reales (cobre por unidad):

| Objeto | `m` | `h` | `l` | `a` |
|---|---|---|---|---|
| 2592 | 100 | 8/11: 72 · 14/11: 100 | 8/11: 71 | 8/11: 11 640 · 14/11: 26 233 |
| 4358 | 36 | 12/11: 44 · 14/11: 36 | — | 12/11: 15 040 · 14/11: 12 482 |
| 2447 | 42 | 13/11: 40 · 14/11: 42 | — | 13/11: 4 762 · 14/11: 7 970 |
| 6291 | 17 | 8/11: 12 · 14/11: 17 | — | 8/11: 3 141 · 14/11: 4 044 |
| 2997 | 339 | 8/11: 274 · 14/11: 339 | — | 8/11: 2 944 · 14/11: 3 131 |

Estado de tus datos: 6519 objetos, pero **solo dos días con escaneo amplio** (8/11: 381 objetos; 14/11: 6515). Auctionator solo suma histórico los días que abres la subasta.

## 4. API para otros addons

`Auctionator.API.v1`, con el nombre del addon que llama como primer argumento (`Source/API/Internal.lua:9`):

| Función | Devuelve | Archivo |
|---|---|---|
| `GetAuctionPriceByItemID(caller, itemID)` / `…ByItemLink` | precio mínimo (`m`) o `nil` | `Source/API/v1/GetAuctionPrice.lua:1`, `:18` |
| `GetAuctionAgeByItemID` / `…ByItemLink` | días desde el último dato | `Source/API/v1/GetAuctionAge.lua:4` |
| `IsAuctionDataExactByItemID` / `…ByItemLink` | si hay precio | `Source/API/v1/IsAuctionDataExact.lua:1` |
| `GetVendorPriceByItemID`, `GetDisenchantPriceByItemID` | precio de vendedor / desencantar | `Source/API/v1/GetVendorPrice.lua:1`, `GetDisenchantPrice.lua:1` |
| `RegisterForDBUpdate(caller, callback)` | llama a `callback()` sin argumentos tras cada escaneo **y tras cada búsqueda** | `Source_ModernAH/API/v1/RegisterForDBUpdate.lua:1-19` |
| `MultiSearch*`, listas de la compra | abre búsquedas en su pestaña | `Source/API/v1/MultiSearch.lua:51`, `ShoppingLists.lua` |

**La API pública solo da el precio mínimo.** La cantidad y el histórico existen, pero solo por dentro: `Auctionator.Database:GetPriceHistory(clave)` (`Source/Database/Mixin.lua:155`, devuelve por día `minSeen`, `maxSeen`, `available`) y la tabla `Auctionator.Database.db`. No son API: pueden cambiar con una actualización.

Licencia: «All Rights Reserved», y su `AGENTS.md` pide a los asistentes de IA no usar el repositorio como base. Lo que se propone aquí es llamar a su API y leer tu propio archivo de datos; **no se copia código suyo** (el decodificador CBOR es nuestro).

## 5. Qué le falta a Oroboros si los precios vienen de Auctionator

| Dato de Oroboros | Dónde se usa | ¿Lo da Auctionator? | Efecto |
|---|---|---|---|
| Precio mínimo | coste de reactivos, vista `recipe_cost` | Sí (`m`) | ninguno |
| Valor de mercado (media del 15 % más barato) | precio de venta, medianas 7/14 d, tendencia (`oroboros_plan.py:137-148`), todas las ideas | No | se usa el mínimo: ventas estimadas algo a la baja (prudente) y coste de compra algo optimista (`buy_unit`, `:192-199`) |
| Cantidad publicada | tope del 30 % (`:254-255`, `:719-720`), texto, «oferta que se seca» (`oroboros_ideas.py:234-240`), progresión (`:64-75`, `:303`) | Sí, por día (`a`), pero es el **máximo** del día, no el último | casi ninguno |
| Profundidad (uds a ≤ mín ×1,10/1,25/1,5/2) | `buy_unit` (`:192-199`), cantidad de reventas (`:497`), tamaño de ideas (`oroboros_ideas.py:381-384`) | **No** | el planificador ya tiene un sustituto inventado: cantidad × 0,2/0,45/0,75/0,95 (`:184-185`). Puede proponer comprar más de lo que hay barato |
| Ventas por día | confianza (`:164-169`), cantidades, filtros de ideas | No lo da nadie: Oroboros lo estima con las bajadas de cantidad entre días (`:142-147`) | igual que hoy; con `a` sale la misma estimación |
| Histórico ≥ 14 días | mediana 14 d, rebote (≥ 7 d), ciclo semanal (≥ 13 d), oferta que se seca (≥ 10 d) | Sí: 21 días, pero solo los días con escaneo | suficiente; nuestra foto diaria lo alarga a 30 |
| Hora del dato | `age_h` | Solo el día, y `TimeOfLastBrowseScan` global | aviso de antigüedad menos fino |
| Nº de subastas | no se usa en el planificador | No | ninguno |

Resumen: **lo único que se pierde de verdad es la profundidad** (y, con ella, la precisión del valor de mercado).

## 6. Propuesta

### (a) En el juego

- TOC: `## OptionalDeps: Auctionator` para que cargue antes.
- Módulo nuevo `Sources.lua` con la fuente de precios: `auctionator` si existe `Auctionator.API.v1`; si no, `propia`.
- Con Auctionator cargado, `Scanner.FullScan` no llama a `ReplicateItems`: avisa de que los precios vienen de Auctionator (que ya escanea solo al abrir la subasta).
- **Foto diaria**: nos registramos con `RegisterForDBUpdate("Oroboros", …)` y, agrupando avisos (salta con cada búsqueda), copiamos a nuestro mercado `min = m`, `mv = m`, `qty = a[hoy]`, sin profundidad, marcado `src = "atr"`. Alimenta `prices` e `history` como ahora.
- Para tener cantidad hay que leer `Auctionator.Database.db` (interno). Propongo leerlo dentro de `pcall` y, si falla o cambia de forma, caer a la API pública (solo precio, para los objetos que Oroboros conoce: recetas, reactivos, inventario y apuestas).
- Guardamos en el mercado la clave de Auctionator (`Auctionator.State.CurrentRealm`, p. ej. `"PvE"`) para que el exportador sepa emparejarlos.
- Un registro con profundidad real (búsqueda propia) de hoy no se pisa con uno de Auctionator.

### (b) Fuera del juego

- `oroboros_export.py --auctionator [ruta]`: por defecto busca `Auctionator.lua` junto a `Oroboros.lua`. Decodifica el CBOR (sin dependencias nuevas), convierte los días a fecha y vuelca `m`, `h`/`l` y `a` a `prices` e `history`.
- Mezcla por objeto y día: gana el registro de Oroboros si tiene profundidad; si no, el de Auctionator. Columna nueva `source` en `prices`.
- Ventaja inmediata: importa de golpe los días que Auctionator ya tiene, sin esperar a nuestras fotos, y funciona aunque Oroboros no se haya cargado ese día.
- El planificador marca la profundidad estimada (`depth_est`) y con ella baja la confianza y recorta reventas e ideas.

### (c) Lo que falta

- **Profundidad: búsquedas puntuales solo de los objetos del plan.** Botón «Actualizar objetos de la ruta»: recorre los `BUY`/`SELL`/`HOLD` de la ruta pegada con `Scanner.Search` (ya existe y guarda profundidad, valor de mercado y nº de subastas), espaciadas para no saturar. Flujo: plan con profundidad estimada → pegar ruta → actualizar → (opcional) reexportar y replanificar con datos exactos. La ejecución ya está protegida: `Queue` busca precio fresco antes de cada compra y respeta el precio máximo.
- **Valor de mercado** fuera del plan: renunciamos; se usa el mínimo.
- **Nº de subastas y hora exacta**: renunciamos.
- **Escaneo propio**: se mantiene tal cual cuando Auctionator no está. Con Auctionator, queda como `/oro scan completo` manual para quien quiera profundidad de todo el mercado; hoy no choca con tu configuración.

### Cosas a decidir

1. ¿Leemos la tabla interna de Auctionator (da cantidad; puede romperse con una actualización, con caída a la API) o solo la API pública (solo precio)? Recomiendo la interna con `pcall`.
2. Clave de mercado: ¿pasamos a la de reglas regionales (`"PvE"`) si se confirma en el juego que la subasta es única?
3. ¿Dejamos el escaneo completo propio accesible a mano con Auctionator cargado? Recomiendo que sí.

## 7. Otros hallazgos

- `python tests/run_tests.py` **falla en Windows** tal cual: `oroboros_export.py:282` y `:285` imprimen «→» y la consola es cp1252 (`UnicodeEncodeError`), así que el SQLite no se crea. Con `PYTHONUTF8=1` pasan las 84 comprobaciones y acaba en «TODO OK». Arreglo propuesto: fijar UTF-8 en la salida de las herramientas.
- Interfaz 16001 y duraciones 2/8/24 h (apartado 1).
- Goblinomics cubre parte de lo que hace Oroboros (libro, reventas, fabricación) y ya trae conector para Auctionator. No es parte de esta tarea, pero conviene saber que está instalado.
