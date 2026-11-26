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

- Tras la segunda auditoría: `falling`/`streak`/`FRESH` en reventas, Aguasnegras y rebote; techo `LOW_CEIL` en el precio de venta de las recetas; ciclo semanal con lo más barato de cada día; un depósito perdido en el beneficio de cada idea; tope por tu oro y profesión nueva sin plazo en «qué aprender»; confianza baja en el farmeo con poca muestra.

## Lo que no se cambia

- Las ventas al día «medidas con tus escaneos» son lo que baja lo publicado de un día a otro: no ve lo que se vende y se repone, y en equipo con pocas unidades cuenta caducidades. Sigue siendo lo mejor que hay hasta que la API se calibre; por eso el equipo sale siempre con confianza baja.
- «Qué tienes» manda al vendedor lo que vale menos de ~20 platas en total aunque en subasta valga varias veces más (Sombrerrosa, Pluma ligera). Es poco dinero y ahorra clics; queda como está.
- «Qué tienes» no avisa de que una receta que llevas encima no está aprendida (Receta: poción de resistencia a la magia).

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

## Segunda auditoría a mano (25/11, plan de las 12:25): las maneras que faltaban

Mismo método (datos crudos, cuenta a mano, comparar), ahora con reventas con datos nuevos, Aguasnegras, ideas, «qué aprender», «qué tienes» y farmeo.

| Propuesta | A mano | Programa | Coinciden | Qué se cambió |
|---|---|---|---|---|
| Reventa: Linguini de almejas (64, **en el plan**) | No: 40s → 19s → 10s → 9s → 8s en cinco días; el escalón de arriba es género viejo | Sí | No | No se compra un precio que viene bajando (`falling`: cuesta abajo o racha, también con 4 días de histórico) |
| Reventa: Cuervo de piedra (4 por 34 oro) | No: 20 → 9,5 → 8 → 6 oro; solo la de 6 sería defendible | Sí (no cabía) | No | Lo mismo |
| Reventa: Estofado de langosta (227 de 229) | No: ayer lo más barato ya estaba a 4s 45c | Sí (no cabía) | No | «Ayer ya estaba a este precio» se mira con lo más barato, no con el valor de mercado |
| Reventa: Tratado sobre Enfoque, Aro radiante | Pequeñas y defendibles, con ventas sin comprobar | Sí, confianza baja | Sí | — |
| Aguasnegras (2 objetos, 54 platas) | No merece el viaje | «No compensa el viaje» | Sí | No entra lo que en tu casa viene bajando |
| Rebote: Patrón: guanteletes de tormenta (**en el plan**) | No: 4 → 3,5 → 3 → 2 → 1,3 oro, cinco días bajando | Sí («no venía bajando») | No | Racha de bajadas (`streak`): tres días seguidos que suman un 15 % |
| Rebote: Granada de torio (**en el plan**) | No: ayer ya estaba a 20s; depósito de 9s para ganar 11s | Sí | No | Si ayer ya estaba a este precio no es un bache de hoy (`FRESH`); el beneficio de una idea cuenta un depósito perdido |
| Rebote: Almófar de oro duro (entra tras los cambios) | Sí: una semana entre 2,7 y 4 oro y hoy 5 unidades a 1,9 | Sí | Sí | — |
| Evento: Elixir de entereza superior (3) | Sí, pequeña; el +30 % es una suposición y lo dice | Sí | Sí | — |
| Aprender: Corona viva (**en la portada**: «34 oro al día, se paga en menos de un día») | No: 214 oro de materiales por unidad con 45 oro, y una profesión que no tienes | Sí | No | No se fabrica más de lo que tu oro compra; una profesión nueva no dice en cuántos días se paga; la portada solo muestra tus profesiones |
| Aprender: transmutar arcanita, frascos | Sí, cuando llegues a 275/300 | Sí | Sí | — |
| Fabricar: Venado magro (entra tras los cambios) | Sí, pero a 1s 80c–2s (lo más barato de cada día), no a 2s 53c | Sí, a 2s 53c | A medias | El precio de venta de cualquier receta tiene el mismo techo que las reventas (`LOW_CEIL`) |
| Qué tienes: hierbas y paños a subasta, restos al vendedor | Sí en lo grande. En lo pequeño, mandar al vendedor lo que vale menos de ~20 platas pierde unas 70 platas en total | Sí | Sí, con matiz | — (ver «no se cambia») |
| Farmeo medido: Base de Ventura y Cía., 48,8 oro/h | No: 5 muertes en 74 segundos y un objeto verde | Sí, confianza media, la primera | No | Confianza baja con menos de 10 muertes y 5 minutos, y por detrás de lo medido con muestra |

**Lo que se repite:** la primera auditoría quitó el valor de mercado de reventas e ideas, pero seguía en tres sitios (el «ayer ya estaba a este precio», el precio de venta de las recetas y el ciclo semanal). Y «hundido respecto a su mediana» no distingue un bache de una bajada: hace falta mirar el orden de los días.

**Una prueba que bailaba:** «con 3 días de API, las ventas salen de la API» pasaba por la mañana y fallaba a partir de las 11:45, porque según la hora el histórico de la prueba daba 2 o 3 bajadas. Ahora la prueba quita esa medida a propósito.

## Pruebas

En `tests/run_tests.py`, bloque «Pasada del 25/11»: días medidos, rotación, calibración con y sin rotación, recolocaciones (seis casos), marca de la regla, precedencia de escaneos y API, reventa sin variantes, suelo del vendedor, catálogo y «qué aprender» con tu parte. Bloque «Auditoría a mano»: techo de reventa, lote con tu parte, prueba de esfuerzo del depósito, rebote (tres casos) y sequía (dos). Bloque «Segunda auditoría a mano»: racha y cuesta abajo, reventa que viene bajando, reventa que ayer ya estaba a ese precio, rebote (dos casos más), depósito en las ideas, «qué aprender» (tu oro, profesión nueva, sin oro) y farmeo con poca muestra.
