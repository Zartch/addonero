# Oroboros — contexto para trabajar en local

Addon del proyecto Addonero (ver `../../CLAUDE.md`). Los comandos de abajo se ejecutan desde `addons/Oroboros/`.

Addon de subasta para **WoW Forever** + planificador de oro en Python. El usuario (Zartch) habla español; los textos del addon, de la página y de la documentación van en español.

Lee `README.md` (uso y funciones) y `docs/arquitectura.md` (decisiones y reglas) antes de cambiar nada.

## Estructura

- `Oroboros/` — el addon (Lua 5.1, API moderna de Midnight, interfaz 120105). Archivos: `Core`, `DB`, `Scanner`, `Professions`, `Ledger`, `Queue`, `UI`.
- `tools/oroboros_export.py` — SavedVariables → SQLite/JSON.
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

- Windows (cmd como administrador): `mklink /D "<WoW>\<Forever>\Interface\AddOns\Oroboros" "<repo>\addons\Oroboros\Oroboros"`
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

## Siguiente tarea: no solapar con el addon de subasta que ya está instalado

El usuario ya usa un addon de subasta (lo llamó "acuttioner": comprobar si es **Auctioneer** o **Auctionator**). Ese addon ya escanea y guarda precios. El escaneo completo (`C_AuctionHouse.ReplicateItems`) tiene un límite de uno cada 15 minutos **compartido entre todos los addons**, así que escanear dos veces no sirve.

Plan:

1. Mirar qué hay instalado: `<WoW>/<Forever>/Interface/AddOns/` y `WTF/Account/<CUENTA>/SavedVariables/` (y `.../<Reino>/<Personaje>/SavedVariables/`).
2. Leer el código y los SavedVariables de ese addon para ver qué guarda de verdad: precio por objeto, histórico por día, cantidad publicada, y si expone una API para otros addons. No fiarse de la memoria: comprobarlo en los archivos. (Pista sin verificar: Auctionator suele tener `Auctionator.API.v1.GetAuctionPriceByItemID(nombreAddon, itemID)` y guarda en `AUCTIONATOR_PRICE_DATABASE`.)
3. Hacer la fuente de precios intercambiable:
   - En el juego: si el otro addon está cargado, `Scanner.FullScan` no llama a `ReplicateItems`; `DB` toma una foto diaria de sus precios para nuestro histórico.
   - Fuera del juego: `oroboros_export.py` puede leer directamente sus SavedVariables.
4. Ver qué pierde el planificador si esa fuente no da cantidad publicada ni profundidad (hoy las usa para: cuántas unidades proponer, ventas por día, ideas de "oferta que se seca" y "progresión"). Si faltan, mantener una búsqueda puntual propia (`Scanner.Search`) solo para los objetos que el plan usa.
5. Mantener el escaneo propio como alternativa cuando el otro addon no esté.

Otros pendientes: ver `docs/arquitectura.md`, sección Pendiente.
