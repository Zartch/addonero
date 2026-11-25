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

## Lo que no se cambia

- Las horas ya guardadas no se pueden volver a clasificar: las fotos crudas no se conservan. Las franjas de la pestaña Horas seguirán mezclando horas de antes y de después durante dos semanas.
- La precisión de las «vendidas» sigue sin medirse de verdad. Haría falta que el addon apuntara tus subastas que caducan o que cancelas, para ver cuántas de esas da por vendidas la estimación.

## Pruebas

En `tests/run_tests.py`, bloque «Pasada del 25/11»: días medidos, rotación, calibración con y sin rotación, recolocaciones (seis casos), marca de la regla, precedencia de escaneos y API, reventa sin variantes, suelo del vendedor, catálogo y «qué aprender» con tu parte.
