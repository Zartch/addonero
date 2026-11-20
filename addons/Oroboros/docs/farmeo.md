# Dónde farmear para vender en la subasta

Diseño del 20/11/2026. Estado: **propuesta revisada, pendiente de aprobar**. Enfoque elegido por el usuario: base de datos de un emulador + nodos de GatherMate2 + lo que mide el addon, calculado fuera del juego.

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
- **GatherMate2_Data/Forever** (instalado; 629 KB): nodos de hierbas (~14 650), minerales, pesca y tesoros, con la forma `[uiMapID] = { [coordenada] = tipoDeNodo }`.
- Precios: el archivo (`daily`) y el precio de vendedor (`items.vendor_sell` o, si falta, `item_template.SellPrice`).

## Objetivos

- Para cada personaje: las **mejores zonas** para su nivel, con oro por hora estimado, las criaturas que matar y lo que sueltan que más vale.
- Lo mismo para **recolectar** (hierbas, minerales, pesca), según las profesiones del personaje.
- **Aprender de lo que juega el usuario**: donde ya ha farmeado, la estimación se sustituye o se corrige con lo que de verdad le cayó y a qué ritmo.
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
| **AzerothCore + GatherMate2 + medición propia** | **Elegido por el usuario** |
| Solo medición propia (exacta, pero no propone sitios nuevos) | Descartado como única fuente; queda como corrección |
| Wowhead (tiene datos de Forever) | Descartado: sus condiciones no permiten copiarlos |
| Cargar la base de botín dentro del juego | Descartado: decenas de MB y cargas lentas |

## Diseño

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

- Cuenta las muertes que haces tú (`COMBAT_LOG_EVENT_UNFILTERED`, `PARTY_KILL` con origen el jugador o su mascota).
- Apunta el botín al despojar: con `LOOT_OPENED`, recoge `GetLootSourceInfo` (de qué criatura sale cada objeto), objetos, cantidades y dinero.
- Cuando tienes una criatura como objetivo, guarda su nivel y su clasificación (`UnitClassification`).
- Calcula el tiempo activo: suma de los huecos entre muertes seguidas de menos de 2 minutos.
- Guarda **sumas por criatura y subzona** en `OroborosDB.farm`: muertes, botín, cobre, segundos activos, nivel y clasificación. Pocos KB.
- **Qué subzona es**: el juego da el nombre de la subzona (`GetSubZoneText`) y el mapa (`C_Map.GetBestMapForUnit`), no el `areaId`. El addon traduce a su nombre en español cada `areaId` de `Farmeo.lua` (`C_Map.GetAreaInfo`), los compara con la subzona actual y guarda esa tabla `areaId → nombre` en `OroborosDB.farmAreas`. Lo medido se guarda con el `areaId` que coincide, o con el nombre si no coincide ninguno. El exportador empareja estimado y medido con esa tabla.
- **«Medido»** = oro recogido + botín valorado a los precios de hoy (como hace Goblinomics), no lo cobrado al vender.
- Recolección: nodos recogidos y objetos (los hechizos de recolección, `UNIT_SPELLCAST_SUCCEEDED` y el botín).
- El exportador lo pasa al archivo (tablas `farm_obs`). Con **30 muertes o más** de una criatura, su valor por muerte medido sustituye al estimado, y el ritmo medido sustituye a la suposición.

### 6. Resultado

- **Pestaña «Farmear»** en la página del plan, para cada personaje: las 10 mejores subzonas de criaturas y las 5 mejores de recolección.
  - Oro por hora (rango) y nivel de las criaturas.
  - Qué matar, con sus 3 objetos más valiosos.
  - Aviso de saturación.
  - Origen (estimado o medido) y confianza.
- **En el juego**: `tools/oroboros_farm.py` escribe `Oroboros/Farmeo.lua` (ignorado en git) con las 15 mejores subzonas por tramo de 5 niveles y los ids de zona.
  - `/oro farmear` abre un panel con el estilo actual: las mejores para el nivel del personaje.
  - Al entrar en una subzona de la lista, una línea en el chat: «Farmeo aquí: ≈ X/h (estimado)».
  - Los nombres de zona se resuelven en el juego (`C_Map.GetAreaInfo`, `C_Map.GetMapInfo`), y el addon guarda una caché de esos nombres para que la página los muestre en español.
- El vigilante regenera `Farmeo.lua` junto al plan cuando ya hay fuentes descargadas.

## Restricciones

- Python solo con biblioteca estándar. Lua 5.1, interfaz 16001, todo en `ns`.
- Los datos de AzerothCore no se suben al repositorio: se descargan a `work/`.
- Cada parte, con pruebas en `tests/run_tests.py`, usando volcados de AzerothCore y nodos de GatherMate2 en miniatura escritos por la prueba.

## Decisiones del constructor (propuestas)

- Las cifras de ritmo (40/h, +10 % por nivel, ×0,5 de apariciones, 30 nodos/h), el 30 % para «zona de élites», el margen de nivel (+1 / −12) y las 30 muertes para fiarse de lo medido. Van como constantes con nombre y se documentan.
- Tablas exactas de `farm_obs` en el archivo y formato compacto de `Farmeo.lua`.
- Diseño visual del panel `/oro farmear`, con el estilo actual.
