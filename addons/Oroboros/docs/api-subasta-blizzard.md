# Subasta sin entrar al juego: la API de Blizzard y cómo estiman las ventas los demás

Informe del 23/11/2026. Responde a dos preguntas del usuario:

1. ¿De dónde sacan los datos Auctionator, Auctioneer, TSM y las webs? ¿Se puede automatizar la extracción y el seguimiento de precios sin entrar al juego?
2. ¿Cómo calculan las unidades vendidas por objeto?

El informe se escribió sin acceso a los servidores de Blizzard, con fuentes de la comunidad. **El apartado 0 recoge lo comprobado después con llamadas reales** (23/11/2026); donde no coincida con el resto del informe, manda el apartado 0.

## 0. Comprobado con llamadas reales (23/11/2026, fase A)

Desde el PC del usuario, con su cliente de `develop.battle.net` y el script de prueba `work/api_probe.py` (no va a git). **La API de Forever funciona** y responde casi como decía el informe. Diferencias y detalles:

**Rutas y cabeceras**
- Token con `client_credentials`: válido 24 h (la cabecera `blizzard-token-expires` de cada respuesta lo confirma).
- `ruleset/index` da las reglas 1, 2, 3 y 15. `ruleset/{r}/auctions/index` da las 15 casas con su nombre.
- **La regla no importa**: `ruleset/1/…/111`, `2`, `3` y `15` devuelven exactamente la misma foto (mismos `id`). Se usa la 2.
- La raíz de una casa normal trae `id`, `name` («Casa de subastas de la Alianza»), `auctions` y enlaces; la de materiales solo `auctions`.
- `last-modified` llega **en minúsculas** (hay que leer las cabeceras sin distinguir mayúsculas).
- **`HEAD` da 404.** Para no bajar nada si no ha cambiado: `GET` con `If-Modified-Since` = el último `last-modified` → **304** sin cuerpo (0,2 s). Con una fecha anterior → 200.
- Con `Accept-Encoding: gzip` llega comprimido (unas 10 veces menos). Una casa grande: 1,7 MB comprimida (16 MB de JSON) y menos de 1 s.

**Casas** (los grupos de tres del informe son correctos; 112, 115 y 118 están vacías):

| Grupo | Alianza | Horda | Aguasnegras |
|---|---|---|---|
| 1 | 110 | 113 | 116 |
| 2 | **111 (la nuestra)** | 114 | 117 |
| 3 | 112 (vacía) | 115 (vacía) | 118 (vacía) |
| 4 | 119 | 120 | 121 |
| 5 | 123 | 124 | 125 |

Tamaño de la foto del 23/11 a las 16:23 UTC (subastas normales / de materiales; unidades de materiales; KB comprimidos de las dos):

| Casa | Normales | Materiales | Unidades de mat. | KB gzip |
|---|---|---|---|---|
| 110 | 160 392 | 124 979 | 2 793 240 | 2834 |
| **111** | **161 410** | **130 011** | **3 087 042** | **2947** |
| 113 | 158 952 | 147 707 | 2 775 635 | 3061 |
| 114 | 152 011 | 129 641 | 2 394 537 | 2788 |
| 116 | 17 707 | 32 541 | 659 751 | 504 |
| 117 | 18 409 | 32 035 | 567 253 | 512 |
| 119 | 23 793 | 25 793 | 400 029 | 506 |
| 120 | 13 623 | 16 421 | 190 197 | 312 |
| 121 | 439 | 1 093 | 8 779 | 17 |
| 123 | 16 864 | 21 055 | 288 602 | 394 |
| 124 | 17 811 | 21 078 | 342 062 | 403 |
| 125 | 502 | 1 285 | 20 037 | 20 |

**Campos reales**
- Normal: `{"id": 220983487, "item": {"id": 211786}, "buyout": 100, "quantity": 1, "time_left": "SHORT"}`. `item` puede traer además `bonus_lists`, `context` y `modifiers` (equipo). Unas pocas llevan `bid` (puja) y alguna solo `bid`, sin `buyout`.
- Materiales: `{"id": 220996873, "item": {"id": 8170}, "quantity": 57, "unit_price": 2450, "time_left": "SHORT"}`.
- **`buyout` es por unidad en la práctica**: en las 15 casas **todas** las subastas normales tienen `quantity = 1`. Los materiales traen `unit_price`. Comparado con el escaneo propio de la casa 111, la mediana de mínimo API / mínimo del juego es 1,000 tanto en normales como en materiales.
- Ningún objeto sale a la vez en normales y en materiales.
- **Los materiales no se agrupan por precio**: cada publicación es una subasta con su `id` (mediana de 37 subastas por objeto y hasta 1233). Por eso se ven las compras parciales (baja `quantity` del mismo `id`).
- Los `id` de subasta son crecientes y compartidos por todas las casas (normales y materiales mezclados).

**Nuestra casa: la 111.** Mínimo por objeto de cada casa contra el escaneo completo propio (mercado `CAMWOWEU5Realm5PvE-Alliance`, el único del archivo). Foto de las 16:23 UTC; escaneos del 23/11 a las 12:57 (31) y a las 00:28 (30) y del 22/11 a las 10:39 (26), hora local:

| Casa | Igual (esc. 31) | ±5 % (esc. 31) | Igual (esc. 30) | Igual (esc. 26) |
|---|---|---|---|---|
| 110 | 4,1 % | 23,0 % | 4,2 % | 4,6 % |
| **111** | **30,4 %** | **57,3 %** | **15,3 %** | **8,8 %** |
| 113 | 3,1 % | 21,3 % | 3,3 % | 3,0 % |
| 114 | 5,0 % | 22,9 % | 4,9 % | 4,8 % |
| 116 | 1,4 % | 9,1 % | 1,3 % | 1,3 % |
| 117 | 2,0 % | 8,8 % | 1,9 % | 2,0 % |
| 119 | 1,9 % | 9,4 % | 1,8 % | 1,9 % |
| 120 | 1,4 % | 6,9 % | 1,2 % | 1,3 % |
| 121 | 1,2 % | — | 0,9 % | 0,7 % |
| 123 | 1,5 % | 7,0 % | 1,1 % | 1,2 % |
| 124 | 1,2 % | 6,8 % | 1,3 % | 1,4 % |
| 125 | 0,4 % | — | 0,7 % | 0,3 % |

Solo la 111 destaca, y su coincidencia baja a medida que el escaneo es más viejo (30 % → 15 % → 9 %): es lo que se espera de la casa correcta, cuyos precios se mueven. Las casas grandes (110, 113, 114) tienen la misma mediana de precio (1,00) y de cantidad (unas 1,2 veces la nuestra) porque son reinos parecidos; las pequeñas (116-125) son un 50 % más caras y tienen 5 veces menos.

**Ritmo (medido el 23/11, de 16:23 a 18:23 UTC, casas 111, 114 y 117):** una foto por hora, **siempre hacia el minuto 23** (16:23, 17:23 y 18:23 UTC; Aguasnegras unos 20 s antes). Se puede bajar menos de un minuto después. Basta con preguntar cada hora pasado el minuto 25; si da 304, reintentar a los pocos minutos.

**Diferencias entre fotos seguidas** (por hora; regla del apartado 4a, «barata» = precio ≤ mínimo del objeto × 1,25 en la foto anterior):

| Casa | Tipo | Nuevas | Caducadas | Canceladas | «Vendidas» | Compras parciales |
|---|---|---|---|---|---|---|
| 111 | normales | ~38 500 | ~8 100 | ~5 900 | ~15 200 | — |
| 111 | materiales | ~36 800 (~720 000 u.) | ~5 800 | ~5 500 | ~18 400 (~480 000 u.) | ~430 (~24 000 u.) |
| 114 | normales | ~36 200 | ~8 000 | ~4 900 | ~14 600 | — |
| 114 | materiales | ~35 000 | ~5 900 | ~5 700 | ~17 000 | ~400 |
| 117 | normales | ~4 500 | ~900 | ~240 | ~1 900 | — |
| 117 | materiales | ~9 200 | ~1 600 | ~900 | ~4 200 | ~200 |

- Casi todos los objetos cambian cada hora: en la 111, 5411 de 5743 normales y 1311 de 1386 materiales.
- Las cifras de «vendidas» son muy altas para un reino: seguramente buena parte son cancelaciones para volver a publicar más barato, aunque fueran de las baratas (bots). **Hay que calibrarlas con las ventas reales del libro** antes de fiarse de ellas.
- `time_left` cambia en unas 20 000 subastas por hora: baja por tramos, así que sirve para saber la antigüedad aproximada.

**Nombres de objetos:** `GET /data/wow/item/{id}?namespace=static-forever-eu&locale=es_ES` responde, por ejemplo «Paño de lino», `quality`, `level` y `sell_price`, también con objetos propios de Forever (211786). Con `static-classic-eu` y `static-eu` los de Forever dan 404. Sirve para rellenar los nombres que faltan en el archivo (una petición por objeto, una sola vez).

**Histórico:** la API no lo da: solo la foto actual. El histórico se construye guardando las fotos desde que empecemos.

**Sin comprobar:** que la Horda y Aguasnegras de nuestro reino sean la 114 y la 117. Se supone por el orden de los grupos, que encaja con los tamaños: en cada grupo, Aguasnegras es una décima parte de las facciones. Se confirma con un escaneo de un personaje de la Horda.

## 1. De dónde saca cada uno los datos

| Herramienta | Fuente | ¿Sin entrar al juego? |
|---|---|---|
| **Auctionator** | Solo escaneos en el juego (`SendBrowseQuery` o `ReplicateItems`). Guarda mínimo y cantidad por día (ver `fuentes-de-precios.md`) | No |
| **Auctioneer** | Escaneos en el juego. El módulo BeanCounter lee tu correo (tus ventas y compras) | No |
| **TSM (TradeSkillMaster)** | La aplicación de escritorio de TSM descarga sus valores (`DBMarket`, `DBRegion…`) de los servidores de TSM, que leen la API de Blizzard cada hora | Sí, pero son datos de TSM. No sabemos si cubre Forever |
| **Webs de subasta** (Undermine Exchange, Saddlebag, y para Forever azerothauctions.com, azerothvault.com) | La **API oficial de Blizzard** (Game Data API), cada hora | Sí |

Conclusión: lo que se lee fuera del juego sale siempre de la **API oficial de Blizzard**. Es pública y legal: Blizzard la ofrece para esto. No toca el juego ni la cuenta del jugador, así que no tiene nada que ver con el botting.

## 2. La API de Blizzard para Forever

### Lo que hay en WoW normal (documentado)

- Autenticación: se crea un cliente gratis en `develop.battle.net` (Client ID y Client Secret) y se pide un token con `POST https://oauth.battle.net/token`, `grant_type=client_credentials`. Dura unas 24 h.
- `GET /data/wow/connected-realm/{id}/auctions`: todas las subastas del reino, una foto por hora.
- `GET /data/wow/auctions/commodities`: materiales (los «commodities»), una foto por región.

### Comprobado por el usuario (23/11/2026, con curl y un token de cliente)

- `GET /data/wow/ruleset/index?namespace=dynamic-forever-eu` → 200, reglas 1, 2, 3 y 15. Cabecera `cache-control: max-age=30`.
- `GET /data/wow/ruleset/2` → «Normal», estado `UP`, `auctions.href` = `/data/wow/ruleset/2/auctions/`.
- `GET /data/wow/ruleset/2/auctions/index` **y** `/data/wow/ruleset/2/auctions/` (con barra final) → 200, la misma lista: 15 casas, `110`–`121` y `123`–`125`. Por nombre: Alianza 110, 111, 112, 119, 123; Horda 113, 114, 115, 120, 124; Aguasnegras 116, 117, 118, 121, 125. Cabeceras: `last-modified` y `cache-control: max-age=86400` (la lista casi no cambia).
- Sin la palabra `Bearer` bien puesta, la respuesta es un 401 **sin cuerpo**: `curl` sin `-i` no muestra nada.
- `blizzard-token-expires` dice cuándo caduca el token (24 h).
- La regla 2 lista las 15 casas, no solo las suyas: la regla de la ruta no parece separar mercados. Falta saber cuál de los 5 grupos es el nuestro (apartado «Cómo encaja con Oroboros»).

### Lo que se sabe de Forever (comunidad, sin confirmar)

Forever no tiene reinos conectados: tiene **reglas** (rulesets) y casas de subasta por facción. Según el issue [jkc-be/goldbook#67](https://github.com/jkc-be/goldbook/issues/67) (cerrado el 6/11/2026; resume un post de Reddit que su autor dice que está escrito con IA y que él aún no había comprobado con su cliente) y un hilo del foro de desarrolladores de Blizzard:

- Espacio de nombres: `dynamic-forever-eu` (y `dynamic-forever-us`).
- Rutas que responden:
  - `GET /data/wow/ruleset/index`
  - `GET /data/wow/ruleset/{rulesetId}/auctions/index` (con `/index`; sin él da 404)
  - `GET /data/wow/ruleset/{rulesetId}/auctions/{houseId}` → subastas normales
  - `GET /data/wow/ruleset/{rulesetId}/auctions/{houseId}/commodities` → materiales
- `realm/index`, `connected-realm/*` y `auctions/commodities` dan 404.
- Reglas: 1 PvP, 2 Normal, 3 Rol, 15 Rol PvP. Región EU = 93.
- Casas en grupos de Alianza/Horda/Aguasnegras: 110/113/116, 111/114/117, 112/115/118, 119/120/121, 123/124/125. **No se sabe qué grupo es de qué regla**: la casa 116 devolvía lo mismo pidiéndola con la regla 1 y con la 2.
- Cada subasta: `id`, `item.id` (a veces `item.bonus_lists`), `quantity`, `buyout` (normales) o `unit_price` (materiales), `time_left` (`SHORT`, `MEDIUM`, `LONG`, `VERY_LONG`). Precios en cobre. Falta confirmar si `buyout` es por el montón entero.
- Una casa vacía devuelve 200 sin `auctions`.
- Límites: 36 000 peticiones por hora, 100 por segundo. Sobra: son ~30 peticiones por hora para todas las casas.

### Cómo encaja con Oroboros

- Nuestro reino interno es `CAMWOWEU5Realm5PvE`, sin ID de casa ni de regla. Para saber cuál es nuestra casa: comparar un escaneo completo nuestro con la foto de cada casa (la que coincide en mínimos es la nuestra). Oroboros ya guarda los escaneos en `work/archivo.sqlite`, así que se puede hacer fuera del juego, una vez.
- Esto también responde a la pregunta pendiente de si la subasta se comparte entre facciones: la API da una casa por facción.

## 3. Qué ganaría Oroboros con la API

| Hoy (escaneo en el juego) | Con la API |
|---|---|
| Solo cuando abres la subasta (unos pocos escaneos al día) | 24 fotos al día, también cuando no juegas |
| Las franjas horarias tardan semanas en llenarse | Se llenan en días |
| Una sola casa (la de tu facción) | Las tres casas (Alianza, Horda, Aguasnegras): se ven diferencias de precio entre facciones |
| Sin identificador de subasta: solo se ve que baja la cantidad | Cada subasta tiene `id`: se sabe **qué** subasta desapareció, a qué precio y con cuánto tiempo le quedaba |
| No se separan caducadas de vendidas (fase 4, punto 3) | Con `time_left` sí, en buena parte (ver apartado 4) |

Lo que **no** cambia: comprar, publicar y fabricar siguen siendo en el juego, con un clic. La API solo lee.

## 4. Cómo se calculan las unidades vendidas

Nadie tiene las ventas reales del mercado: Blizzard no las publica. Hay tres maneras de estimarlas.

### a) Comparar fotos (Auctioneer, las webs, Oroboros)

- **Auctioneer, módulo Stat-Purchased**: compara escaneos seguidos; lo que desaparece antes de poder haber caducado se da por comprado. Necesita escanear a menudo.
- **Webs con la API** (The Undermine Journal en su día, foros de desarrolladores de Blizzard): con dos fotos seguidas, por cada `id` que desaparece:
  - si tenía `time_left = SHORT` (menos de 30 min) → **caducada**;
  - si no era de las más baratas cuando desapareció → probablemente **cancelada** (alguien la retiró para bajar el precio);
  - lo demás → **vendida**: suma su `quantity`.
  - Oroboros añade desde el 24/11 (fase 5 de la hoja de ruta): si sigue viva otra subasta más barata del mismo objeto y variante (`bonus_lists`), la que desaparece cuenta como **cancelada**, porque quien compra, compra primero lo más barato. En cuatro fotos reales de la casa 111 eso pasó a canceladas un 20 % de las unidades «vendidas».
  - Errores conocidos: lo que se publica y se vende entre dos fotos no se ve nunca; quien cancela y vuelve a publicar parece una venta; si falta una foto, el hueco mezcla todo. Con materiales es peor: una compra parcial baja la `quantity` de una subasta sin hacerla desaparecer (hay que restar cantidades por `id`, no solo contar desapariciones).
- **Oroboros hoy** (`docs/franjas-horarias.md`): sin `id`, resta cantidades totales entre escaneos y, aparte, cuánto bajó lo barato (≤ mínimo × 1,25). La idea de «lo barato que desaparece es venta» es la misma que la regla de cancelación de arriba, pero sin poder separar caducadas.

### b) Ventas reales de muchos jugadores (TSM)

- `DBRegionSoldPerDay`: unidades vendidas de media por casa de subasta y día en la región.
- `DBRegionSaleRate`: proporción de publicaciones que acaban vendidas (0,4 = se vende el 40 % de las veces que se publica).
- Según la documentación de TSM y addons que usan estos valores, salen de la aplicación de escritorio de TSM. Lo que se sabe en la comunidad (**no lo he podido comprobar**: sus páginas no cargan desde aquí) es que se calculan con los datos de contabilidad que los usuarios de TSM suben con la aplicación: ventas reales leídas del correo, no fotos. Por eso son medias de toda la región y no de tu casa.
- `DBMarket` (valor de mercado): media ponderada de 14 días de un valor diario que se calcula con la parte barata de las subastas, quitando precios anómalos. Oroboros ya hace algo parecido (media del 15 % más barato).

### c) Tus propias ventas (BeanCounter, TSM Accounting, Oroboros)

Leer el correo («Subasta realizada»). Es exacto pero solo cuenta lo tuyo. Sirve para la tasa de venta propia (cuántas de tus publicaciones se venden) y para calibrar la estimación (a): si sabes que vendiste 5 unidades entre dos fotos, la estimación debería ver al menos esas 5.

### Qué haría Oroboros

Con la API: el método (a) por `id` y `time_left`, que da vendidas, caducadas y canceladas por separado, por hora y por casa. Se comprueba con tus ventas reales del correo (c), que Oroboros ya guarda en el libro.

## 5. Qué se construyó (24/11/2026)

Plan: `docs/planes/2026-11-23-api-blizzard.md`. Uso: README, «Subasta sin entrar al juego».

- `tools/oroboros_api.py`: descarga con `If-Modified-Since`, tablas `api_*` en `work/archivo.sqlite`, clasificación del apartado 4a por `id` (con compras parciales y sin clasificar los huecos de más de 90 min), resumen semanal por franja, nombres de objetos y calibración con el libro.
- `tools/oroboros_panel.py`: descarga cada hora y panel en `127.0.0.1:8737`.
- El plan, las franjas y `Resumen.lua` usan la API cuando tiene datos (ver README, «Qué gana»).

Primeros datos (12 fotos del 23/11 y la de las 00:23 del 24/11):
- Las «vendidas» son muy altas. El Paño de lino, por ejemplo, sale con unas 72 000 vendidas al día en la 111 y unas 179 000 publicadas: casi seguro, recolocaciones de bots que retiran una subasta barata y la vuelven a poner. La regla de «cancelada» (solo lo caro) no las separa.
- Tus 28 ventas del libro son anteriores a las fotos: aún no hay calibración. Se hará sola cada día.
- Idea para afinar, si la calibración lo confirma: tratar como recolocación lo que desaparece y reaparece (mismo objeto, misma cantidad) en la foto siguiente, al mismo precio o más barato.

## 6. Propuesta inicial de automatización (ya hecha, ver apartado 5)

1. **Comprobar a mano** (10 minutos, en tu PC): crear el cliente en `develop.battle.net`, pedir el token y llamar a `ruleset/index` y `ruleset/2/auctions/index` con `namespace=dynamic-forever-eu`. Si responde, todo lo demás es viable.
2. `tools/oroboros_api.py` (Python sin dependencias, como el resto): cada hora pide las fotos de las casas que interesan, se salta las que no han cambiado (`Last-Modified`) y las guarda en `work/archivo.sqlite` en una tabla aparte de los escaneos del juego (por subasta: `id`, objeto, cantidad, precio, `time_left`, hora de la foto). Las credenciales en un archivo de `work/` o en variables de entorno, **nunca en git**.
3. Encontrar nuestra casa comparando con un escaneo propio (apartado 2).
4. Estimación de ventas por `id` (apartado 4a) y franjas horarias desde la API; el plan y `Resumen.lua` la usan cuando hay datos.
5. Lanzarlo con la tarea programada de Windows cada hora (como el vigilante), o desde un servidor si se quiere que funcione con el PC apagado.

Riesgos: que las rutas de Forever cambien (no están documentadas); que Blizzard tarde en actualizar alguna foto; que la casa de nuestro reino no se pueda identificar con seguridad.

## Fuentes

- Issue «Fetch Forever auction prices from the Battle.net API»: https://github.com/jkc-be/goldbook/issues/67
- Hilo del foro de desarrolladores, «WoW: Forever API: what works so far»: https://us.forums.blizzard.com/en/blizzard/t/wow-forever-api-what-works-so-far-plus-a-ts-client/60334 (no se pudo abrir desde aquí)
- API de WoW (Game Data): https://community.developer.battle.net/documentation/world-of-warcraft/game-data-apis
- Webs de Forever: https://azerothauctions.com/forever/us, https://azerothvault.com/forever (no se pudieron abrir desde aquí)
- Valores de TSM: https://support.tradeskillmaster.com/custom-strings/which-value-sources-can-i-use-and-what-do-they-mean
- Addon que usa la tasa de venta de TSM: https://www.curseforge.com/wow/addons/pbs-sales-rate-tsm-regionsalerateavg
- Auctioneer (Stat-Purchased): https://www.curseforge.com/wow/addons/auctioneer
- Clasificar desapariciones por `time_left`: https://us.forums.blizzard.com/en/blizzard/t/how-to-find-items-sold-on-ah-and-turnover/11022 y https://medium.com/@patricklowe33/analyzing-the-auction-house-world-of-warcraft-124183ebc6af
