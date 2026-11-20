#!/usr/bin/env python3
"""
Oroboros: convierte el SavedVariables del addon (Oroboros.lua) en SQLite y/o JSON
para que el planificador (paso 2) trabaje con los datos.

Uso:
  python oroboros_export.py "C:/.../SavedVariables/Oroboros.lua" --sqlite oroboros.sqlite --json oroboros.json
  python oroboros_export.py --find "C:/Program Files (x86)/World of Warcraft" --sqlite oroboros.sqlite
  python oroboros_export.py --find "F:/World of Warcraft/_forever_" --auctionator --sqlite oroboros.sqlite
      (--auctionator sin ruta busca Auctionator.lua junto a Oroboros.lua)

Sin dependencias externas (solo biblioteca estándar).
"""
import argparse
import glob
import json
import os
import re
import sqlite3
import sys


# ----------------------------------------------------------------------
# Parser mínimo de tablas Lua tal como las escribe WoW
# ----------------------------------------------------------------------
class LuaParser:
    TOKEN = re.compile(r"""
        (?P<ws>\s+|--[^\n]*)
      | (?P<str>"(?:\\[\s\S]|[^"\\])*")
      | (?P<num>-?(?:0x[0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?))
      | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
      | (?P<sym>[{}\[\]=,;])
    """, re.VERBOSE)

    ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "'": "'", "\n": "\n"}

    def __init__(self, text, binary=False):
        # binary=True: las cadenas se devuelven byte a byte (latin-1), sin decodificar UTF-8
        self.binary = binary
        self.tokens = []
        pos = 0
        while pos < len(text):
            m = self.TOKEN.match(text, pos)
            if not m:
                raise ValueError(f"carácter inesperado en {pos}: {text[pos:pos+30]!r}")
            pos = m.end()
            kind = m.lastgroup
            if kind != "ws":
                self.tokens.append((kind, m.group(kind)))
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def take(self, value=None):
        tok = self.peek()
        if value is not None and tok[1] != value:
            raise ValueError(f"se esperaba {value!r} y llegó {tok[1]!r}")
        self.i += 1
        return tok

    def unescape(self, s):
        out, k = [], 0
        while k < len(s):
            c = s[k]
            if c == "\\" and k + 1 < len(s):
                n = s[k + 1]
                if n.isdigit():
                    m = re.match(r"\d{1,3}", s[k + 1:])
                    out.append(chr(int(m.group())))
                    k += 1 + len(m.group())
                    continue
                out.append(self.ESCAPES.get(n, n))
                k += 2
            else:
                out.append(c)
                k += 1
        raw = "".join(out)
        if self.binary:
            return raw
        # WoW escribe UTF-8; los escapes numéricos dan bytes sueltos
        try:
            return raw.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return raw

    def value(self):
        kind, tok = self.take()
        if kind == "str":
            return self.unescape(tok[1:-1])
        if kind == "num":
            return int(tok, 16) if tok.lower().startswith(("0x", "-0x")) else (
                float(tok) if any(c in tok for c in ".eE") else int(tok))
        if kind == "name":
            return {"true": True, "false": False, "nil": None}.get(tok, tok)
        if tok == "{":
            return self.table()
        raise ValueError(f"valor inesperado {tok!r}")

    def table(self):
        result, n = {}, 0
        while self.peek()[1] != "}":
            kind, tok = self.peek()
            if tok == "[":
                self.take("[")
                key = self.value()
                self.take("]")
                self.take("=")
                result[key] = self.value()
            elif kind == "name" and self.tokens[self.i + 1][1] == "=":
                self.take()
                self.take("=")
                result[tok] = self.value()
            else:
                n += 1
                result[n] = self.value()
            if self.peek()[1] in (",", ";"):
                self.take()
        self.take("}")
        if result and all(isinstance(k, int) for k in result) and \
                sorted(result) == list(range(1, len(result) + 1)):
            return [result[k] for k in range(1, len(result) + 1)]
        return result

    def assignments(self):
        out = {}
        while self.peek()[0] is not None:
            _, name = self.take()
            self.take("=")
            out[name] = self.value()
        return out


def load_savedvariables(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return LuaParser(fh.read()).assignments()


# ----------------------------------------------------------------------
# SQLite
# ----------------------------------------------------------------------
SCHEMA = """
CREATE TABLE items      (item_id INTEGER PRIMARY KEY, name TEXT, quality INTEGER, vendor_sell INTEGER,
                         stack INTEGER, is_commodity INTEGER, vendor_buy REAL, ilvl INTEGER);
CREATE TABLE config     (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE ledger     (t INTEGER, char TEXT, op TEXT, item_id INTEGER, qty REAL, unit REAL, total REAL, src TEXT);
CREATE TABLE positions  (item_id INTEGER PRIMARY KEY, qty REAL, entry REAL, target REAL, stop REAL, due TEXT,
                         t INTEGER, char TEXT);
CREATE TABLE prices     (market TEXT, item_id INTEGER, min REAL, mv REAL, qty INTEGER, auctions INTEGER,
                         t INTEGER, d110 INTEGER, d125 INTEGER, d150 INTEGER, d200 INTEGER,
                         src TEXT DEFAULT 'oro',               -- oro = Oroboros | atr = Auctionator
                         PRIMARY KEY (market, item_id));
CREATE TABLE history    (market TEXT, item_id INTEGER, day TEXT, min REAL, mv REAL, qty INTEGER,
                         src TEXT DEFAULT 'oro', t INTEGER, PRIMARY KEY (market, item_id, day));
CREATE TABLE characters (char TEXT PRIMARY KEY, market TEXT, money INTEGER, level INTEGER, class TEXT, t INTEGER);
CREATE TABLE inventory  (char TEXT, location TEXT, item_id INTEGER, count INTEGER,
                         PRIMARY KEY (char, location, item_id));   -- location: bags | bank | warband
CREATE TABLE slots      (char TEXT, location TEXT, total INTEGER, free INTEGER, t INTEGER,
                         PRIMARY KEY (char, location));
CREATE TABLE professions(char TEXT, profession TEXT, skill INTEGER, max INTEGER, t INTEGER,
                         PRIMARY KEY (char, profession));
CREATE TABLE recipes    (char TEXT, profession TEXT, recipe_id INTEGER, name TEXT, learned INTEGER,
                         output_item INTEGER, qmin REAL, qmax REAL, difficulty INTEGER, skill_ups INTEGER,
                         enchant INTEGER, source TEXT, cd_until INTEGER, PRIMARY KEY (char, recipe_id));
CREATE TABLE reagents   (recipe_id INTEGER, item_id INTEGER, qty REAL, alternatives TEXT,
                         PRIMARY KEY (recipe_id, item_id));
CREATE VIEW recipe_cost AS
  SELECT r.recipe_id, r.item_id, r.qty,
         COALESCE(i.vendor_buy, p.min) AS unit_cost,
         CASE WHEN i.vendor_buy IS NOT NULL THEN 'vendor' ELSE 'ah' END AS source
  FROM reagents r
  LEFT JOIN items i ON i.item_id = r.item_id
  LEFT JOIN prices p ON p.item_id = r.item_id;
"""


def as_dict(x):
    """Lua vacía/array → dict indexable por clave."""
    if isinstance(x, list):
        return {i + 1: v for i, v in enumerate(x)}
    return x or {}


def write_sqlite(db, path):
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    vendor = as_dict(db.get("vendor"))
    items = as_dict(db.get("items"))
    for item_id in set(items) | set(vendor):
        it = items.get(item_id) or {}
        con.execute("INSERT INTO items VALUES (?,?,?,?,?,?,?,?)", (
            int(item_id), it.get("n"), it.get("q"), it.get("s"), it.get("st"),
            None if it.get("c") is None else int(bool(it.get("c"))), vendor.get(item_id), it.get("il")))

    for market, m in as_dict(db.get("markets")).items():
        for item_id, p in as_dict(m.get("prices")).items():
            d = p.get("d") or [None] * 4
            d = d if isinstance(d, list) else [d.get(k) for k in (1, 2, 3, 4)]
            con.execute("INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?,?,?,'oro')",
                        (market, int(item_id), p.get("min"), p.get("mv"), p.get("qty"), p.get("n"), p.get("t"),
                         *d[:4]))
        for item_id, days in as_dict(m.get("history")).items():
            for day, h in as_dict(days).items():
                con.execute("INSERT INTO history VALUES (?,?,?,?,?,?,'oro',?)",
                            (market, int(item_id), day, h.get("min"), h.get("mv"), h.get("qty"), h.get("t")))

    seen_reagents = set()
    for char, c in as_dict(db.get("chars")).items():
        con.execute("INSERT INTO characters VALUES (?,?,?,?,?,?)",
                    (char, c.get("market"), c.get("money"), c.get("level"), c.get("class"), c.get("t")))
        for loc, key, slots_key, t in (("bags", "bags", "bagSlots", c.get("t")),
                                       ("bank", "bank", "bankSlots", c.get("bankT"))):
            for item_id, n in as_dict(c.get(key)).items():
                con.execute("INSERT INTO inventory VALUES (?,?,?,?)", (char, loc, int(item_id), n))
            sl = c.get(slots_key)
            if isinstance(sl, dict):
                con.execute("INSERT INTO slots VALUES (?,?,?,?,?)", (char, loc, sl.get("total"), sl.get("free"), t))
        for prof, p in as_dict(c.get("professions")).items():
            con.execute("INSERT INTO professions VALUES (?,?,?,?,?)",
                        (char, prof, p.get("skill"), p.get("max"), p.get("t")))
            for rid, r in as_dict(p.get("recipes")).items():
                rid = int(rid)
                con.execute("INSERT INTO recipes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    char, prof, rid, r.get("n"), r.get("l"), r.get("out"), r.get("qmin"), r.get("qmax"),
                    r.get("diff"), r.get("ups"), 1 if r.get("ench") else 0, r.get("src"), r.get("cdUntil")))
                if rid in seen_reagents:
                    continue
                seen_reagents.add(rid)
                for reg in r.get("r") or []:
                    reg = reg if isinstance(reg, list) else [reg.get(1), reg.get(2), reg.get(3)]
                    alts = reg[2] if len(reg) > 2 else None
                    con.execute("INSERT OR REPLACE INTO reagents VALUES (?,?,?,?)",
                                (rid, int(reg[0]), reg[1], json.dumps(alts) if alts else None))
    for k, v in as_dict(db.get("config")).items():
        con.execute("INSERT INTO config VALUES (?,?)", (str(k), str(v)))
    led = db.get("ledger") or []
    for e in (led if isinstance(led, list) else led.values()):
        con.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?)", (e.get("t"), e.get("char"), e.get("op"),
                    e.get("item"), e.get("qty"), e.get("unit"), e.get("total"), e.get("src")))
    for item_id, p in as_dict(db.get("positions")).items():
        con.execute("INSERT INTO positions VALUES (?,?,?,?,?,?,?,?)", (int(item_id), p.get("qty"), p.get("entry"),
                    p.get("target"), p.get("stop"), p.get("due"), p.get("t"), p.get("char")))
    wb = db.get("warband")
    if isinstance(wb, dict):
        for item_id, n in as_dict(wb.get("items")).items():
            con.execute("INSERT INTO inventory VALUES (?,?,?,?)", ("Banda", "warband", int(item_id), n))
        sl = wb.get("slots") or {}
        con.execute("INSERT INTO slots VALUES (?,?,?,?,?)", ("Banda", "warband", sl.get("total"), sl.get("free"), wb.get("t")))
    con.commit()
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("items", "prices", "history", "characters", "inventory", "slots", "recipes", "reagents")}
    con.close()
    return counts


def find_file(root):
    hits = glob.glob(os.path.join(root, "**", "SavedVariables", "Oroboros.lua"), recursive=True)
    if not hits:
        sys.exit(f"No encuentro SavedVariables/Oroboros.lua dentro de {root}")
    hits.sort(key=os.path.getmtime, reverse=True)
    if len(hits) > 1:
        print("Varios ficheros encontrados, uso el más reciente:")
        for h in hits:
            print("  ", h)
    return hits[0]


def add_auctionator(sqlite_path, atr_path, oroboros_path):
    import auctionator_source
    if atr_path == "auto":
        atr_path = os.path.join(os.path.dirname(os.path.abspath(oroboros_path)), "Auctionator.lua")
        if not os.path.exists(atr_path):
            print(f"Auctionator: no encuentro {atr_path}; sigo solo con los datos de Oroboros.")
            return
    atr = auctionator_source.load(atr_path)
    con = sqlite3.connect(sqlite_path)
    # mismo criterio que el planificador: el mercado de la mayoría de personajes
    markets = [r[0] for r in con.execute("SELECT market FROM characters WHERE market IS NOT NULL")]
    market = max(set(markets), key=markets.count) if markets else auctionator_source.pick_market(atr["markets"])
    n_price, n_hist = auctionator_source.merge(con, atr, market)
    con.close()
    total = sum(len(v) for v in atr["markets"].values())
    print(f"Auctionator → mercado {market}: {total} objetos leídos, {n_price} precios y {n_hist} días de histórico añadidos.")


def _main_market(db):
    """Mercado de la mayoría de personajes (el mismo criterio que el planificador)."""
    markets = [c.get("market") for c in as_dict(db.get("chars")).values() if isinstance(c, dict) and c.get("market")]
    return max(set(markets), key=markets.count) if markets else None


def update_archive(archive_path, db, atr_arg, oroboros_path):
    """Escaneos → histórico diario (+ Auctionator) → resumen de lo viejo, en el archivo permanente."""
    import time
    import oroboros_archive as A
    res = A.append_scans(archive_path, db)
    con = A.open_archive(archive_path)
    A.update_daily(con, db)
    n_farm = A.append_farm(con, db, _main_market(db))
    n_atr = 0
    if atr_arg:
        import auctionator_source
        atr_path = atr_arg
        if atr_arg == "auto":
            atr_path = os.path.join(os.path.dirname(os.path.abspath(oroboros_path)), "Auctionator.lua")
        if os.path.exists(atr_path):
            atr = auctionator_source.load(atr_path)
            market = _main_market(db) or auctionator_source.pick_market(atr["markets"])
            n_atr = auctionator_source.to_daily(con, atr, market)
        else:
            print(f"Auctionator: no encuentro {atr_path}; sigo sin sus datos.")
    rolled = A.rollup(con, int(time.time()))
    n_daily = con.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
    n_scans = con.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    con.close()
    print(f"Archivo → {archive_path}: {res['scans']} escaneos nuevos ({res['added']} filas), "
          f"{res['already']} filas ya estaban; {n_scans} escaneos en bruto, histórico diario: {n_daily} filas"
          f"{f' ({n_atr} nuevas de Auctionator)' if n_atr else ''}; resumidos y borrados: {rolled}"
          f"{f'; farmeo medido: {n_farm[0]} criaturas, {n_farm[1]} subzonas de recolección' if n_farm[0] or n_farm[1] else ''}.")
    if res["gap"]:
        print("Aviso: se han perdido escaneos entre el último archivado y los guardados en el juego "
              "(más de 12 sin exportar).")


def add_professiondb(sqlite_path, pdb_arg, oroboros_path):
    """Recetas de ProfessionDB (nivel, origen…) en el SQLite del plan. Sin ProfessionDB, sigue sin ella."""
    import professiondb
    base = professiondb.find(oroboros_path) if pdb_arg == "auto" else pdb_arg
    if not base or not os.path.isdir(base):
        if pdb_arg != "auto":
            print(f"ProfessionDB: no encuentro {pdb_arg}; sigo sin ella.")
        return
    recipes = professiondb.load(base)
    con = sqlite3.connect(sqlite_path)
    professiondb.write_tables(con, recipes)
    con.commit()
    con.close()
    print(f"ProfessionDB → {len(recipes)} recetas (nivel requerido, dónde se aprende).")


def utf8_output():
    """La consola de Windows usa cp1252: sin esto, «→» rompe la salida."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main():
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="ruta a SavedVariables/Oroboros.lua")
    ap.add_argument("--find", metavar="WOW_ROOT", help="buscar Oroboros.lua dentro de la carpeta de WoW")
    ap.add_argument("--sqlite", help="fichero SQLite de salida")
    ap.add_argument("--json", help="fichero JSON de salida")
    ap.add_argument("--auctionator", nargs="?", const="auto", metavar="RUTA",
                    help="añadir los precios de Auctionator (sin ruta: Auctionator.lua junto a Oroboros.lua)")
    ap.add_argument("--archive", metavar="RUTA",
                    help="añadir los escaneos guardados en el juego a un SQLite permanente (p. ej. work/archivo.sqlite)")
    ap.add_argument("--professiondb", metavar="RUTA", default="auto",
                    help="carpeta Data/Forever de ProfessionDB (por defecto la busca junto a la instalación; «no» para no usarla)")
    ap.add_argument("--resumen", metavar="RUTA",
                    help="con --archive: dónde escribir Resumen.lua para el panel del juego "
                         "(por defecto Oroboros/Resumen.lua; «no» para no escribirlo)")
    args = ap.parse_args()

    path = args.path or (find_file(args.find) if args.find else None)
    if not path:
        ap.error("indica la ruta del fichero o --find")
    data = load_savedvariables(path)
    db = data.get("OroborosDB")
    if not isinstance(db, dict):
        sys.exit("El fichero no contiene OroborosDB (¿has hecho /reload después de escanear?)")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(db, fh, ensure_ascii=False, indent=1, default=str)
        print(f"JSON → {args.json}")
    if args.archive:
        update_archive(args.archive, db, args.auctionator, path)
        if (args.resumen or "").lower() != "no":
            import oroboros_summary
            out = args.resumen or oroboros_summary.DEFAULT_OUT
            r = oroboros_summary.write_resumen(args.archive, out)
            print(f"Resumen → {os.path.abspath(out)}: {r['items']} objetos, {r['bytes'] / 1024:.0f} KB "
                  "(el juego lo carga al entrar o con /reload).")
    if args.sqlite:
        counts = write_sqlite(db, args.sqlite)
        print(f"SQLite → {args.sqlite}  " + ", ".join(f"{k}: {v}" for k, v in counts.items()))
        if args.archive:
            import oroboros_archive as A
            con = A.open_archive(args.archive)
            r = A.plan_from_archive(con, args.sqlite)
            con.close()
            print(f"Plan desde el archivo: {r['history']} días de histórico, {r['prices_added']} precios completados.")
        elif args.auctionator:
            add_auctionator(args.sqlite, args.auctionator, path)
        if (args.professiondb or "").lower() != "no":
            add_professiondb(args.sqlite, args.professiondb, path)
    if not args.json and not args.sqlite and not args.archive:
        print(json.dumps({k: (len(v) if hasattr(v, "__len__") else v) for k, v in db.items()}, indent=1))


if __name__ == "__main__":
    main()
