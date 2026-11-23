# Subasta sin entrar al juego: la API de Blizzard y cómo estiman las ventas los demás

Informe del 23/11/2026. Responde a dos preguntas del usuario:

1. ¿De dónde sacan los datos Auctionator, Auctioneer, TSM y las webs? ¿Se puede automatizar la extracción y el seguimiento de precios sin entrar al juego?
2. ¿Cómo calculan las unidades vendidas por objeto?

**Nada de esto está probado desde aquí**: el entorno donde se escribió no llega a los servidores de Blizzard (`oauth.battle.net`, `eu.api.blizzard.com`) ni a las webs de TSM. Lo de Forever viene de fuentes de la comunidad, no de documentación oficial. Hay que comprobarlo con una llamada real antes de construir nada.

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

## 5. Propuesta de automatización (sin hacer)

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
