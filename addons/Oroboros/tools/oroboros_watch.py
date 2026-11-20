#!/usr/bin/env python3
"""
Oroboros: vigilante (fase 3, docs/hoja-de-ruta.md).

Mira cada `--interval` segundos la fecha de `Oroboros.lua`. Cuando el juego la cambia (al salir o con
/reload) y lleva `--settle` segundos sin cambiar, ejecuta:
  exportar (archivo + Auctionator + SQLite del plan + Resumen.lua) → plan (página y rutas)
No toca nada del juego: solo lee sus SavedVariables y escribe en `work/` y en Resumen.lua.

Uso:
  python oroboros_watch.py --find "F:/World of Warcraft/_forever_"          # vigilar
  python oroboros_watch.py --find "F:/World of Warcraft/_forever_" --once   # procesar ya, una vez
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_WORK = os.path.normpath(os.path.join(HERE, "..", "work"))
LOG_FILE = None          # --log: también se escribe aquí (para arrancarlo sin consola)


def _log(*a):
    line = " ".join([time.strftime("[%d/%m %H:%M:%S]")] + [str(x) for x in a])
    print(line, flush=True)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + chr(10))


def watch(path, run, interval=30, settle=10, cycles=None, clock=time.time, sleep=time.sleep,
          mtime=None, log=_log):
    """Llama a run() cada vez que la fecha de `path` cambia y lleva `settle` s estable.
    Devuelve las ejecuciones que acabaron bien. `cycles` limita las vueltas (pruebas)."""
    mtime = mtime or (lambda p: os.path.getmtime(p) if os.path.exists(p) else None)
    done = mtime(path)
    pending = since = None
    ok = n = 0
    while cycles is None or n < cycles:
        n += 1
        m = mtime(path)
        if m is not None and m != done:
            if m != pending:
                pending, since = m, clock()
            elif clock() - since >= settle:
                try:
                    run()
                    ok += 1
                except Exception as e:          # se registra y se sigue vigilando
                    log(f"Error al procesar: {e}")
                done, pending = m, None
        else:
            pending = None
        sleep(interval if pending is None else min(interval, settle))
    return ok


def pipeline(sv_path, work_dir, resumen=None, log=_log, ac_dir=None):
    """Exporta y genera el plan. Lanza RuntimeError si algún paso falla.
    Con AzerothCore descargado (ac_dir), el plan lleva también la estimación del farmeo."""
    os.makedirs(work_dir, exist_ok=True)
    py = sys.executable
    archive = os.path.join(work_dir, "archivo.sqlite")
    sqlite_ = os.path.join(work_dir, "oroboros.sqlite")
    steps = [
        ("exportar", [py, os.path.join(HERE, "oroboros_export.py"), sv_path, "--auctionator",
                      "--archive", archive, "--sqlite", sqlite_] + (["--resumen", resumen] if resumen else [])),
        ("plan", [py, os.path.join(HERE, "oroboros_plan.py"), "--db", sqlite_, "--archive", archive,
                  "--html", os.path.join(work_dir, "plan.html"), "--json", os.path.join(work_dir, "plan.json"),
                  "--routes", os.path.join(work_dir, "rutas"), "--wow", sv_path]
                 + (["--azerothcore", ac_dir] if ac_dir else [])),
    ]
    for name, cmd in steps:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        for line in (r.stdout or "").strip().splitlines():
            if line and not line.startswith("  "):
                log(f"{name}: {line}")
        if r.returncode != 0:
            raise RuntimeError(f"{name} falló: {(r.stderr or '').strip()[-300:]}")
    log(f"Listo: {os.path.abspath(os.path.join(work_dir, 'plan.html'))}")
    return True


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    from oroboros_export import find_file
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="ruta a SavedVariables/Oroboros.lua")
    ap.add_argument("--find", metavar="WOW_ROOT", help="buscar Oroboros.lua dentro de la carpeta de WoW")
    ap.add_argument("--work", default=DEFAULT_WORK, help="carpeta de trabajo (por defecto work/)")
    ap.add_argument("--resumen", help="dónde escribir Resumen.lua (por defecto, en la carpeta del addon)")
    ap.add_argument("--interval", type=float, default=30)
    ap.add_argument("--settle", type=float, default=10)
    ap.add_argument("--once", action="store_true", help="procesar una vez y salir")
    ap.add_argument("--azerothcore", default=os.path.join(HERE, "..", "work", "fuentes", "azerothcore"),
                    help="carpeta de AzerothCore para el farmeo (si no está descargado, se omite)")
    ap.add_argument("--log", help="escribir también lo que hace en este archivo (útil sin consola)")
    a = ap.parse_args()
    global LOG_FILE
    LOG_FILE = a.log
    a.work = os.path.normpath(a.work)
    path = a.path or (find_file(a.find) if a.find else None)
    if not path:
        ap.error("indica la ruta de Oroboros.lua o --find")
    import azerothcore
    ac_dir = a.azerothcore if a.azerothcore and azerothcore.available(a.azerothcore) else None
    run = lambda: pipeline(path, a.work, a.resumen, ac_dir=ac_dir)
    if a.once:
        try:
            run()
        except RuntimeError as e:
            _log(str(e))
            sys.exit(1)
        return
    _log(f"Vigilando {path} (cada {a.interval:g} s). Ctrl+C para parar.")
    try:
        watch(path, run, a.interval, a.settle)
    except KeyboardInterrupt:
        _log("Parado.")


if __name__ == "__main__":
    main()
