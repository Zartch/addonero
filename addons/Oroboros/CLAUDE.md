# Oroboros — contexto para trabajar en local

Addon del proyecto Addonero (ver `../../CLAUDE.md`). Los comandos de abajo se ejecutan desde `addons/Oroboros/`.

Addon de subasta para **WoW Forever** + planificador de oro en Python. El usuario (Zartch) habla español; los textos del addon, de la página y de la documentación van en español.

Lee `README.md` (uso y funciones) y `docs/arquitectura.md` (decisiones y reglas) antes de cambiar nada.

## Estructura

- `Oroboros/` — el addon (Lua 5.1, API moderna de Midnight, interfaz 16001 de Forever; el TOC también lista 120105). Archivos: `Core`, `DB`, `Scanner`, `Professions`, `Ledger`, `Queue`, `UI`.
- `tools/oroboros_export.py` — SavedVariables → SQLite/JSON (con `--auctionator`, añade los precios de Auctionator).
- `tools/auctionator_source.py` — lee `Auctionator.lua` (base en CBOR) y la mezcla en el SQLite.
- `tools/oroboros_plan.py` — planificador: rutas, transformaciones, qué aprender, inventario → `plan.html`.
- `tools/oroboros_ideas.py` — ideas de especulación y cartera.
- `tools/planner_ui.html` — plantilla de la página (el plan se incrusta en `/*__PLAN__*/null`).
- `tools/make_synthetic.py` — datos inventados para probar.
- `tools/catalog.json` — lo que el juego no da (valores de ejemplo).
- `tests/` — simulación de la API de WoW (`mock_wow.lua`) y pruebas (`run_tests.py`).

## Comandos

```
pip install lupa                      # una vez
python tests/run_tests.py             # debe acabar en "TODO OK"

python tools/make_synthetic.py --out work/Oroboros.lua
python tools/oroboros_export.py work/Oroboros.lua --sqlite work/oroboros.sqlite
python tools/oroboros_plan.py --db work/oroboros.sqlite --html work/plan.html --routes work/rutas --synthetic
```

Con datos reales: `python tools/oroboros_export.py --find "<carpeta WoW>" --sqlite work/oroboros.sqlite`.

Para probar el addon en el juego, enlaza la carpeta en vez de copiarla (así los cambios se ven con `/reload`):

- Windows (unión, sin administrador): `mklink /J "<WoW>\_forever_\Interface\AddOns\Oroboros" "<repo>\addons\Oroboros\Oroboros"`
- Instalación del usuario: `F:\World of Warcraft\_forever_\` (cliente 1.60.1, interfaz 16001).
- macOS/Linux: `ln -s <repo>/addons/Oroboros/Oroboros "<WoW>/<Forever>/Interface/AddOns/Oroboros"`

## Reglas que no se rompen

- **Un clic o una tecla por acción protegida** (comprar, publicar, fabricar). Nada de automatizarlo: es botting y hay baneo.
- El addon no tiene red ni escribe archivos: solo SavedVariables (se escriben en `/reload` o al salir).
- Los números los calcula código; un LLM solo explica o propone ideas.
- Los objetivos de las ideas son escenarios, no predicciones: siempre con riesgo y stop.
- Cada cambio de lógica lleva su comprobación en `tests/run_tests.py`.
- Eventos o funciones del juego que puedan no existir en Forever: registrar con `ns.On` (ya usa `pcall`) o comprobar antes de llamar.

## Estado

- Nada se ha probado todavía en el cliente real: solo con la simulación y con datos sintéticos.
- Lo primero que hay que validar en el juego: carga del addon y número de interfaz, lectura del banco (¿pestañas o clásico?), libro de compras (compra de equipo, facturas del correo), tooltip.

## Fuente de precios: Auctionator (hecho, sin probar en el juego)

El usuario usa **Auctionator** con su escaneo completo activado. Detalle y referencias a su código en `docs/fuentes-de-precios.md`.

- En el juego: si Auctionator hace el escaneo completo, `Scanner.FullScan` no llama a `ReplicateItems`; Oroboros lee su resultado al llegar `REPLICATE_ITEM_LIST_UPDATE` (lectura pasiva). `/oro scan forzar` lanza el propio.
- Fuera del juego: `oroboros_export.py --auctionator` mezcla su base (precio, histórico de 21 días y cantidad). Gana Oroboros si tiene dato del mismo día.
- Sin profundidad real, el planificador la estima y no da confianza alta (`stats()["depth_est"]`).

Por validar en el juego: que la lectura pasiva funciona con el escaneo de Auctionator; el número de interfaz; si la subasta es única por reglas regionales (Auctionator usa la clave `"PvE"`, Oroboros `Reino-Facción`; si es única, pasar a esa clave); duraciones de publicación (Auctionator usa 2/8/24 h en Forever, `postDuration` asume 12/24/48 h).

Goblinomics (instalado) es contabilidad y patrimonio sobre precios de TSM/Auctionator: no escanea, no ejecuta acciones ni planifica. Se solapa con el libro de compras e inventario de Oroboros, no con el escaneo, la cola ni el planificador.

Otros pendientes: ver `docs/arquitectura.md`, sección Pendiente.
