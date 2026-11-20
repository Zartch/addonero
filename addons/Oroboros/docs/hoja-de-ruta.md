# Hoja de ruta: datos, seguimiento de precios y automatización

Actualizado el 19/11/2026. Este documento resume **qué esperamos** de cada fase y en qué estado está. El detalle técnico de cada una está en `docs/modelo-y-seguimiento.md`, que es la referencia para planificarla.

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
| 4 | Cálculos avanzados | ⏳ Siguiente, cuando haya un par de semanas de datos |

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

## Fase 4: cálculos avanzados

**Qué esperamos:** sacar más de los mismos datos. Cada cálculo tiene su propio diseño corto antes de programarlo, cuando haya datos suficientes para comprobar que funciona:

1. **Franjas con intervalos largos**: que cuenten también los días con solo dos escaneos muy separados, despejando las franjas como un sistema de ecuaciones.
2. **Día de la semana**: si unos días se vende más o está más barato.
3. **Caducadas**: separar lo que caduca de lo que se vende de verdad.
4. **Velocidad de rebaja**: cuánto tarda alguien en ponerse por debajo de tu precio.
5. **Precio y ventas**: qué precio gana más, no solo cuál es el más bajo.

## Ideas para después (fuera de estas fases)

- Alertas de precio («avísame si baja de X»), la otra mitad de Camel.
- Saber si la subasta se comparte entre facciones (con un personaje de cada una). Si es así, quitar la facción de la clave de mercado.
- Duraciones de publicación en Forever (Auctionator usa 2/8/24 h; `postDuration` asume 12/24/48 h).

## Reglas que no cambian

- Nada que actúe en el juego sin el usuario. Un clic por acción protegida.
- No subir datos reales a git (`work/`, `Resumen.lua`).
- Python solo con biblioteca estándar; Lua 5.1 e interfaz 16001.
- Cada cambio, con sus pruebas en `tests/run_tests.py` en verde.
