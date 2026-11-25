# Oroboros — contexto para trabajar en local

Addon del proyecto Addonero (ver `../../CLAUDE.md`). Los comandos de abajo se ejecutan desde `addons/Oroboros/`.

Addon de subasta para **WoW Forever** + planificador de oro en Python. El usuario (Zartch) habla español; los textos del addon, de la página y de la documentación van en español.

Lee `README.md` (uso y funciones) y `docs/arquitectura.md` (decisiones y reglas) antes de cambiar nada.

## Estructura

- `Oroboros/` — el addon (Lua 5.1, API moderna de Midnight, interfaz 16001 de Forever; el TOC también lista 120105). Archivos: `Core`, `DB`, `Scanner`, `Professions`, `Ledger`, `Queue`, `UI`.
- `tools/oroboros_export.py` — SavedVariables → SQLite/JSON (con `--auctionator`, añade los precios de Auctionator).
- `tools/auctionator_source.py` — lee `Auctionator.lua` (base en CBOR) y la mezcla en el SQLite.
- `tools/oroboros_archive.py` — añade los últimos 12 escaneos del juego a `work/archivo.sqlite` (permanente).
- `tools/oroboros_hours.py` — franjas horarias: lo que desaparece (total y barato) y el precio por franja.
- `tools/oroboros_watch.py` — vigilante: cuando el juego guarda Oroboros.lua, exporta, archiva y genera el plan y Resumen.lua (`--once` para una vez).
- `tools/oroboros_api.py` — subasta con la API oficial de Blizzard, sin entrar al juego (`docs/api-subasta-blizzard.md`, apartado 0): descarga cada hora las casas 111/114/117 (Alianza/Horda/Aguasnegras de nuestro grupo) con `If-Modified-Since`, guarda en el archivo (`api_houses`, `api_snaps`, `api_live`, `api_item_hour` 14 días, `api_band_week` acumulada al meter cada foto, `daily` con `src='api'`), estima vendidas/caducadas/canceladas por id de subasta, pide nombres (`static-forever-eu`) y calibra con el libro (`--calibrar`). Credenciales en `work/bnet.env` o `BNET_CLIENT_ID`/`BNET_CLIENT_SECRET`.
- `tools/oroboros_panel.py` — panel de escritorio: hilo de descarga cada hora + servidor en 127.0.0.1:8737 (página del plan con pestañas Inicio, Subasta y Ventas, JSON en `/api/*`) + ventana de Edge en modo aplicación. Una sola copia (mutex).
- `tools/oroboros_summary.py` — resumen de precios por objeto → `Oroboros/Resumen.lua` (ignorado en git), que lee el panel `Oroboros/PriceHistory.lua`.
- `tools/oroboros_plan.py` — planificador: rutas, transformaciones, qué aprender, inventario → `plan.html`.
- `tools/oroboros_farm.py` — dónde farmear (`docs/farmeo.md`): combina lo medido (`Oroboros/Farm.lua`) con la estimación de AzerothCore (`tools/azerothcore.py`, en `work/fuentes/`) y la recolección de GatherMate2 (`tools/gathermate.py`, `tools/gather_skill.json`); escribe la pestaña Farmear y `Oroboros/Farmeo.lua` (ignorado en git), que lee `Oroboros/FarmPanel.lua` (`/oro farmear`).
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
- La API de Blizzard solo lee. Las credenciales (`work/bnet.env`) y las fotos (`work/api/`) nunca van a git ni salen en mensajes o registros. Las pruebas no usan la red (cliente falso y fotos sintéticas).

## Estado

- Probado en el cliente real: carga del addon, interfaz 16001 y escaneo completo propio. El resto solo con la simulación y datos sintéticos.
- API de Blizzard y panel (24/11): probados con datos reales (descarga, archivo, plan, Resumen.lua y rutas del panel, sin la ventana). Pendiente: que la ventana de Edge se vea bien, que las «vendidas» sean ventas (la calibración del 24/11 pasó contando recolocaciones; desde el 25/11 pide además una rotación creíble de la casa, ver fase 8 de la hoja de ruta) y confirmar con un personaje de la Horda que su casa es la 114.
- Lo siguiente que hay que validar en el juego: lectura del banco (¿pestañas o clásico?), libro de compras (compra de equipo, facturas del correo), tooltip.
- Farmeo, por validar en el juego: que se cuentan muertes y botín, el aviso al entrar en un sitio, que los nombres resueltos (`OroborosDB.farmPlaces`) caen donde están las criaturas, y los niveles de `tools/gather_skill.json`.

## Fuente de precios: Auctionator (hecho, sin probar en el juego)

El usuario usa **Auctionator** con su escaneo completo activado. Detalle y referencias a su código en `docs/fuentes-de-precios.md`.

- En el juego: si Auctionator hace el escaneo completo, `Scanner.FullScan` no llama a `ReplicateItems`; Oroboros lee su resultado al llegar `REPLICATE_ITEM_LIST_UPDATE` (lectura pasiva). `/oro scan forzar` lanza el propio.
- Fuera del juego: `oroboros_export.py --auctionator` mezcla su base (precio, histórico de 21 días y cantidad). Gana Oroboros si tiene dato del mismo día.
- Sin profundidad real, el planificador la estima y no da confianza alta (`stats()["depth_est"]`).

Comprobado en el cliente real (18/11/2026): el addon carga con interfaz 16001 (cliente 1.60.1.70959) y el escaneo completo propio guarda ~6900 objetos con profundidad. `/oro cliente` dio: reino interno `CAMWOWEU5Realm5PvE`, nombres regionales `true`, `GetRegionalRulesetName()` = `nil`, sin reinos conectados. Clave de mercado actual: `CAMWOWEU5Realm5PvE-<Facción>` (se mantiene).

Por validar en el juego: la lectura pasiva con el escaneo completo de Auctionator (el usuario no lo tiene activado; escanea con Oroboros); duraciones de publicación (Auctionator usa 2/8/24 h en Forever, `postDuration` asume 12/24/48 h).

Goblinomics (instalado) es contabilidad y patrimonio sobre precios de TSM/Auctionator: no escanea, no ejecuta acciones ni planifica. Se solapa con el libro de compras e inventario de Oroboros, no con el escaneo, la cola ni el planificador.

## Siguiente trabajo: hoja de ruta por fases

**Lee primero `docs/hoja-de-ruta.md`.** Ahí está qué esperamos de cada fase (modelo de datos, seguimiento de precios al estilo Camel, automatización, cálculos y, desde el 24/11, las fases 5 a 8 del repaso de las maneras de ganar oro: están hechas fuera del juego; cada una lista lo que queda por comprobar) y en qué estado está; el detalle técnico está en `docs/modelo-y-seguimiento.md`. Se trabaja una fase cada vez: plan en `docs/planes/`, ejecución con pruebas y commits, y al acabar se actualiza el estado en la hoja de ruta.

Otros pendientes: ver `docs/arquitectura.md`, sección Pendiente.
