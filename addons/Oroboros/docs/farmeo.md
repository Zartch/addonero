# Dónde farmear para vender en la subasta

Diseño del 20/11/2026. Estado: **aprobado y construido el 20/11** (falta probarlo en el juego; ver «Cambios al construirlo» al final). Enfoque elegido por el usuario (ajustado el 20/11): **la base es lo que mide el addon**; AzerothCore es solo una **estimación inicial** para proponer sitios donde aún no se ha farmeado, y la recolección sale de GatherMate2 (datos de Forever). Se calcula fuera del juego.

## Para qué

El usuario quiere que Oroboros **proponga dónde ir a farmear** para vender en la subasta, también en sitios donde aún no ha estado. Condiciones:
- criaturas de **mundo abierto**;
- **sin grupos de élites**;
- según el **nivel** del personaje.

Se calcula **fuera del juego**, como el plan. Dentro solo entra un resumen pequeño, para no alargar la carga ni el `/reload`.

## Lo que hay (comprobado el 20/11)

- El juego **no da a los addons tablas de botín**. Lo que sí ve un addon mientras se juega: cada muerte, el botín al despojar (y de qué criatura sale), el nivel y la clasificación de la criatura que tienes como objetivo, y la zona.
- **AzerothCore** (servidor de código abierto de WotLK, licencia AGPL-3.0) publica la base de datos del mundo clásico. Las tablas necesarias pesan unos 45 MB y se descargan de GitHub:
  - `creature_template`: `entry`, `name`, `minlevel`, `maxlevel`, `rank` (0 normal, 1 élite, 2 élite rara, 3 jefe, 4 rara), `type`, `unit_flags`, `lootid`, `skinloot`, `mingold`, `maxgold`;
  - `creature`: cada aparición, con `id1`, `map`, `zoneId`, `areaId` y `spawntimesecs`;
  - `creature_loot_template`, `reference_loot_template`, `skinning_loot_template`;
  - `item_template`: `SellPrice`, `Quality`, `Bonding` y si es de misión.
- **Los números de objeto de Forever coinciden con los clásicos** (comprobado con pociones, hierbas y paños). Los de criatura, previsiblemente también.
- **Pero el botín de Forever no es el clásico** (comprobado el 20/11 en otra sesión, al estudiar un addon de equipo): casi la mitad del equipo es nuevo (números de objeto ≥ 250000), y el botín de los objetos antiguos cambió de criaturas y de porcentajes. Por eso AzerothCore solo vale como **aproximación para materiales** (paño, cuero, carne, polvos, objetos grises de vendedor y oro suelto), no para equipo.
- Otras fuentes de Forever, por si hacen falta más adelante: **Pro Item Forever** (instalado, sin licencia: 866 objetos con origen y porcentaje, centrado en equipo; se puede leer del disco, no copiar) y foreverchanges.pro (no permite copiar en bloque). Quedan fuera de este diseño.
- **GatherMate2_Data/Forever** (instalado; 629 KB): nodos de hierbas (~14 650), minerales, pesca y tesoros, con la forma `[uiMapID] = { [coordenada] = tipoDeNodo }`.
- Precios: el archivo (`daily`) y el precio de vendedor (`items.vendor_sell` o, si falta, `item_template.SellPrice`).

## Objetivos

- Para cada personaje: las **mejores zonas** para su nivel, con oro por hora estimado, las criaturas que matar y lo que sueltan que más vale.
- Lo mismo para **recolectar** (hierbas, minerales, pesca), según las profesiones del personaje.
- **Lo medido manda**: donde el usuario ya ha farmeado, la cifra es la suya (lo que le cayó y a qué ritmo). La estimación de AzerothCore solo sirve para **proponer sitios por explorar**, marcada como «estimación inicial (aproximada)».
- Verlo en la página del plan (pestaña **Farmear**) y en el juego (`/oro farmear` y un aviso al entrar en una zona).

## Fuera de alcance

- Rutas, flechas o navegación por el mapa.
- Mazmorras, bandas, criaturas élite, élites raras y jefes.
- Zonas exclusivas de Forever que no están en AzerothCore: solo aparecen si el usuario ya ha farmeado allí (medido) o si son de recolección (GatherMate2 sí las tiene).
- Cualquier automatización del farmeo. Es botting.

## Lo que sería un fracaso

- Dar cifras que parezcan exactas sin serlo. Cada zona lleva su **origen** (estimado o medido) y su **confianza**, y el oro por hora se muestra como un rango.
- Proponer farmear cosas que el mercado no absorbe: 300 paños por hora no se venden a su precio si se venden 40 al día.
- Alargar la carga del juego: el archivo para el juego ocupa como mucho ~50 KB.
- Subir a git los datos de AzerothCore o datos reales del usuario.

## Enfoques considerados

| Enfoque | Decisión |
|---|---|
| **Medición propia como base + AzerothCore como estimación inicial de materiales + GatherMate2** | **Elegido por el usuario** (ajustado el 20/11: antes AzerothCore era la base y lo medido la corrección) |
| Solo medición propia (exacta, pero no propone sitios nuevos) | Descartado como única fuente: no propondría dónde ir por primera vez |
| AzerothCore como base | Descartado: el botín de Forever cambió y las cifras serían engañosas |
| Wowhead (tiene datos de Forever) | Descartado: sus condiciones no permiten copiarlos |
| Cargar la base de botín dentro del juego | Descartado: decenas de MB y cargas lentas |

## Diseño

**Orden de construcción**: primero la medición en el juego (sección 5), que da valor desde el primer día y es la base de todo. Después la estimación inicial (secciones 1 a 3) y la recolección (4). Por último el resultado (6).

### 1. Fuentes (fuera del juego, `tools/oroboros_farm.py`)

- `--descargar`: baja las seis tablas de AzerothCore a `work/fuentes/azerothcore/` (ignorado en git), con la fecha en un archivo. Fuente: repositorio `azerothcore/azerothcore-wotlk`, rama `master`, `data/sql/base/db_world/<tabla>.sql` (comprobado el 20/11: se descargan; unos 45 MB). Las tablas `*_dbc` de ese repositorio (zonas, facciones) son solo correcciones parciales, así que no sirven. Solo se descarga cuando no están o con `--descargar` explícito; el vigilante nunca descarga.
- Lector de los volcados SQL (`INSERT INTO ... VALUES (...)`) que extrae solo las columnas necesarias.
- Lector de GatherMate2_Data/Forever desde la carpeta de WoW (`find` como ProfessionDB).

### 2. Valor de una criatura

- **Candidatas** (sin tabla de facciones no se puede saber «hostil» con exactitud; filtro aproximado que corrige lo medido):
  - sin servicios (`npcflag = 0`: deja fuera vendedores, instructores, posaderos…);
  - sueltan botín u oro (`lootid > 0` o `maxgold > 0`);
  - fuera de las seis capitales (`zoneId` 1519 Ventormenta, 1537 Forjaz, 1657 Darnassus, 1637 Orgrimmar, 1638 Cima del Trueno, 1497 Entrañas);
  - `rank = 0`;
  - no son alimañas (`type` 8);
  - no tienen las marcas de «no atacable» ni «no seleccionable» en `unit_flags`;
  - aparecen en los continentes de mundo abierto (`map` 0 o 1).
- **Grupos de élites**: en cada subzona (`areaId`), si al menos el 30 % de las apariciones que pasan el filtro anterior (sin contar el `rank`) son élites, la subzona se marca «zona de élites» y sus criaturas normales se descartan.
- **Valor por muerte** = oro medio ((mingold + maxgold) / 2) + Σ (probabilidad × cantidad media × valor unitario).
  - Las referencias (`reference_loot_template`) se expanden.
  - En un grupo de botín (`groupid > 0`) cae como mucho uno: los objetos con probabilidad explícita la usan, y los que tienen 0 se reparten lo que queda a partes iguales.
  - Se excluyen los objetos de misión (`QuestRequired`) y los ligados al recogerlos que no se venden al vendedor.
- **Qué cuenta la estimación inicial**: solo materiales y objetos de vendedor, porque el botín de equipo de Forever cambió. En concreto: oro suelto; objetos de clase «artículos de comercio» (`class` 7), consumibles (`class` 0) y componentes (`class` 5), y objetos grises (`Quality` 0) a precio de vendedor. El equipo (armas y armaduras, `class` 2 y 4) **no se estima**: aparece como «equipo: sin estimar» hasta que se mide.
- **Valor unitario**: mediana de 7 días del valor de mercado **del mercado del personaje** (el mismo criterio que el plan) si el objeto se vende en la subasta; si no, el precio de vendedor.
- **Versión del mundo**: Forever es 1–60 y solo los continentes clásicos (mapas 0 y 1). AzerothCore es la base de WotLK (3.3.5): algún porcentaje de botín difiere del de Vanilla. Se acepta como **estimación de partida**; lo medido la corrige. Una base más fiel a Vanilla (VMaNGOS) se distribuye en 7z, que la biblioteca estándar de Python no abre: queda como mejora futura.
- **Saturación**: si lo que caería en una hora supera lo que la subasta vende en un día (`vol`), lo que pasa de esa cantidad vale el precio de vendedor. La zona lo avisa.
- **Desuello**: si el personaje tiene Desuello y la criatura tiene `skinloot`, se suma su valor (mismo cálculo).

### 3. Ritmo y nivel

- **Criaturas por hora** (suposición, se corrige con lo medido): 40 por hora a tu mismo nivel, +10 % por cada nivel por debajo (como mucho ×2). Tope: apariciones × 3600 / `spawntimesecs` × 0,5 (no te las encuentras todas).
- **Nivel**: criaturas con `maxlevel` ≤ nivel del personaje + 1 y `minlevel` ≥ nivel − 12.
- **Oro por hora de una subzona** = Σ (criaturas por hora × valor por muerte), repartiendo el ritmo según el peso de las apariciones de cada criatura en la subzona. Se da como rango: el de la estimación ±30 % y, si está medido, el de lo medido.

### 4. Recolección

- Por mapa: número de nodos de cada tipo y valor del objeto que dan (hierba, mineral, pez).
- **Nodos por hora** (suposición): 30 por hora en un mapa con nodos densos. Se corrige con lo medido.
- Solo con las profesiones del personaje.
- **Nivel de profesión**: el que pide cada tipo de nodo, si GatherMate2 o ProfessionDB lo traen. Si no, «nivel sin comprobar», como en «qué aprender».

### 5. Medición en el juego (`Oroboros/Farm.lua`)

- Cuenta una muerte por cada cadáver de criatura que despojas (cambiado el 20/11: el registro de combate, `COMBAT_LOG_EVENT_UNFILTERED`, es una acción prohibida para los addons en la API de Midnight y el juego bloqueaba Oroboros). Lo que no suelta nada no cuenta.
- Apunta el botín al despojar: con `LOOT_OPENED`, recoge `GetLootSourceInfo` (de qué criatura sale cada objeto), objetos, cantidades y dinero.
- Cuando tienes una criatura como objetivo, guarda su nivel y su clasificación (`UnitClassification`).
- Calcula el tiempo activo: suma de los huecos entre muertes seguidas de menos de 2 minutos.
- Guarda **sumas por criatura y subzona** en `OroborosDB.farm`: muertes, botín, cobre, segundos activos, nivel y clasificación. Pocos KB.
- **Qué subzona es**: el juego da el nombre de la subzona (`GetSubZoneText`) y el mapa (`C_Map.GetBestMapForUnit`), no el `areaId`. El addon traduce a su nombre en español cada `areaId` de `Farmeo.lua` (`C_Map.GetAreaInfo`), los compara con la subzona actual y guarda esa tabla `areaId → nombre` en `OroborosDB.farmAreas`. Lo medido se guarda con el `areaId` que coincide, o con el nombre si no coincide ninguno. El exportador empareja estimado y medido con esa tabla.
- **«Medido»** = oro recogido + botín valorado a los precios de hoy (como hace Goblinomics), no lo cobrado al vender.
- Recolección: nodos recogidos y objetos (los hechizos de recolección, `UNIT_SPELLCAST_SUCCEEDED` y el botín).
- **Tiempo de recolección (28/11):** un solo reloj para muertes y nodos; el hueco hasta un nodo cuenta para la recolección si es de menos de 3 minutos (hasta una muerte, 2). Así el ritmo de farmeo del plan incluye las plantas sin contar dos veces el mismo rato. Los nodos de antes no tienen tiempo: cuentan lo que suele costar un nodo (si no hay ninguno con tiempo, no cuentan).
- **Sesión (28/11):** además del tiempo activo, cada criatura y cada recolección guardan `span`, los huecos de hasta 10 minutos (descansos, moverse entre grupos). El ritmo del plan usa la parte activa de la sesión para amortizar esos ratos y suma 10 minutos por hora de viajes a vender.
- **Donde ya has farmeado (28/11), por zona:** «Cuando pasaste por <zona> ganaste X en Y activos: Z/h contando descansos y viajes a vender» y, dentro, cada criatura con todas sus subzonas juntas (muertes, por muerte, ganado, oro por hora, lo que más soltó) y lo recogido. Lo que va a `Farmeo.lua` sigue siendo por subzona.
- El exportador lo pasa al archivo (tablas `farm_obs`).
- **Lo medido manda**:
  - con **30 muertes o más** de una criatura en una subzona, su valor por muerte y su ritmo son los medidos, sin mezclar;
  - con menos, se mezcla: peso de lo medido = muertes / 30, y el resto, la estimación inicial. Si no hay estimación (criatura de Forever que no está en AzerothCore), cuenta solo lo medido y la confianza baja;
  - el equipo que suelte se valora a partir de lo medido (precio de la subasta de cada pieza, o de vendedor), como cualquier otro objeto.
- **Confianza**:
  - **alta**: medido con ≥ 30 muertes y ≥ 20 minutos activos;
  - **media**: con medición parcial;
  - **baja**: solo estimación inicial.

### 6. Resultado

- **Pestaña «Farmear»** en la página del plan, para cada personaje, en tres bloques:
  - **«Donde ya has farmeado»**, con lo medido: oro por hora real, muertes, tiempo y lo que más te dejó;
  - **«Por explorar»**, las 10 mejores subzonas de la estimación inicial, marcadas «aproximado: solo materiales»;
  - **«Recolección»**, las 5 mejores.
  - Oro por hora (rango) y nivel de las criaturas.
  - Qué matar, con sus 3 objetos más valiosos.
  - Aviso de saturación.
  - Origen (estimado o medido) y confianza.
- **En el juego**: `tools/oroboros_farm.py` escribe `Oroboros/Farmeo.lua` (ignorado en git) con las 15 mejores subzonas por tramo de 5 niveles y los ids de zona.
  - `/oro farmear` abre un panel con el estilo actual: primero las medidas y después las «por explorar», para el nivel del personaje.
  - Al entrar en una subzona de la lista, una línea en el chat: «Farmeo aquí: ≈ X/h (estimado)».
  - Los nombres de zona se resuelven en el juego (`C_Map.GetAreaInfo`, `C_Map.GetMapInfo`), y el addon guarda una caché de esos nombres para que la página los muestre en español.
- El vigilante regenera `Farmeo.lua` junto al plan cuando ya hay fuentes descargadas.

## Restricciones

- Python solo con biblioteca estándar. Lua 5.1, interfaz 16001, todo en `ns`.
- Los datos de AzerothCore no se suben al repositorio: se descargan a `work/`.
- Cada parte, con pruebas en `tests/run_tests.py`, usando volcados de AzerothCore y nodos de GatherMate2 en miniatura escritos por la prueba.

## Cambios al construirlo (20/11)

- **Cuadrículas en vez de subzonas.** En los volcados reales de AzerothCore, `creature.zoneId` y `areaId` vienen a 0. Las criaturas se agrupan en cuadrículas de 400 m del continente (`CELL`), por su posición. Una cuadrícula con ≥ 20 % de PNJ con servicios (`npcflag` ≠ 0) se considera ciudad o campamento y queda fuera (`CITY_SHARE`). La regla de capitales se mantiene, pero con zona 0 no hace nada.
- **Nombres resueltos en el juego.** En lugar de `C_Map.GetAreaInfo` por `areaId`, `FarmPanel.lua` traduce la posición media de cada cuadrícula con `C_Map.GetMapPosFromWorldPos` y guarda la zona y las coordenadas en `OroborosDB.farmPlaces`; los mapas de la recolección van a `farmMaps`. El orden x/y que espera el juego se calibra con la posición del jugador (`UnitPosition` frente a `C_Map.GetPlayerMapPosition`). Se supone que (`position_x`, `position_y`) de AzerothCore son los dos primeros valores de `UnitPosition`. El exportador guarda los nombres en `meta` del archivo y la página los usa.
- **Aviso al entrar:** el addon compara la cuadrícula del jugador con las de su tramo de nivel y, para lo medido, la subzona. Salta con los eventos de cambio de zona y de subzona.
- **Lo medido se empareja por criatura**, sumando todas sus subzonas. La combinación es W × medido + (1 − W) × estimado, donde W es la media de min(1, muertes/30) ponderada por las apariciones. «Medido» usa el oro y los objetos que soltaron, al ritmo de muertes estimado. Lo medido por subzona se muestra aparte («Donde ya has farmeado»), con su oro por hora real.
- **Recolección:** el botín de cada tipo de nodo sale de los nodos de AzerothCore con el mismo nombre (`gameobject_template` tipo 3 → `gameobject_loot_template`). Todos los nodos de Forever lo tienen. Ni GatherMate2 ni ProfessionDB dan el nivel de profesión, así que va en `tools/gather_skill.json`, con niveles del clásico sin comprobar en Forever. El Loto negro está marcado como raro: GatherMate2 guarda cada punto donde ha salido, pero solo aparece en uno de vez en cuando, y sin esto inflaba el oro por hora a más de 100 de oro. En Forever en español, Herboristería se llama «Botánica».
- **`Farmeo.lua`:**
  - las 15 mejores cuadrículas de cada tramo de 5 niveles (0 a 60);
  - la recolección, por tramos de 25 de nivel de profesión;
  - lo medido.

  Con los datos reales ocupa unos 40 KB. Generarlo, con el plan, tarda unos 20 s.

## Decisiones del constructor (propuestas)

- Las cifras de ritmo de la estimación inicial (40/h, +10 % por nivel, ×0,5 de apariciones, 30 nodos/h), el 30 % para «zona de élites», el margen de nivel (+1 / −12), las 30 muertes y 20 minutos para fiarse de lo medido, y las clases de objeto que entran en la estimación. Van como constantes con nombre y se documentan.
- Tablas exactas de `farm_obs` en el archivo y formato compacto de `Farmeo.lua`.
- Diseño visual del panel `/oro farmear`, con el estilo actual.
