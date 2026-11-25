# Hoja de ruta: datos, seguimiento de precios y automatización

Actualizado el 25/11/2026. Este documento resume **qué esperamos** de cada fase y en qué estado está. El detalle técnico de cada una está en `docs/modelo-y-seguimiento.md`, que es la referencia para planificarla.

**Cómo se trabaja:** una fase cada vez. Al empezarla se escribe su plan en `docs/planes/`, se ejecuta con pruebas y commits, y al terminarla se marca aquí como hecha, con lo aprendido. No se empieza una fase sin haber cerrado la anterior.

## Para qué es todo esto

El usuario quiere ganar oro con la subasta de WoW Forever sabiendo **cuándo** comprar y vender, no solo qué. Para eso necesita:

- historia de precios fiable y sin datos repetidos;
- verla cómodamente: dentro del juego al mirar un objeto, como la extensión de CamelCamelCamel en Amazon, y completa en la página del plan;
- que recoger y procesar los datos le cueste lo mínimo, sin botting.

## Estado

| Fase | Qué | Estado |
|---|---|---|
| — | Franjas horarias (dos cuentas: total y baratas) | ✅ Hecho (19/11), ver `docs/franjas-horarias.md` |
| 1 | Modelo de datos | ✅ Hecho (19/11), plan en `docs/planes/2026-11-19-fase1-modelo-de-datos.md` |
| 2 | Seguimiento de precios al estilo Camel | ✅ Hecho fuera del juego (19/11); falta comprobarlo en el juego. Plan en `docs/planes/2026-11-19-fase2-seguimiento-precios.md` |
| 3 | Automatización | ✅ Hecho fuera del juego (19/11); falta comprobarlo en el juego. Plan en `docs/planes/2026-11-19-fase3-automatizacion.md` |
| — | API de Blizzard y panel de escritorio | ✅ Hecho (24/11), plan en `docs/planes/2026-11-23-api-blizzard.md` |
| 4 | Cálculos avanzados | ⏳ Cuando haya un par de semanas de datos |
| 5 | Cálculo fiable del oro (depósito, variantes, reventa por escalones, ventas) | ✅ Hecho fuera del juego (24/11); falta medir el depósito real en el juego |
| 6 | Catálogo de Forever al día (antes de las bandas del 9/12) | ✅ Hecho (25/11); falta comprobar en el juego el día de reinicio y el vendedor del mercado negro |
| 7 | Maneras nuevas: Aguasnegras, enfriamientos como renta, gangas en el panel | ✅ Hecho fuera del juego (25/11) |
| 8 | Pasada de corrección: las «vendidas» de la API no se dan por buenas sin más | ✅ Hecho (25/11); falta medir la precisión con tus subastas caducadas |

## Fase 1: modelo de datos

**Qué esperamos:** un archivo permanente (`work/archivo.sqlite`) que sea la única fuente de verdad de los precios, con cada producto una sola vez y los escaneos relacionados con los productos. Lo viejo se resume para que nada crezca sin límite.

**Hecho cuando:**
- El archivo tiene tablas de productos, mercados, escaneos, observaciones, histórico diario y resumen semanal por franja.
- Los escaneos en bruto se guardan **8 semanas** (decisión del usuario). Después se resumen y se borran; el histórico diario y los resúmenes se quedan para siempre.
- El archivo actual (tabla plana) y el histórico que ya hay (del juego y de Auctionator) se migran sin perder nada.
- El plan sale del archivo y propone lo mismo que antes con los mismos datos.
- El histórico dentro del juego baja de 30 a 14 días, **solo después** de pasar los datos reales al archivo nuevo, y `Oroboros.lua` pesa menos que hoy.

**Hecho (19/11).** Lo aprendido:
- Datos reales migrados: 3 escaneos (21 088 observaciones), 7305 productos, 21 410 días de histórico (Auctionator desde el 8/11, juego el 18/11, escaneos el 19/11). Exportar tarda unos 3,5 s. Copia del archivo anterior en `work/archivo.sqlite.bak`.
- Al resumir, las franjas dan exactamente lo mismo que con los datos en bruto (hay una prueba que lo garantiza).
- **Solo 2382 de 7305 productos tienen nombre**: el escaneo completo no siempre trae el nombre del objeto. La fase 2 lo necesita (panel y página): el addon tendrá que pedir los nombres que falten.
- El histórico del juego se recorta a 14 días en el siguiente `/reload`; `Oroboros.lua` bajará de tamaño entonces.

## Fase 2: seguimiento de precios (Camel)

**Qué esperamos:** al seleccionar un objeto en la subasta, un panel a su lado con su historial resumido. En la página del plan, el historial completo.

**Hecho cuando:**
- Los objetos tienen nombre (aprendido en la fase 1: hoy faltan dos tercios). El addon pide los nombres que no tiene y el exportador los guarda en `items`.
- Fuera del juego se genera `Oroboros/Resumen.lua` (ignorado en git, con un apartado por mercado). Por objeto lleva: hoy, medias de 7/30/90 días, mínimo y máximo históricos con fecha, 13 semanas y 14 días de gráfica, y las franjas.
- El panel aparece con la subasta de Blizzard y con Auctionator sin taparlos, muestra el precio de hoy en vivo y funciona aunque falte el resumen.
- `/oro precio <objeto>` abre el panel en cualquier sitio.
- La pestaña Mercado de la página muestra el historial completo con rangos (1 mes, 3 meses, 6 meses, 1 año, todo) y los mínimos, máximos y medias.
- El juego no tarda más en cargar.

**Hecho (19/11), con pruebas fuera del juego.** Lo aprendido:
- Con datos reales, `Resumen.lua` ocupa 841 KB para 7211 objetos y carga en unos 0,02 s. Crecerá algo cuando se llenen las 13 semanas: si pasa de ~1,5 MB, comprimir los números.
- Con 4 días de historia, las barras semanales del panel salen casi vacías; se llenan solas con los escaneos.
- Las pruebas nunca escriben `Resumen.lua` en la carpeta del addon: el juego la carga a través del enlace y vería datos inventados.

**Por comprobar en el juego:**
1. Tras `/reload`, que no salga ningún error, y que el addon cargue también en una instalación sin `Resumen.lua` (mirar `Logs/FrameXML.log`).
2. Que el panel aparece a la derecha de la subasta al seleccionar un objeto, sin tapar Auctionator.
3. Que las tildes y el «·» se ven bien con la fuente del juego.
4. Que `/oro precio <id>` lo abre fuera de la subasta.
5. Que tras un escaneo completo los objetos van recibiendo su nombre (`/oro stats`, o en la página del plan).

## Fase 3: automatización

**Qué esperamos:** el usuario solo tiene que pasar por la subasta cuando le venga bien; lo demás ocurre solo.

**Hecho cuando:**
- Al abrir la subasta, si han pasado 15 minutos, Oroboros lanza el escaneo completo solo (aceptado por el usuario: escanear no es una acción protegida).
- **Se ve claramente**, como si se hubiera pulsado el botón: el botón aparece pulsado y desactivado con «Escaneando…», el avance se ve como hoy («Escaneo automático: 3000 / 7000») y el chat avisa al empezar y al acabar.
- Con el escaneo completo de Auctionator activado, no se lanza el propio: se lee el de Auctionator.
- Se puede apagar con `/oro set autoscan 0`.
- Un vigilante en Windows (`tools/oroboros_watch.py`) detecta cuándo el juego guarda los datos y exporta, archiva, genera el plan y el resumen solo. Está documentado cómo arrancarlo al iniciar sesión.

**Hecho (19/11), con pruebas fuera del juego.** Lo aprendido:
- Procesar tus datos reales completos tarda unos 6 s.
- Arreglado de paso: el panel de precios de la fase 2 se anclaba en el mismo sitio que la ventana de Oroboros; ahora va debajo de ella.
- La tarea programada de Windows está documentada en el README, pero no se ha creado: es un cambio en el sistema del usuario y la crea él si quiere.

**Por comprobar en el juego:**
1. Al abrir la subasta pasados 15 min: el botón «Escaneando…» pulsado, el avance y los avisos del chat.
2. Que no choca con el autoescaneo resumen de Auctionator, que también arranca al abrir la subasta.
3. Que el panel de precios queda debajo de la ventana de Oroboros.

## Rediseño de las ventanas (20/11)

Hecho fuera del juego: estilo propio oscuro y plano (`Style.lua`), gráficas con escala, leyenda y detalle al pasar el ratón (`Chart.lua`), precio en vivo corregido y ventana principal con el mismo estilo. Diseño en `docs/rediseno-ventanas.md`. Falta comprobarlo en el juego: fuente, caracteres «×» y «…», gráficas y detalle al pasar el ratón.

## ProfessionDB (20/11)

Hecho: «qué aprender» lee ProfessionDB (nivel real, dónde se aprende, coste; sin recetas que nunca existieron) y «si cambiaras de profesión» sale de ella. Con los datos reales, las recetas de nivel desconocido bajan de 230 a 15. Plan en `docs/planes/2026-11-20-professiondb.md`.

También:
- las reventas de riesgo usan como mucho la mitad del 30 % de confianza baja, para que entren los lotes de prueba de fabricación (de 1 a 7 con los datos reales);
- subasta o vendedor se decide por objeto, sumando bolsas y banco.

Ojo: el beneficio por día de las profesiones nuevas aún usa ventas por día supuestas (hay pocos días de datos) y sale muy alto. Se corregirá solo con más escaneos.

## Farmeo: dónde farmear para vender (hecho el 20/11; falta probarlo en el juego)

**Qué esperamos:** que Oroboros proponga dónde farmear criaturas de mundo abierto (sin élites) y recolectar, según el nivel. La base es lo que mide el addon; AzerothCore es solo una estimación inicial de materiales para los sitios donde aún no has estado; la recolección sale de GatherMate2. Diseño en `docs/farmeo.md`; plan en `docs/planes/2026-11-20-farmeo.md` (6 tareas, empezando por la medición).

**Estado:** las 6 tareas hechas, con pruebas (`Farm.lua`, `FarmPanel.lua`, `tools/oroboros_farm.py`, `azerothcore.py`, `gathermate.py`, pestaña Farmear, `Farmeo.lua` y `/oro farmear`). Cambios respecto al diseño, en `docs/farmeo.md` («Cambios al construirlo»). Por comprobar en el juego:
- que se cuentan las muertes y el botín;
- que el aviso salta al entrar en un sitio de la lista;
- que los nombres resueltos de los sitios caen donde están las criaturas (si no, el orden x/y de AzerothCore respecto a `UnitPosition` es otro);
- que los niveles de `tools/gather_skill.json` son los de Forever.

## API de Blizzard y panel de escritorio (hecho el 24/11)

**Qué esperábamos:** leer la subasta sin entrar al juego, cada hora, con la API oficial de Blizzard; usarla para el seguimiento de precios y para estimar ventas; y verlo todo en un panel que se queda abierto. Lo comprobado a mano, en `docs/api-subasta-blizzard.md` (apartado 0); el plan, en `docs/planes/2026-11-23-api-blizzard.md`.

**Hecho:** `tools/oroboros_api.py` (descarga, tablas `api_*`, ventas estimadas por id de subasta, resumen semanal, nombres y calibración con el libro) y `tools/oroboros_panel.py` (descarga cada hora, servidor local y ventana con las pestañas del plan más Subasta y Ventas). El plan, las franjas y `Resumen.lua` usan la API cuando tiene datos. Las 12 fotos de la fase A están en el archivo.

Lo aprendido:
- Nuestra casa es la **111** (Alianza); el grupo es 111/114/117. La regla no importa. Una foto por hora hacia el minuto 23; `HEAD` no funciona, `If-Modified-Since` sí (304).
- Una casa grande son ~300 000-390 000 subastas por foto; `api_live` ocupa ~22 MB y el detalle por hora ~18 MB al día.
- Las «vendidas» estimadas son muy altas (el Paño de lino, decenas de miles al día): seguramente recolocaciones. Hasta calibrarlas con tus ventas del correo (5 ventas y 80 % de cobertura), el plan las trata como estimadas.
- El panel no puede abrir el archivo para escribir mientras descarga (daba error): lee sin tocar el esquema.
- `Resumen.lua` con las tres casas pasaba de 2 MB: solo lleva los mercados con datos del juego.

**Por comprobar:**
1. Abrir el panel con su ventana y mirar las pestañas Subasta y Ventas.
2. Tras unos días con ventas tuyas, `--calibrar`: si la cobertura es buena pero tu parte es ínfima, la regla de «cancelada» necesita afinarse (por ejemplo, contar como recolocación lo que reaparece al mismo precio o más barato).
3. Con un personaje de la Horda, que su casa es la 114.
4. En el juego, que «Unas N vendidas al día» se ve en el panel de precios.

## Fase 4: cálculos avanzados

**Qué esperamos:** sacar más de los mismos datos. Cada cálculo tiene su propio diseño corto antes de programarlo, cuando haya datos suficientes para comprobar que funciona:

1. **Franjas con intervalos largos**: que cuenten también los días con solo dos escaneos muy separados, despejando las franjas como un sistema de ecuaciones.
2. **Día de la semana**: si unos días se vende más o está más barato.
3. **Caducadas**: separar lo que caduca de lo que se vende de verdad.
4. **Velocidad de rebaja**: cuánto tarda alguien en ponerse por debajo de tu precio.
5. **Precio y ventas**: qué precio gana más, no solo cuál es el más bajo.

## Repaso de las maneras de ganar oro (24/11): fases 5 a 7

El 24/11 se repasaron todas las maneras de ganar oro (fabricar, transformar, aprender, revender, vender lo que sobra, ideas, farmeo y franjas) con el plan real y con lo publicado sobre Forever. Conclusión: antes de añadir maneras nuevas hay que corregir el cálculo. Con los datos de ese día, 266 de las 275 oportunidades eran reventas, y muchas no eran reales.

### Fase 5: cálculo fiable del oro

**Qué esperamos:** que el beneficio que promete el plan se parezca al que se cobra.

**Hecho cuando:**
1. **Depósito.** El plan deja de restar 1 plata fija. Usa el depósito de Forever (5 %, 20 % y 60 % del precio de vendedor para 2, 8 y 24 h; mínimo 1 cobre; se devuelve al vender y se pierde al caducar o cancelar) y cuenta las republicaciones esperadas cuando el lote no cabe en las ventas de un día. El addon apunta el depósito real que da el juego al publicar, y con 3 mediciones el plan usa el porcentaje medido (una guía trae un ejemplo que triplica la fórmula).
2. **Variantes de equipo.** La API distingue las variantes de un mismo objeto («del bandido», «de la ballena») con `bonus_lists`. Se guardan, las ventas se clasifican por variante, y el plan no propone reventas ni rebotes de objetos con más de una variante (su precio por número de objeto no significa nada).
3. **Reventa por escalones.** Con la lista completa de subastas de la API, una reventa es: comprar todo lo que hay por debajo de un salto de precio y volver a ponerlo justo por debajo del escalón siguiente, sin pasar de la mediana de 7 días, y solo lo que el mercado absorbe. Sin API, sigue la regla anterior.
4. **Ventas estimadas.** Una subasta que desaparece mientras sigue viva otra más barata del mismo objeto no se vendió (quien compra, compra primero lo más barato): pasa a «cancelada».

**Lo medido el 24/11 (casa 111, cuatro fotos seguidas):**
- La regla del punto 4 pasa a canceladas un 20 % de las unidades «vendidas».
- El grueso de las unidades vendidas es munición a 1–4 cobres (flechas y balas, en lotes de 200 a 8000): infla el total, pero no afecta a los objetos con los que se comercia.
- 1557 de 7123 objetos tienen más de una variante.
- Comprar por debajo del precio de vendedor no compensa: menos de 1 oro en total en cada casa.
- La subasta **no** se comparte entre facciones: no hay ni un número de subasta común entre la 111 y la 114. La facción se queda en la clave de mercado.

**Hecho (24/11), con pruebas fuera del juego.** Lo aprendido:
- Con los datos reales, las reventas pasan de 266 a 7 y el beneficio prometido del plan baja de 85 a unos 4 oro: lo de antes no se podía cobrar.
- Las variantes van en una tabla aparte (`api_var`) y no en `api_live`: el panel en marcha escribe en `api_live` con el código que tenía al arrancar, y cambiarle las columnas le rompía la descarga. **Hay que reiniciar el panel** para que empiece a guardar variantes; hasta entonces el plan no descarta el equipo con variantes.
- Las constantes están en `tools/oroboros_plan.py`: `DEPOSIT_RATE`, `SELL_SHARE` (cuento con que te llevas la mitad de las ventas del día), `FLIP_GAP` (salto del 25 %) y `FLIP_MIN_MARGIN` (15 %).
- Queda a la vista otro problema: fabricaciones de miles de unidades por céntimos (3047 pescados por 24 platas). Falta un mínimo de beneficio por clic.

**Por comprobar en el juego:**
1. Que al vender con la ruta, la línea de estado dice «Depósito: …» (si no sale, `CalculateCommodityDeposit` o `CalculateItemDeposit` no existen en Forever).
2. Tras 3 ventas, que el plan usa el porcentaje medido (`Data.deposit_measured`) y cuánto se aparta del 60 %.

### Fase 6: catálogo de Forever al día

**Qué esperamos:** que las ideas de evento y el plan conozcan lo que Forever cambió, antes del 9/12.

**Hecho cuando** `catalog.json` y el plan recogen, cada dato con su fuente y marcado como comprobado o no:
- elixires de estadísticas distintas que se acumulan, y los tres nuevos de nivel 55;
- frascos naturales (bonificación extra en Hyjal y Barrow Deeps) y pilas de 20;
- pociones de sanación en Primeros auxilios, no en Alquimia;
- techo de precio del mercado negro (Loto negro y Cristal arcano a 50 oro, sin verificar) para los objetivos de las ideas;
- día de reinicio semanal de las bandas, para el ciclo semanal.

**Hecho (25/11).** Plan en `docs/planes/2026-11-24-catalogo-forever.md`. `catalog.json` tiene tres secciones nuevas: `facts` (10 datos de Forever, cada uno con fuente y marca), `price_caps` (techos) y `server.raid_reset_weekday`. La apertura de las bandas son ahora tres eventos: pociones y hierbas, elixires y frascos. En las ideas, el objetivo no pasa del techo, la idea de evento dice la fecha del primer reinicio (miércoles 16/12) y el ciclo semanal dice si el día caro coincide con el reinicio. La pestaña Ideas enseña los datos del catálogo con su marca y su fuente.

**Lo aprendido en nuestros datos:**
- Los elixires nuevos de nivel 55 no son tres: son 13 (objetos 250328 a 250351), y ya se venden entre 0,7 y 1,6 oro.
- Los frascos naturales son cuatro (274273 a 274276, Alquimia 300). El 24/11 no había ninguno en subasta.
- Las pociones de sanación ya salían bien: la profesión de cada receta viene de ProfessionDB, y ahí son de Primeros auxilios. Alquimia hace las «descoloridas».
- Loto negro (8,4 oro) y Cristal Arcano (14,4 oro) están muy por debajo del techo de 50: hoy el techo no cambia ninguna idea.

**Por comprobar en el juego:**
1. El día de reinicio: en la ventana de información de banda, desde el 9/12. Si no es miércoles, se cambia `raid_reset_weekday` (lunes = 0).
2. Que el vendedor del mercado negro (Mister Graphed, Powderfuse Port) vende Loto negro y Cristal Arcano a 50 oro. Si es así, se pone `verified: true` en `price_caps`.

**Dos arreglos después (25/11):**
- La idea de evento ya no parte de la mediana si el objeto está hundido (un 15 % o más por debajo): parte del punto medio entre hoy y la mediana, y lo dice.
- Mínimo por fabricación: una receta que da menos de 2 oro a la hora (a 3 s por fabricación, unos 17 cobres cada una) se descarta con su motivo. Constantes `CRAFT_SECONDS` y `MIN_CRAFT_HOUR` en `tools/oroboros_plan.py`.

### Fase 7: maneras nuevas

**Qué esperamos:** tres fuentes de oro que hoy no se miran.

**Hecho cuando:**
- **Aguasnegras → tu casa:** el plan propone comprar en la 117 y vender en la tuya solo lo que tiene ventas comprobadas en la tuya (el 24/11 había 327 objetos más baratos después de la comisión, pero son precios mínimos de un mercado pequeño).
- **Enfriamientos como renta diaria:** «qué aprender» valora las recetas con enfriamiento por lo que dan al día (Arcanita y esencias a Alquimia 275).
- **Gangas en el panel:** con cada foto, la pestaña Inicio lista lo que ha aparecido muy por debajo de su precio habitual.

**Hecho (25/11).** Plan en `docs/planes/2026-11-25-maneras-nuevas.md`.

- **Aguasnegras → tu casa:** panel propio en la pestaña Ideas, con lo que entra, lo que no cabe y la lista de compras para pegar en la subasta neutral. Con los datos del 24/11 salieron 12 objetos con margen, pero con 1,9 oro para apuestas solo entraban 4 y ganaban 1,6 oro: por debajo de los 2 oro, el plan dice que no compensa el viaje. De los 327 objetos «más baratos» del primer recuento, casi todos se caen al pedir ventas comprobadas y margen.
- **Enfriamientos:** «qué aprender» marca las transmutaciones como renta diaria. Con precios del 24/11, legionita y arcanita dan unos 11 oro al día (un uso cada 47 h), las mejores de esencias entre 3 y 4, y las de una hora 12 platas con dos usos al día. Piden Alquimia 275.
- **Gangas:** en la pestaña Inicio del panel. Con los datos del 24/11 salían 13, casi todas consumibles con 30–50 % de descuento y entre 0,5 y 4 oro de diferencia.

**Lo aprendido:**
- La primera versión de las gangas daba sobre todo equipo y precios de broma: comparaba con una mediana que el propio mercado ya había dejado atrás. La regla que lo arregló es pedir que no haya subastas más viejas a ese precio.
- La API lleva solo 19 fotos por casa: las ventas de la API aún no llegan a los 3 días, así que las «ventas comprobadas» de Aguasnegras salen hoy de tus escaneos.

**Por comprobar:**
1. Que comprando en la subasta neutral no hay comisión para el comprador y que la lista `BUY` funciona allí con el addon.
2. Los enfriamientos de las transmutaciones y si comparten uno solo (al aprender la primera, a Alquimia 225).
3. Que la tabla de gangas y el panel de Aguasnegras se ven bien en la ventana del panel.

**Descartado con datos:** comprar bajo precio de vendedor (menos de 1 oro), transmutaciones de una hora (5 platas) y pasar mercancía a la otra facción por la casa neutral (15 % de comisión).

### Fase 8: pasada de corrección (25/11)

Plan en `docs/planes/2026-11-25-pasada-de-correccion.md`.

**Lo que pasó:** el 24/11 la calibración dio por buenas las ventas estimadas de la API (6 ventas tuyas, todas vistas como vendidas) y el plan del 25/11 por la mañana salió con 104 oportunidades, casi todas reventas con ventas imposibles: un arma épica de 599 oro «vendiéndose» 4 veces al día. Con el presupuesto solo entraban 4, pero con más oro habrían entrado.

**Hecho:**
- La calibración pide dos cosas: que tus ventas aparezcan entre las vendidas y que la casa no salga vendida más de una vez al día. Con las fotos del 24/11 salía 4,7 veces.
- Las recolocaciones (misma cantidad que reaparece igual o hasta un 20 % más barata) cuentan como canceladas. Las ventas por día solo usan las fotos clasificadas ya con esa regla.
- Los «3 días de fotos» son tres días de medición, no tres fechas.
- Con ventas medidas en tus escaneos, la API sin comprobar solo puede bajarlas.
- «Qué aprender» cuenta con la mitad de lo que se vende, como la ruta.
- Catálogo: tela lunar con sus 95 h, la receta de legionita cae en Hyjal Summit, depósito mínimo de 1 cobre desde el 17/11.
- Ideas: el precio del vendedor es un suelo para la pérdida.
- Comprobado a la vista (capturas con Edge sin ventana): las pestañas Inicio, Ideas y Qué aprender se ven bien.

- **Auditoría a mano** de nueve propuestas (tabla en el plan de la fase): en cinco el programa proponía algo que un jugador no haría. Cambios: el precio de reventa no pasa de un 15 % sobre lo más barato de cada día; el lote de fabricación cuenta con tu parte de las ventas; el lote se encoge si el depósito se come el margen con la mitad de ventas; el rebote se mide con lo más barato de cada día y no entra en una cuesta abajo; la sequía no entra si el precio ya ha saltado.
- **Medición de la regla de recolocaciones** con la foto de las 10:21: quita el 10 % de las vendidas (el 41 % en equipo). La rotación sigue en unas 2 veces al día.

Con los datos del 25/11, el plan pasa de «18,9 oro invirtiendo 34,5» (con 4 reventas dudosas) a 3,5 oro invirtiendo 7,6.

**Lo aprendido:**
- Una comprobación que solo mira si se escapan casos (cobertura) no dice nada de los que sobran. Hay que mirar las dos cosas.
- El valor de mercado (media del 15 % más barato) dice cuánto cuesta comprar, no a cuánto se vende: salta al escalón de arriba cuando el de abajo es fino. Para vender, lo más barato de cada día.
- La regla de recolocaciones no se puede probar del todo: una venta seguida de una subasta nueva igual, de otro vendedor, se ve idéntica. Se elige contar de menos.

**Por comprobar:**
1. La rotación de la casa con la regla nueva, cuando haya tres días de fotos (a partir del 28/11). Si sigue muy por encima de 1, las ventas de la API seguirán sin usarse.
2. La precisión de verdad: hace falta que el addon apunte tus subastas caducadas y canceladas.

## Ideas para después (fuera de estas fases)

- Apuntar en el libro las subastas propias que caducan o se cancelan (correo de «subasta caducada»), para medir cuántas da por vendidas la estimación de la API.
- Guardar las últimas fotos crudas de la API unos días, para poder volver a clasificar cuando cambie una regla.
- Enfriamientos que no son recetas (el salero de peletería, 71 h): hoy el plan no los valora.

- Alertas de precio («avísame si baja de X»), la otra mitad de Camel.
- ~~Leer la subasta sin entrar al juego con la API oficial de Blizzard~~: hecho el 24/11 (ver arriba).
- Apagar el escaneo automático del juego cuando hay foto reciente de la API; comparar precios entre facciones (Aguasnegras); alertas de precio desde el panel.
- Saber si la subasta se comparte entre facciones (con un personaje de cada una). Si es así, quitar la facción de la clave de mercado.

## Reglas que no cambian

- Nada que actúe en el juego sin el usuario. Un clic por acción protegida.
- No subir datos reales a git (`work/`, `Resumen.lua`).
- Python solo con biblioteca estándar; Lua 5.1 e interfaz 16001.
- Cada cambio, con sus pruebas en `tests/run_tests.py` en verde.
