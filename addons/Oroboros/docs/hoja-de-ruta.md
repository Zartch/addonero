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
| 1 | Modelo de datos | ⏳ Siguiente |
| 2 | Seguimiento de precios al estilo Camel | Pendiente |
| 3 | Automatización | Pendiente |
| 4 | Cálculos avanzados | Pendiente (cuando haya datos) |

## Fase 1: modelo de datos

**Qué esperamos:** un archivo permanente (`work/archivo.sqlite`) que sea la única fuente de verdad de los precios, con cada producto una sola vez y los escaneos relacionados con los productos. Lo viejo se resume para que nada crezca sin límite.

**Hecho cuando:**
- El archivo tiene tablas de productos, mercados, escaneos, observaciones, histórico diario y resumen semanal por franja.
- Los escaneos en bruto se guardan **8 semanas** (decisión del usuario). Después se resumen y se borran; el histórico diario y los resúmenes se quedan para siempre.
- El archivo actual (tabla plana) y el histórico que ya hay (del juego y de Auctionator) se migran sin perder nada.
- El plan sale del archivo y propone lo mismo que antes con los mismos datos.
- El histórico dentro del juego baja de 30 a 14 días, **solo después** de pasar los datos reales al archivo nuevo, y `Oroboros.lua` pesa menos que hoy.

## Fase 2: seguimiento de precios (Camel)

**Qué esperamos:** al seleccionar un objeto en la subasta, un panel a su lado con su historial resumido. En la página del plan, el historial completo.

**Hecho cuando:**
- Fuera del juego se genera `Oroboros/Resumen.lua` (ignorado en git, con un apartado por mercado). Por objeto lleva: hoy, medias de 7/30/90 días, mínimo y máximo históricos con fecha, 13 semanas y 14 días de gráfica, y las franjas.
- El panel aparece con la subasta de Blizzard y con Auctionator sin taparlos, muestra el precio de hoy en vivo y funciona aunque falte el resumen.
- `/oro precio <objeto>` abre el panel en cualquier sitio.
- La pestaña Mercado de la página muestra el historial completo con rangos (1 mes, 3 meses, 6 meses, 1 año, todo) y los mínimos, máximos y medias.
- El juego no tarda más en cargar.

## Fase 3: automatización

**Qué esperamos:** el usuario solo tiene que pasar por la subasta cuando le venga bien; lo demás ocurre solo.

**Hecho cuando:**
- Al abrir la subasta, si han pasado 15 minutos, Oroboros lanza el escaneo completo solo (aceptado por el usuario: escanear no es una acción protegida).
- **Se ve claramente**, como si se hubiera pulsado el botón: el botón aparece pulsado y desactivado con «Escaneando…», el avance se ve como hoy («Escaneo automático: 3000 / 7000») y el chat avisa al empezar y al acabar.
- Con el escaneo completo de Auctionator activado, no se lanza el propio: se lee el de Auctionator.
- Se puede apagar con `/oro set autoscan 0`.
- Un vigilante en Windows (`tools/oroboros_watch.py`) detecta cuándo el juego guarda los datos y exporta, archiva, genera el plan y el resumen solo. Está documentado cómo arrancarlo al iniciar sesión.

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
