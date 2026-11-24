# Fase 6: catálogo de Forever al día — plan

**Objetivo:** que las ideas de evento y el plan conozcan lo que Forever cambió, antes de que abran las bandas el 9/12/2026. Cada dato lleva su fuente y dice si está comprobado.

**Qué cuenta como comprobado:** lo que se ve en nuestros propios datos (objetos y recetas del juego, ProfessionDB, la subasta) o en una nota oficial de Blizzard. Lo que solo dicen guías va como «sin comprobar».

## Lo que dicen nuestros datos (24/11)

- **Elixires nuevos:** no son tres, son 13 de nivel de objeto 55 (objetos 250328 a 250351), todos ya en subasta entre 0,7 y 1,6 oro. Comprobado.
- **Frascos naturales:** cuatro (274273 a 274276), receta de Alquimia 300 en ProfessionDB, pila de 20. Aún no hay ninguno en subasta. Comprobado que existen; su bonificación en Hyjal y Barrow Deeps, sin comprobar.
- **Pociones de sanación:** las seis (menor a sublime) son recetas de Primeros auxilios en ProfessionDB; Alquimia hace las «descoloridas». Comprobado. El plan ya lo calcula bien porque la profesión de cada receta sale de ProfessionDB, no del catálogo.
- **Loto negro y Cristal Arcano:** a 8,4 y 14,4 oro, lejos del techo de 50.

## Cambios

1. `tools/catalog.json`
   - `facts`: lista de datos de Forever con `text`, `source`, `verified` y, si está comprobado, `how`.
   - `price_caps`: techo de precio por objeto (Loto negro 13468 y Cristal Arcano 12363 a 50 oro), con fuente y `verified: false`.
   - `server.raid_reset_weekday`: 2 (miércoles, lunes = 0), sin comprobar para Forever (es el día de la UE en el resto de versiones, y el 9/12 cae en miércoles).
   - `events`: la apertura de bandas se parte en pociones y hierbas, elixires (con los 13 nuevos) y frascos (con los naturales).
2. `tools/oroboros_ideas.py`
   - Techo: el objetivo de una idea no pasa del techo del objeto, y la idea lo dice. Si con el techo ya no gana un 5 %, la idea desaparece sola por la regla que ya existe.
   - Evento: la salida dice la fecha del primer reinicio después del evento.
   - Ciclo semanal: dice si el día caro coincide con el reinicio (ese día o el anterior) o no.
   - `outlook["facts"]`: los datos del catálogo, para la página.
3. `tools/planner_ui.html`: en Ideas, un desplegable «Lo que el catálogo da por cierto de Forever» con cada dato, su marca (comprobado o sin comprobar) y la fuente.
4. Pruebas en `tests/run_tests.py`: techo, fecha de reinicio, coincidencia del ciclo semanal, y que cada dato y cada techo del catálogo real tengan fuente y marca.

## Fuera de esta fase

- Mínimo de beneficio por clic (anotado en la hoja de ruta).
- Usar el techo en reventas o en el valor del inventario: hoy los precios están muy por debajo.
