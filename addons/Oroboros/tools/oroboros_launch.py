#!/usr/bin/env python3
"""
Oroboros: lanzador. Abre Battle.net, espera a que arranque WoW Forever, se queda dormido mientras
juegas (Windows avisa cuando el proceso termina; no comprueba nada periódicamente) y, al cerrar el
juego, procesa una sola vez: exportar → archivo → plan → Resumen.lua. Luego termina.

Uso (normalmente desde el acceso directo «Jugar a Forever con Oroboros», con pythonw.exe):
  python oroboros_launch.py --find "F:/World of Warcraft/_forever_" --log work/lanzador.log
  python oroboros_launch.py --find "..." --battlenet no      # no abrir Battle.net (ya está abierto)
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BNET = r"C:\Program Files (x86)\Battle.net\Battle.net.exe"
LOG_FILE = None


def _log(*a):
    line = " ".join([time.strftime("[%d/%m %H:%M:%S]")] + [str(x) for x in a])
    print(line, flush=True)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + chr(10))


def run_session(find_game, wait_exit, run, start_launcher=None, wait_start=900, poll=5,
                clock=time.time, sleep=time.sleep, log=_log):
    """Espera a que el juego arranque (como mucho `wait_start` s, mirando cada `poll` s), después
    espera a que se cierre y llama a run() una vez. Devuelve True si procesó bien."""
    if start_launcher:
        start_launcher()
    t0 = clock()
    pid = find_game()
    while pid is None:
        if clock() - t0 >= wait_start:
            log("El juego no ha arrancado; no hay nada que procesar.")
            return False
        sleep(poll)
        pid = find_game()
    log(f"Juego en marcha (proceso {pid}). Esperando a que lo cierres…")
    wait_exit(pid)
    log("Juego cerrado. Procesando…")
    try:
        run()
        return True
    except Exception as e:                        # se registra y se termina
        log(f"Error al procesar: {e}")
        return False


# ----------------------------------------------------------------------
# Windows: localizar el proceso del juego y esperar a que termine (sin sondeo)
# ----------------------------------------------------------------------
def _process_path(pid):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        k32.CloseHandle(h)


def find_wow(exe_path):
    """PID del Wow.exe de esa carpeta (Forever), o None."""
    flags = 0x08000000 if os.name == "nt" else 0      # CREATE_NO_WINDOW: sin ventana con pythonw
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq Wow.exe"],
                             capture_output=True, text=True, creationflags=flags).stdout
    except OSError:
        return None
    want = os.path.normcase(os.path.abspath(exe_path))
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            pid = int(parts[1])
            path = _process_path(pid)
            if path and os.path.normcase(path) == want:
                return pid
    return None


def wait_pid(pid):
    """Bloquea hasta que el proceso termina (WaitForSingleObject: no consume CPU)."""
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x00100000, False, pid)    # SYNCHRONIZE
    if not h:
        return
    try:
        k32.WaitForSingleObject(h, 0xFFFFFFFF)     # INFINITE
    finally:
        k32.CloseHandle(h)


def main():
    global LOG_FILE
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--find", required=True, metavar="CARPETA", help="carpeta de WoW Forever (la que tiene Wow.exe)")
    ap.add_argument("--battlenet", default="auto", help="ruta de Battle.net.exe, o «no» para no abrirlo")
    ap.add_argument("--wait-start", type=float, default=15, help="minutos esperando a que arranque el juego")
    ap.add_argument("--work", default=None, help="carpeta de trabajo (por defecto work/)")
    ap.add_argument("--resumen", help="dónde escribir Resumen.lua (por defecto, en la carpeta del addon)")
    ap.add_argument("--log", help="escribir también lo que hace en este archivo")
    a = ap.parse_args()
    LOG_FILE = a.log
    if os.name != "nt":
        sys.exit("El lanzador solo funciona en Windows.")
    import oroboros_watch
    oroboros_watch.LOG_FILE = a.log
    from oroboros_export import find_file
    root = os.path.abspath(a.find)
    exe = next((p for p in (os.path.join(root, "Wow.exe"), os.path.join(root, "_forever_", "Wow.exe")) if os.path.exists(p)), None)
    if not exe:
        sys.exit(f"No encuentro Wow.exe en {root}")
    bnet = DEFAULT_BNET if a.battlenet == "auto" else (None if a.battlenet.lower() == "no" else a.battlenet)
    start = None
    if bnet and os.path.exists(bnet):
        start = lambda: (subprocess.Popen([bnet], close_fds=True), _log("Battle.net abierto: dale a Jugar."))
    work = a.work or oroboros_watch.DEFAULT_WORK

    def process():
        time.sleep(3)                               # por si el juego aún cierra archivos
        oroboros_watch.pipeline(find_file(root), work, a.resumen)

    run_session(lambda: find_wow(exe), wait_pid, process, start_launcher=start, wait_start=a.wait_start * 60)


if __name__ == "__main__":
    main()
