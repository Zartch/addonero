#!/usr/bin/env python3
"""
Oroboros: panel de escritorio (docs/planes/2026-11-23-api-blizzard.md, tarea 5).

Un solo programa que:
  1. descarga cada hora la subasta con la API de Blizzard (tools/oroboros_api.py) y, si hay foto nueva,
     regenera el plan y Resumen.lua (con --find, como el vigilante; si no, solo Resumen.lua);
  2. sirve en http://127.0.0.1:8737 (solo este PC) la página del plan con tres pestañas más:
     Inicio (ritmo de descarga, el juego y lo importante), Subasta (buscador, precio por casa, gráficas,
     franjas) y Ventas (lo más vendido y la calibración);
  3. abre una ventana propia con Edge en modo aplicación (o el navegador por defecto).
Una sola copia: abrirlo otra vez solo abre la ventana. Cerrar la ventana no para la descarga; se para
con el botón «Parar» del panel. Solo lee: nada actúa en el juego.

Uso:
  pythonw tools/oroboros_panel.py --find "F:/World of Warcraft/_forever_"
  python tools/oroboros_panel.py --sin-ventana          # solo descarga y servidor (para la tarea al iniciar sesión)
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import oroboros_api as API  # noqa: E402

DEFAULT_PORT = 8737
DEFAULT_WORK = os.path.join(HERE, "..", "work")
TEMPLATE = os.path.join(HERE, "planner_ui.html")
MUTEX = r"Local\OroborosPanel"
LOG_FILE = None


def _log(*a):
    line = " ".join([time.strftime("[%d/%m %H:%M:%S]")] + [str(x) for x in a])
    print(line, flush=True)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


# ----------------------------------------------------------------------
# Datos para la página (JSON). Todo lectura del archivo y del SQLite del plan.
# ----------------------------------------------------------------------
def _latest(con):
    return {h: t for h, t in con.execute("SELECT house, MAX(t) FROM api_snaps GROUP BY house")}


def estado(con, state):
    houses = []
    for h, name, fac, t, n, units, items in con.execute(
            """SELECT a.house, a.name, a.faction, s.t, s.auctions, s.units, s.items FROM api_houses a
               LEFT JOIN api_snaps s ON s.house = a.house AND s.t = (SELECT MAX(t) FROM api_snaps WHERE house = a.house)
               ORDER BY a.house"""):
        houses.append({"house": h, "name": name, "faction": fac, "t": t, "auctions": n, "units": units, "items": items})
    st = {k: v for k, v in (state or {}).items() if not callable(v)}
    return {"houses": houses, "state": st, "now": int(time.time())}


def _gaps(times, start, now):
    """Huecos sin foto (más de API.MAX_GAP entre dos fotos, o entre la última y ahora) dentro de [start, now].
    times: fotos ordenadas; puede llevar delante la última anterior a start. Sin ella, se cuenta desde start."""
    pts = list(times)
    if not pts or pts[0] > start:
        pts.insert(0, start)
    pts.append(now)
    return [[max(a, start), b] for a, b in zip(pts, pts[1:]) if b - a > API.MAX_GAP]


def inicio(con, state, work_dir, sv_path=None, now=None, top=5):
    """Pestaña Inicio: ritmo de descarga de la API (última foto, huecos de 24 h, próxima), el juego (último
    escaneo, último guardado, personajes) y lo importante (plan, lo más vendido en tu casa)."""
    now = int(now or time.time())
    start = now - 86400
    st = state or {}
    houses = []
    for h, name, fac in con.execute("SELECT house, name, faction FROM api_houses ORDER BY house").fetchall():
        prev = con.execute("SELECT MAX(t) FROM api_snaps WHERE house=? AND t < ?", (h, start)).fetchone()[0]
        ts = [r[0] for r in con.execute("SELECT t FROM api_snaps WHERE house=? AND t >= ? AND t <= ? ORDER BY t",
                                        (h, start, now))]
        last = con.execute("SELECT t, auctions FROM api_snaps WHERE house=? ORDER BY t DESC LIMIT 1", (h,)).fetchone()
        houses.append({"house": h, "name": name, "faction": fac, "t": last[0] if last else None,
                       "auctions": last[1] if last else None, "snaps24": len(ts),
                       "gaps": _gaps(([prev] if prev else []) + ts, start, now)})
    api = {k: st.get(k) for k in ("busy", "error", "credentials", "next_run", "last_run")}
    api["houses"] = houses

    game = {"scan_t": None, "scan_items": None, "sv_t": None, "chars": []}
    try:
        r = con.execute("SELECT t, n_items FROM scans ORDER BY t DESC LIMIT 1").fetchone()
        if r:
            game["scan_t"], game["scan_items"] = r
    except sqlite3.OperationalError:
        pass
    if sv_path and os.path.exists(sv_path):
        game["sv_t"] = int(os.path.getmtime(sv_path))
    plan_db = os.path.join(work_dir, "oroboros.sqlite")
    if os.path.exists(plan_db):
        p = sqlite3.connect(plan_db, timeout=30)
        try:
            banks = {c: t for c, t in p.execute("SELECT char, MAX(t) FROM slots WHERE location='bank' GROUP BY char")}
            for c, money, lvl, cls, t in p.execute(
                    "SELECT char, money, level, class, t FROM characters ORDER BY money DESC"):
                game["chars"].append({"name": c.split("-")[0], "money": money, "level": lvl, "class": cls,
                                      "t": t, "bank_t": banks.get(c)})
        except sqlite3.OperationalError:
            pass
        finally:
            p.close()

    plan = None
    pj = os.path.join(work_dir, "plan.json")
    if os.path.exists(pj):
        try:
            with open(pj, encoding="utf-8") as fh:
                pd = json.load(fh)
            s = pd.get("summary") or {}
            if s:
                plan = {"generated": pd.get("generated"),
                        **{k: s.get(k) for k in ("profit", "investment", "gold", "stock_sale", "roi")}}
        except (OSError, ValueError):
            pass

    # lo más vendido (estimado) en las últimas 24 h de tu casa: la primera (la de tu facción, 111)
    topd = {"house": houses[0]["house"] if houses else None, "items": [], "calibrated": False}
    if houses:
        h = houses[0]["house"]
        rates, _ = API.move_rates(con, h, now=now, days=1)
        last = houses[0]["t"]
        prices = {i: m for i, m in con.execute("SELECT item_id, min FROM api_item_hour WHERE house=? AND t=?", (h, last))}
        rows = [{"id": i, "sold": r["sold"], "min": prices.get(i), "value": r["sold"] * prices[i] if prices.get(i) else 0}
                for i, r in rates.items() if r["sold"] > 0]
        rows.sort(key=lambda x: -x["value"])
        rows = rows[:top]
        if rows:
            names = {i: (n, q) for i, n, q in con.execute(
                f"SELECT item_id, name, quality FROM items WHERE item_id IN ({','.join('?' * len(rows))})",
                [x["id"] for x in rows])}
            for x in rows:
                n, q = names.get(x["id"], (None, None))
                x["name"], x["quality"] = n or f"objeto {x['id']}", q
        topd["items"] = rows
        topd["calibrated"] = API.is_calibrated(con, h)
        topd["calibration"] = _calib_saved(con, h)
    return {"now": now, "api": api, "game": game, "plan": plan, "top": topd}


def buscar(con, q, limit=40):
    q = (q or "").strip()
    latest = _latest(con)
    if q.isdigit():
        ids = [int(q)]
    elif len(q) >= 2:
        ids = [r[0] for r in con.execute(
            "SELECT item_id FROM items WHERE name LIKE ? ORDER BY length(name), name LIMIT ?", (f"%{q}%", limit))]
    else:
        ids = []
    names = {r[0]: (r[1], r[2]) for r in con.execute(
        f"SELECT item_id, name, quality FROM items WHERE item_id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
    out = []
    for i in ids:
        prices = {}
        for h, t in latest.items():
            r = con.execute("SELECT min FROM api_item_hour WHERE house=? AND t=? AND item_id=?", (h, t, i)).fetchone()
            if r and r[0] is not None:
                prices[str(h)] = r[0]
        name, qual = names.get(i, (None, None))
        out.append({"id": i, "name": name or f"objeto {i}", "quality": qual, "prices": prices})
    return out


def objeto(con, plan_db, item, days=14):
    item = int(item)
    since = int(time.time()) - days * 86400
    r = con.execute("SELECT name, quality, vendor_sell FROM items WHERE item_id=?", (item,)).fetchone()
    out = {"id": item, "name": (r[0] if r and r[0] else f"objeto {item}"), "quality": r[1] if r else None,
           "vendor_sell": r[2] if r else None, "houses": {}, "inventory": [], "ledger": []}
    for h, name, fac, mid in con.execute("SELECT house, name, faction, market_id FROM api_houses ORDER BY house").fetchall():
        hourly = [list(x) for x in con.execute(
            """SELECT t, min, mv, qty, COALESCE(sold, 0) + COALESCE(partial, 0), expired, cancelled, new
               FROM api_item_hour WHERE house=? AND item_id=? AND t >= ? ORDER BY t""", (h, item, since))]
        daily = [list(x) for x in con.execute(
            "SELECT day, min_low, mv, qty_max, src FROM daily WHERE market_id=? AND item_id=? ORDER BY day", (mid, item))]
        rates, cov = API.move_rates(con, h, items=[item])
        bands = API.band_stats(con, h, [item]).get(item)
        out["houses"][str(h)] = {"name": name, "faction": fac, "hourly": hourly, "daily": daily,
                                 "rates": rates.get(item), "days": cov, "bands": bands or []}
    if plan_db and os.path.exists(plan_db):
        p = sqlite3.connect(plan_db)
        try:
            out["inventory"] = [list(x) for x in p.execute(
                "SELECT char, location, count FROM inventory WHERE item_id=? ORDER BY count DESC", (item,))]
            out["ledger"] = [list(x) for x in p.execute(
                "SELECT t, char, op, qty, unit, total FROM ledger WHERE item_id=? ORDER BY t DESC LIMIT 50", (item,))]
        except sqlite3.OperationalError:
            pass
        finally:
            p.close()
    return out


def ventas(con, days=7, top=60):
    latest = _latest(con)
    names = {}
    res = []
    for h, name, fac in con.execute("SELECT house, name, faction FROM api_houses ORDER BY house").fetchall():
        rates, cov = API.move_rates(con, h, days=days)
        prices = {r[0]: r[1] for r in con.execute(
            "SELECT item_id, min FROM api_item_hour WHERE house=? AND t=?", (h, latest.get(h)))} if h in latest else {}
        rows = []
        for i, r in rates.items():
            p = prices.get(i)
            rows.append({"id": i, **r, "min": p, "value": r["sold"] * p if p else None})
        rows.sort(key=lambda x: -(x["value"] or 0))
        rows = rows[:top]
        for x in rows:
            names.setdefault(x["id"], None)
        res.append({"house": h, "name": name, "faction": fac, "days": cov, "top": rows,
                    "calibration": _calib_saved(con, h)})
    ids = list(names)
    if ids:
        for i, n in con.execute(f"SELECT item_id, name FROM items WHERE item_id IN ({','.join('?' * len(ids))})", ids):
            names[i] = n
    for hh in res:
        for x in hh["top"]:
            x["name"] = names.get(x["id"]) or f"objeto {x['id']}"
    return {"houses": res}


def _calib_saved(con, h):
    r = con.execute("SELECT value FROM meta WHERE key=?", (f"api_calibration_{h}",)).fetchone()
    try:
        return json.loads(r[0]) if r else None
    except ValueError:
        return None


def calibrar(archive, plan_db):
    con = sqlite3.connect(archive)
    houses = [r[0] for r in con.execute("SELECT house FROM api_houses ORDER BY house")]
    con.close()
    if not plan_db or not os.path.exists(plan_db):
        return [{"house": h, "error": "falta work/oroboros.sqlite (exporta tus datos del juego)",
                 "coverage": None, "outside": 0} for h in houses]
    return [API.calibrate(archive, plan_db, h) for h in houses]


def page_html(work_dir):
    """La página del plan con el plan incrustado (work/plan.json) y el modo panel activado."""
    with open(TEMPLATE, encoding="utf-8") as fh:
        tpl = fh.read()
    pj = os.path.join(work_dir, "plan.json")
    blob = "null"
    if os.path.exists(pj):
        with open(pj, encoding="utf-8") as fh:
            blob = json.dumps(json.load(fh), ensure_ascii=False).replace("</", "<\\/")
    return tpl.replace("/*__PLAN__*/null", blob).replace("/*__PANEL__*/false", "true")


# ----------------------------------------------------------------------
# Servidor
# ----------------------------------------------------------------------
def make_server(work_dir, port=DEFAULT_PORT, state=None, wake=None, archive=None, sv_path=None):
    """Servidor HTTP solo en 127.0.0.1. state: dict que comparte el hilo de descarga; wake(): descargar ya."""
    archive = archive or os.path.join(work_dir, "archivo.sqlite")
    plan_db = os.path.join(work_dir, "oroboros.sqlite")
    state = state if state is not None else {}
    API.open_api(archive).close()          # el esquema, una vez al arrancar

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):          # sin ruido en la consola
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else (
                json.dumps(body, ensure_ascii=False, default=str) if ctype.startswith("application/json") else body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self, post=False):
            """Solo peticiones a 127.0.0.1/localhost con nuestro puerto (contra DNS rebinding) y, en los POST,
            desde nuestra propia página (contra webs que intenten parar el panel)."""
            port = self.server.server_address[1]
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if (self.headers.get("Host") or "") not in hosts:
                return False
            origin = self.headers.get("Origin")
            return not (post and origin and origin not in {f"http://{h}" for h in hosts})

        def _con(self):
            # solo lectura: no toca el esquema (eso pide escribir y chocaría con la descarga)
            return sqlite3.connect(archive, timeout=30)

        def do_GET(self):
            if not self._allowed():
                return self._send(403, {"error": "solo desde este PC"})
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            try:
                if u.path in ("/", "/index.html"):
                    return self._send(200, page_html(work_dir), "text/html; charset=utf-8")
                if u.path == "/api/calibrar":
                    return self._send(200, calibrar(archive, plan_db))
                con = self._con()
                try:
                    if u.path == "/api/estado":
                        return self._send(200, estado(con, state))
                    if u.path == "/api/inicio":
                        return self._send(200, inicio(con, state, work_dir, sv_path=sv_path))
                    if u.path == "/api/buscar":
                        return self._send(200, buscar(con, (qs.get("q") or [""])[0]))
                    m = re.fullmatch(r"/api/objeto/(\d+)", u.path)
                    if m:
                        return self._send(200, objeto(con, plan_db, int(m.group(1))))
                    if u.path == "/api/ventas":
                        return self._send(200, ventas(con, int((qs.get("dias") or ["7"])[0])))
                finally:
                    con.close()
                self._send(404, {"error": "no existe"})
            except Exception as e:      # el panel no se cae por una consulta
                self._send(500, {"error": type(e).__name__, "detail": str(e)[:200]})

        def do_POST(self):
            if not self._allowed(post=True):
                return self._send(403, {"error": "solo desde la página del panel"})
            if self.path == "/api/descargar":
                if wake:
                    wake()
                return self._send(200, {"ok": True})
            if self.path == "/api/parar":
                self._send(200, {"ok": True})
                state["stopping"] = True
                if callable(state.get("on_stop")):
                    state["on_stop"]()
                threading.Thread(target=srv.shutdown, daemon=True).start()
                return
            self._send(404, {"error": "no existe"})

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    return srv


# ----------------------------------------------------------------------
# Descarga cada hora, en un hilo
# ----------------------------------------------------------------------
class Worker(threading.Thread):
    def __init__(self, work_dir, client, houses, realm, sv_path=None, resumen=None, log=_log):
        super().__init__(daemon=True)
        self.work_dir, self.client, self.houses, self.realm = work_dir, client, houses, realm
        self.sv_path, self.resumen, self.log = sv_path, resumen, log
        self.archive = os.path.join(work_dir, "archivo.sqlite")
        self.plan_db = os.path.join(work_dir, "oroboros.sqlite")
        self.wake_ev, self.stop_ev = threading.Event(), threading.Event()
        self.state = {"busy": False, "last_run": None, "next_run": None, "results": [], "error": None,
                      "credentials": client is not None}

    def wake(self):
        self.wake_ev.set()

    def stop(self):
        self.stop_ev.set()
        self.wake_ev.set()

    def step(self):
        """Una vuelta: descarga, mantenimiento y, si hay foto nueva, plan y Resumen.lua."""
        self.state["busy"] = True
        try:
            res = API.run_once(self.archive, self.client, self.houses, self.realm, log=self.log)
            API.maintenance(self.archive, self.client, log=self.log, plan_db=self.plan_db)
            if any(r["status"] == "nueva" for r in res):
                self.regenerate()
            self.state.update(results=res, last_run=int(time.time()), error=None)
            return res
        except Exception as e:
            self.state["error"] = f"{type(e).__name__}: {e}"[:300]
            self.log("error en la descarga:", self.state["error"])
            return []
        finally:
            self.state["busy"] = False

    def regenerate(self):
        if self.sv_path and os.path.exists(self.sv_path):
            import oroboros_watch
            try:
                oroboros_watch.pipeline(self.sv_path, self.work_dir, self.resumen, log=self.log)
                return
            except RuntimeError as e:
                self.log(str(e))
        import oroboros_summary
        r = oroboros_summary.write_resumen(self.archive, self.resumen or oroboros_summary.DEFAULT_OUT)
        self.log(f"Resumen.lua: {r['items']} objetos")

    def run(self):
        if self.client is None:
            self.state["error"] = "Faltan las credenciales (BNET_CLIENT_ID / BNET_CLIENT_SECRET o work/bnet.env)"
            return
        while not self.stop_ev.is_set():
            res = self.step()
            wait = API.wait_after(res, time.time()) if res else 300
            self.state["next_run"] = int(time.time() + wait)
            self.wake_ev.wait(wait)
            self.wake_ev.clear()


# ----------------------------------------------------------------------
# Ventana
# ----------------------------------------------------------------------
def find_edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.exists(p):
                return p
    return shutil.which("msedge")


def open_window(url):
    edge = find_edge()
    if edge:
        subprocess.Popen([edge, f"--app={url}", "--window-size=1320,880"], close_fds=True)
    else:
        webbrowser.open(url)


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default=DEFAULT_WORK)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--casas", default=",".join(map(str, API.DEFAULT_HOUSES)))
    ap.add_argument("--reino", default=API.DEFAULT_REALM)
    ap.add_argument("--find", metavar="WOW_ROOT", help="carpeta de WoW: con ella, cada foto nueva regenera también el plan")
    ap.add_argument("--sin-ventana", action="store_true", help="no abrir la ventana (para arrancarlo al iniciar sesión)")
    ap.add_argument("--log", help="escribir lo que hace en este archivo (útil con pythonw, sin consola)")
    a = ap.parse_args()
    global LOG_FILE
    LOG_FILE = a.log
    work = os.path.normpath(a.work)
    url = f"http://127.0.0.1:{a.port}/"
    if os.name == "nt":
        from oroboros_launch import single_instance
        if not single_instance(MUTEX):
            if not a.sin_ventana:
                open_window(url)
            return
    sv = None
    if a.find:
        from oroboros_export import find_file
        sv = find_file(a.find)
    creds = API.load_creds(work)
    client = API.Client(creds, cache_dir=os.path.join(work, "api")) if creds else None
    worker = Worker(work, client, [int(x) for x in a.casas.split(",") if x.strip()], a.reino, sv_path=sv)
    worker.state["on_stop"] = worker.stop
    srv = make_server(work, a.port, worker.state, worker.wake, sv_path=sv)
    worker.start()
    _log(f"Panel en {url} (solo este PC). Descarga cada hora: {'sí' if client else 'no, faltan credenciales'}.")
    if not a.sin_ventana:
        open_window(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()
        _log("Panel parado.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _log(traceback.format_exc())
        raise
