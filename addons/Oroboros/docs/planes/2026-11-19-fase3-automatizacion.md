# Fase 3: automatización, plan de implementación

> **Para quien lo ejecute:** tarea a tarea (superpowers:executing-plans). Pasos con casillas `- [ ]`.

**Objetivo:** que el usuario solo tenga que pasar por la subasta. El escaneo se lanza solo al abrirla, y se ve claramente. Un vigilante fuera del juego procesa los datos cuando el juego los guarda.

**Diseño:** `docs/hoja-de-ruta.md` (fase 3) y `docs/modelo-y-seguimiento.md` (fase 3).

## Restricciones globales

- Escanear no es una acción protegida (aceptado por el usuario el 19/11). Nada más se automatiza.
- Visible (petición del usuario): durante cualquier escaneo, el botón «Escaneo completo» aparece pulsado y desactivado con el texto «Escaneando…». La línea de estado muestra el avance («Escaneo automático: 3000 / 7000»). El chat avisa al empezar y al acabar. Al terminar, o al cerrar la subasta, el botón vuelve a «Escaneo completo».
- Configuración: `autoscan` = 1 por defecto; `/oro set autoscan 0` lo apaga.
- Python solo con biblioteca estándar. El vigilante no toca nada del juego.

## Foco de revisión

1. Abrir la subasta antes de 15 minutos desde el último escaneo (propio o de Auctionator): no lanza nada ni avisa en exceso; el pie dice cuánto falta.
2. Auctionator con su escaneo completo activado: no se lanza el propio; se lee el suyo, como ya se hace.
3. Cerrar la subasta a mitad de escaneo: el botón vuelve a su estado normal.
4. El juego guardando `Oroboros.lua` mientras el vigilante mira: espera a que la fecha del archivo lleve 10 s sin cambiar.
5. Un fallo del exportador: el vigilante lo muestra y sigue vigilando.

---

### Tarea 1: escaneo automático visible (y el panel deja de tapar la ventana)

**Archivos:** `Oroboros/Core.lua` (`autoscan` en `DEFAULTS`, versión 0.7.0, ayuda de `/oro set`), `Oroboros/Scanner.lua`, `Oroboros/UI.lua`, `Oroboros/PriceHistory.lua`, `Oroboros/Oroboros.toc` (0.7.0), `tests/run_tests.py`.

**Interfaces:**
- `Scanner.FullScan(force, auto)`. Con `auto`, el estado y el chat dicen «Escaneo automático».
- `Scanner.TryAutoScan()`, que se llama 1 s después de `AUCTION_HOUSE_SHOW` y devuelve `true` si lanza el escaneo.
- `UI.SetScanning(on, label)`, que pone el botón en «Escaneando…», pulsado y desactivado, o lo devuelve a su estado normal.
- `PriceHistory.AnchorTarget()`, que devuelve `"OroborosFrame"` si la ventana de Oroboros está visible, `"AuctionHouseFrame"` si solo lo está la subasta, o `nil`.

- [ ] Prueba (falla):
  - Con el límite cumplido, abrir la subasta y avanzar los temporizadores llama a `ReplicateItems`; el botón dice «Escaneando…» y el chat avisa del escaneo automático.
  - Al llegar el resultado, el botón vuelve a «Escaneo completo» y el estado dice «Escaneo automático leído: …».
  - No se lanza si no han pasado 15 min, con `autoscan` 0, ni con el escaneo completo de Auctionator activado.
  - Cerrar la subasta a mitad devuelve el botón.
  - Con la ventana de Oroboros visible, el panel se ancla a ella.
- [ ] Implementar; pruebas en verde; commit.

### Tarea 2: vigilante fuera del juego

**Archivos:** crear `tools/oroboros_watch.py`; `tests/run_tests.py`.

**Interfaces:**
- `watch(path, run, interval=30, settle=10, cycles=None, clock=time.time, sleep=time.sleep) -> int`: llama a `run()` cada vez que la fecha del archivo cambia y lleva `settle` segundos estable. Devuelve las ejecuciones; `cycles` limita las vueltas, para las pruebas.
- `pipeline(sv_path, work_dir) -> bool`: ejecuta exportador (con `--archive`, `--auctionator` y `--sqlite`) y plan (`--archive`, `--html`, `--routes`).
- Ejecutable: `python tools/oroboros_watch.py --find "<WoW>" [--work work] [--once]`.

- [ ] Prueba (falla), con reloj y espera falsos:
  - Un cambio de fecha seguido de estabilidad → 1 ejecución.
  - Un cambio que sigue cambiando → espera.
  - Sin cambios → 0.
  - Si `run` lanza un error, se registra y sigue.
  - `--once` con los datos sintéticos genera `plan.html` y `Resumen.lua` en una carpeta temporal.
- [ ] Implementar; pruebas en verde; commit.

### Tarea 3: documentación

- [ ] README:
  - escaneo automático (cómo se ve y cómo apagarlo);
  - vigilante: arrancarlo a mano, y con el Programador de tareas de Windows al iniciar sesión (comando `schtasks` documentado; no se crea la tarea sin que el usuario lo pida).
- [ ] Hoja de ruta: fase 3 hecha, con lo aprendido y lo que hay que comprobar en el juego. Commit.
