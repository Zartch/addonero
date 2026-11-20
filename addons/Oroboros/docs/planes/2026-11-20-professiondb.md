# ProfessionDB para «qué aprender» (y dos arreglos del plan)

Diseño y plan del 20/11/2026, **aprobado por el usuario**. Cambio mediano.

## Para qué

En Forever el juego no dice qué nivel pide una receta no aprendida ni dónde se aprende. Por eso 230 recetas salían como «nivel sin comprobar», y «si cambiaras de profesión» se basaba en los ejemplos inventados de `catalog.json`.

ProfessionDB (LibProfessionDB-1.0, licencia MIT; el usuario la tiene instalada) trae datos propios de Forever, sacados del propio cliente (build 1.60.1.70938):
- nivel requerido (si viene de Vanilla, va marcado);
- umbrales de dificultad, reactivos y objeto que se fabrica;
- origen de la receta: instructor, vendedor con precio, misión, botín o contenedor;
- recetas que se aprenden con la profesión y recetas que nunca existieron.

Comprobado con los datos reales: 364 de las 366 recetas del usuario están en ProfessionDB, y 341 con nivel requerido.

## Enfoque

El **planificador lee los archivos de datos** de ProfessionDB desde la carpeta de WoW, sin cargarla en el juego (allí no carga: le falta Ace3) y sin copiar sus datos al repositorio. Solo usa la biblioteca estándar: `tools/professiondb.py` encuentra cada `lib:LoadXxx(...)` y analiza la tabla con el `LuaParser` del exportador.

Se descartan:
- usarla dentro del juego: necesita Ace3 y unos 38 MB;
- copiar los datos al repositorio: 38 MB que habría que actualizar a mano.

## Diseño

- **`professiondb.load(base)`** devuelve `{spell_id: {...}}` con:
  - profesión, nombre en español, nivel requerido y si es prestado de Vanilla;
  - dificultad, reactivos y objeto fabricado;
  - orígenes con su número real de fuentes, y precio de vendedor (en cobre o en otra moneda);
  - «con la profesión», «nunca existió» y pergamino.

  **`professiondb.find(path)`** localiza `Interface/AddOns/ProfessionDB/Data/Forever` subiendo desde `Oroboros.lua`.
- **Exportador**: `--professiondb [RUTA]` (por defecto la busca y, si no está, sigue sin ella). Escribe en el SQLite del plan:
  - `pdb_recipes(recipe_id, prof_id, profession, name, required_skill, req_borrowed, d1, d2, d3, d4, crafted_item, sources, vendor_copper, vendor_currency, vendor_names, acquire, hidden)`;
  - `pdb_reagents(recipe_id, item_id, qty)`.
- **Planificador, «qué aprender»**:
  - En las recetas de tus profesiones, el nivel requerido sale de ProfessionDB, salvo que `catalog.json` diga otra cosa.
  - Estado de cada una: al alcance o «te faltan N puntos». Solo es «desconocido» si ProfessionDB tampoco lo sabe.
  - Dónde se aprende, en una línea: «instructor», «vendedor Gloria Femmel (4s 50c)», «misión», «botín (951 criaturas)», «se aprende con la profesión». Más «(dato de Vanilla)» si es prestado.
  - Coste de aprender, del vendedor si se conoce.
  - Las recetas que nunca existieron se quitan.
- **«Si cambiaras de profesión»**: sale de ProfessionDB para las profesiones que no tienes, solo con recetas cuyo objeto se vende en la subasta; se muestran las mejores 30. Sin ProfessionDB, sigue saliendo de `catalog.json`.
- **Nombres de profesión**: 171 Alquimia, 164 Herrería, 165 Peletería, 197 Sastrería, 202 Ingeniería, 333 Encantamiento, 185 Cocina, 129 Primeros auxilios, 356 Pesca, 186 Minería, 182 Botánica, 393 Desuello.

## Arreglos del plan (incluidos en la propuesta aprobada)

1. **Lotes de prueba antes que reventas de riesgo**: dentro del 30 % reservado a lo de confianza baja, lo que no es lote de prueba (sobre todo las reventas) puede usar como mucho la mitad (15 %), y el resto queda para los lotes de prueba de fabricación.
2. **Subasta o vendedor, por objeto**: la decisión «vale muy poco: al vendedor» se toma con todo lo que tiene el personaje de ese objeto (bolsas + banco + banda), no por sitio.

## Pruebas

- Lector, con un ProfessionDB en miniatura escrito por la prueba:
  - nivel, nivel prestado, reactivos y nombre en español;
  - orígenes con su número real de fuentes y el precio del vendedor;
  - «con la profesión» y «nunca existió».
- Exportador con `--professiondb`: crea `pdb_recipes`; sin ProfessionDB, no falla.
- Planificador:
  - una receta desconocida pasa a «te faltan N puntos» con el dato de ProfessionDB, y su veredicto dice dónde se aprende;
  - las nunca existidas desaparecen;
  - «si cambiaras de profesión» sale de ProfessionDB.
- Arreglos: lo de confianza baja que no es lote de prueba ≤ 15 % del presupuesto; el mismo objeto en bolsas y banco recibe la misma decisión.
