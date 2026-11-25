# Fase 8: pasada de corrección (25/11) — plan

**Objetivo:** mirar lo que da el plan con el código de las fases 5 a 7 y los datos de hoy, buscar en la web lo que quedaba sin comprobar, y corregir lo que no se sostenga.

## Lo que se encontró

1. **El plan se fiaba de las «vendidas» de la API.** La calibración pasó el 24/11 (6 ventas tuyas, cobertura 100 %) y el plan empezó a usar esas cifras como ventas medidas. Proponía revender un arma épica de 599 oro contando con 4 ventas al día, y 100 reventas más. La cobertura solo dice que a la estimación no se le escapan tus ventas; no dice que no cuente de más. Con las fotos de ese día, la casa de la Alianza saldría vendida 4,7 veces al día (10,5 millones de unidades «vendidas» al día con 2,25 millones a la venta).
2. **Tres días de fotos no eran tres días.** Se contaban fechas distintas: 28 fotos seguidas (poco más de un día) ya valían como 3 días.
3. **«Qué aprender» contaba con todas las ventas del mercado**, no con tu parte: salían recetas a 500 oro al día.
4. **Tela lunar sin enfriamiento:** salía a 13 500 oro al día.
5. **Legionita:** la receta la suelta un jefe de Hyjal Summit; antes del 9/12 no se puede aprender.
6. **Gangas:** las unidades salían de las mismas ventas infladas (24 000 unidades de un objeto).
7. **Ideas:** el stop no tenía en cuenta el precio del vendedor. Una idea comprada al precio del vendedor decía a la vez «lo máximo que pierdes es 0 %» y «acepta una pérdida de 44 platas».
8. **Reventas de equipo** con un archivo sin variantes guardadas (panel sin reiniciar).

## Lo que se cambia

- `oroboros_api.classify`: una subasta barata que desaparece y reaparece en la misma foto con la misma cantidad, al mismo precio o hasta un 20 % más barata, es una recolocación y cuenta como cancelada. Cada subasta nueva empareja con una sola desaparecida. Cuenta de menos antes que de más: una venta y una subasta nueva igual, de otro vendedor, no se distinguen de una recolocación.
- `api_rule_t` (en `meta`): primera foto clasificada con esa regla. Las ventas por día (`move_rates`) solo usan las fotos desde ahí; un archivo de antes empieza a contar con la primera foto que meta el panel ya reiniciado.
- `move_rates`: los días son tiempo medido (segundos con medición / 86 400).
- `turnover` e `is_calibrated`: además de la cobertura, la casa no puede salir vendida más de una vez al día (`CALIB_MAX_TURNOVER`). Es una condición necesaria, no una prueba.
- `Data.stats`: si hay ventas medidas con tus escaneos, la API sin comprobar solo puede bajarlas. Si no las hay, la API vale como estimada (lotes de prueba). Comprobada, manda.
- `find_flips`: sin variantes guardadas, lo que no se apila no se revende.
- `learn_suggestions`: ventas al día × `SELL_SHARE`; las recetas de profesiones que no tienes también leen el catálogo (enfriamiento, nivel y nota).
- `bargains`: sin calibrar, las ventas se rebajan con la rotación de la casa antes de limitar las unidades.
- `oroboros_ideas.worst_loss`: lo peor es vender al stop en la subasta o, si paga más, al vendedor.
- `catalog.json`: tela lunar (95 h, Sastrería 230), nota de la legionita y de la arcanita, y cinco datos nuevos con su fuente.

- Tras la auditoría: `resale_price` (techo de reventa), `SELL_SHARE` en el lote de fabricación, prueba de esfuerzo del depósito (`STRESS_VOL`), `sliding` y lo más barato de cada día en el rebote, `LATE` en la sequía, aviso de depósito en las ideas, y las gangas comparan con lo más barato de cada día.

## Lo que no se cambia

- El tiempo de una fabricación solo cuenta los 3 s de fabricar, no el viaje al vendedor ni publicar.
- La confianza «alta» sale de un precio estable y días de datos; no dice que las ventas estén comprobadas.

- Las horas ya guardadas no se pueden volver a clasificar: las fotos crudas no se conservan. Las franjas de la pestaña Horas seguirán mezclando horas de antes y de después durante dos semanas.
- La precisión de las «vendidas» sigue sin medirse de verdad. Haría falta que el addon apuntara tus subastas que caducan o que cancelas, para ver cuántas de esas da por vendidas la estimación.

## Medición de la regla de recolocaciones (foto de las 10:21 del 25/11, casa 111)

Una hora, con la regla vieja y con la nueva sobre las mismas dos fotos:

| | Vendidas (vieja) | Vendidas (nueva) | Cambio |
|---|---|---|---|
| Todo | 191 940 | 172 705 | −10 % |
| Lo que no se apila | 7 370 | 4 371 | −41 % |
| Lo que se apila | 184 570 | 168 334 | −9 % |

Con 2,25 millones de unidades a la venta, esa hora da una rotación de unas 2 veces al día también con la regla nueva. La regla limpia el equipo, pero no explica lo que se apila: o se vende de verdad mucho, o se recoloca cambiando el tamaño de los montones. Mientras la rotación siga por encima de 1, el plan no usa las ventas de la API.

## Auditoría a mano (25/11)

Se revisaron nueve propuestas con sus datos crudos (lista de precios, histórico, receta), calculando primero a mano y comparando después con el programa.

| Propuesta | A mano | Programa | Coinciden | Qué se cambió |
|---|---|---|---|---|
| Fabricar Invernadero (20) | Sí, lote pequeño: gana aun si el precio vuelve a su mediana | Sí, 20, confianza baja | Sí | — |
| Fabricar Hoguera básica (317) | Marginal: 317 es el 84 % de todo lo que se vende | Sí, 317, confianza alta | No | El lote cuenta con tu parte de las ventas (`SELL_SHARE`): 188 |
| Fabricar Sabiola ahumada (260) | Arriesgado: el depósito (24c) es mayor que el margen (23c) | Sí, 260 | A medias | Prueba de esfuerzo: el lote se encoge si con la mitad de ventas da pérdidas. Aquí aguanta (quedan 9c por unidad) |
| Revender Polvo mágico (34) | No: cada día vuelve a haber género a 28s; no se vende a 38s | Sí (no cabía en el presupuesto) | No | El precio de reventa no pasa de un 15 % sobre lo más barato de cada día |
| Rebote: Tinte viridiano | No: baja cada día desde hace 11 (181s → 60s) | Sí | No | Una cuesta abajo no es un bache (`sliding`) |
| Rebote: Pulmón de jabalí | No: lo más barato lleva una semana entre 26s y 39s; hoy 35s | Sí («43 % bajo su mediana») | No | El rebote se mide con lo más barato de cada día, no con el valor de mercado |
| Sequía: Pececito luminoso | No: hoy ha saltado de 23c a 33c; es comprar el pico | Sí | No | Si hoy está un 25 % sobre su mediana de 7 días, no entra |
| Evento: Flor de peste (11) | Sí, pequeña: escenario claro, stop razonable | Sí | Sí | Aviso del depósito al publicar |
| Renta: transmutar arcanita | Sí: 13,9 oro el cristal, 39,5 la arcanita, estable una semana | 23 oro por uso, 12 al día | Sí | — |

De las que entraron después de los cambios: la Sopa de pargo nocturno (rebote) y el Antídoto fuerte (al precio del vendedor: no se pierde, pero ocupa 19 huecos) pasan la revisión a mano.

**Lo que explica casi todos los desacuerdos:** el «valor de mercado» (media del 15 % más barato) salta al escalón de arriba cuando el de abajo es fino. Sirve para saber cuánto cuesta comprar una cantidad, pero no para saber a cuánto se vende: para eso vale lo más barato de cada día.

## Pruebas

En `tests/run_tests.py`, bloque «Pasada del 25/11»: días medidos, rotación, calibración con y sin rotación, recolocaciones (seis casos), marca de la regla, precedencia de escaneos y API, reventa sin variantes, suelo del vendedor, catálogo y «qué aprender» con tu parte. Bloque «Auditoría a mano»: techo de reventa, lote con tu parte, prueba de esfuerzo del depósito, rebote (tres casos) y sequía (dos).
