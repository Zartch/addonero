"""
Oroboros: lector de los datos de ProfessionDB (LibProfessionDB-1.0, licencia MIT) para WoW Forever.

Lee los archivos `Data/Forever/_core/*.lua` y `Data/Forever/esES/*.lua` del addon instalado, sin
cargarlo en el juego y sin copiar sus datos: cada archivo llama a `lib:LoadXxx(...)` con una tabla,
y aquí se analiza esa tabla con el LuaParser del exportador. Solo biblioteca estándar.

Por receta (id del hechizo de fabricación):
  prof, profession (nombre en el juego), name (español), required (nivel requerido o None),
  borrowed (el nivel es de Vanilla), diff [naranja, amarillo, verde, gris], reagents {item: cant},
  crafted (objeto), sources {t|v|q|c|d: número real de fuentes}, vendor [(nombre, cobre, moneda)],
  acquire (1 = se aprende con la profesión), hidden (nunca existió), scroll (pergamino que la enseña).
"""
import glob
import os
import re

# id de la línea de profesión → nombre en el cliente en español (Forever)
PROF_NAMES = {171: "Alquimia", 164: "Herrería", 165: "Peletería", 197: "Sastrería", 202: "Ingeniería",
              333: "Encantamiento", 185: "Cocina", 129: "Primeros auxilios", 356: "Pesca", 186: "Minería",
              182: "Botánica", 393: "Desuello"}

KINDS = ("t", "v", "q", "c", "d")
CALL = re.compile(r"lib:(Load\w+)\(")


def find(path):
    """Busca Interface/AddOns/ProfessionDB/Data/Forever subiendo desde `path` (p. ej. Oroboros.lua)."""
    d = os.path.dirname(os.path.abspath(path))
    while True:
        cand = os.path.join(d, "Interface", "AddOns", "ProfessionDB", "Data", "Forever")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _table_end(text, i):
    """Índice del cierre de la tabla que empieza en text[i] == '{', saltando cadenas."""
    depth, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("tabla sin cerrar")


def calls(text):
    """[(loader, [argumentos previos], tabla)] de cada lib:LoadXxx(...) del archivo."""
    from oroboros_export import LuaParser
    out = []
    for m in CALL.finditer(text):
        brace = text.find("{", m.end())
        if brace < 0:
            continue
        end = _table_end(text, brace)
        pre = [a.strip().strip('"') for a in text[m.end():brace].split(",") if a.strip()]
        out.append((m.group(1), pre, LuaParser(text[brace:end + 1]).value()))
    return out


def _d(x):
    if isinstance(x, list):
        return {i + 1: v for i, v in enumerate(x)}
    return x or {}


def load(base):
    """Carga ProfessionDB (carpeta Data/Forever). Devuelve {spell_id: dict}."""
    core, names, borrowed, sources, src_names, costs, acquire, hidden, scrolls = {}, {}, {}, {}, {}, {}, {}, set(), {}
    files = sorted(glob.glob(os.path.join(base, "_core", "*.lua"))) + sorted(glob.glob(os.path.join(base, "esES", "*.lua")))
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for loader, pre, t in calls(text):
            if loader == "LoadCore":
                prof = int(pre[0])
                for sid, e in _d(t).items():
                    core[int(sid)] = (prof, e)
            elif loader == "LoadNames":
                for sid, e in _d(t).items():
                    if isinstance(e, dict) and e.get("name"):
                        names[int(sid)] = e["name"]
            elif loader == "LoadBorrowed":
                for sid in (t if isinstance(t, list) else list(_d(t).values())):
                    borrowed.setdefault(int(sid), set()).add(pre[0] if pre else "")
            elif loader == "LoadSources":
                for sid, e in _d(t).items():
                    cur = sources.setdefault(int(sid), {})
                    for k in KINDS:
                        ids = e.get(k) if isinstance(e, dict) else None
                        if not ids:
                            continue
                        ids = ids if isinstance(ids, list) else list(_d(ids).values())
                        total = e.get(k + "n") or len(ids)
                        prev = cur.get(k)
                        cur[k] = (max(prev[0], total) if prev else total, (prev[1] if prev else []) + [i for i in ids if not prev or i not in prev[1]])
            elif loader == "LoadSourceNames":
                for nid, nm in _d(t).items():
                    src_names[int(nid)] = nm
            elif loader == "LoadVendorCosts":
                for sid, by in _d(t).items():
                    costs[int(sid)] = {int(n): (parts if isinstance(parts, list) else list(_d(parts).values()))
                                       for n, parts in _d(by).items()}
            elif loader == "LoadAcquireMethods":
                for sid, v in _d(t).items():
                    acquire[int(sid)] = int(v)
            elif loader == "LoadHiddenRecipes":
                hidden.update(int(sid) for sid in _d(t))
            elif loader == "LoadRecipeItems":
                for sid, item in _d(t).items():
                    scrolls[int(sid)] = item
    out = {}
    for sid, (prof, e) in core.items():
        diff = e.get("difficulty")
        diff = diff if isinstance(diff, list) else (list(_d(diff).values()) if diff else None)
        src = sources.get(sid, {})
        vendor = []
        for npc in (src.get("v", (0, []))[1]):
            parts = costs.get(sid, {}).get(int(npc), [])
            copper = next((p.get("g") for p in parts if isinstance(p, dict) and p.get("g")), None)
            cur = next(((p.get("c"), p.get("n")) for p in parts if isinstance(p, dict) and p.get("c")), None)
            vendor.append((src_names.get(int(npc), f"PNJ {npc}"), copper, cur))
        out[sid] = {
            "prof": prof, "profession": PROF_NAMES.get(prof, str(prof)), "name": names.get(sid),
            "required": e.get("requiredSkill"), "borrowed": "requiredSkill" in borrowed.get(sid, set()),
            "diff": diff, "reagents": {int(k): v for k, v in _d(e.get("reagents")).items()},
            "crafted": e.get("craftedItemId"), "sources": {k: v[0] for k, v in src.items()},
            "vendor": vendor, "acquire": acquire.get(sid, 0), "hidden": sid in hidden, "scroll": scrolls.get(sid),
        }
    return out


def reagent_uses(recipes):
    """{itemID: [(profesión, recetas)]}: qué profesiones usan cada objeto como componente y en cuántas recetas
    (sin las recetas ocultas, que nunca existieron), de más a menos recetas."""
    out = {}
    for r in recipes.values():
        if r.get("hidden"):
            continue
        for item in (r.get("reagents") or {}):
            d = out.setdefault(int(item), {})
            d[r["profession"]] = d.get(r["profession"], 0) + 1
    return {i: sorted(d.items(), key=lambda x: (-x[1], x[0])) for i, d in out.items()}


# ----------------------------------------------------------------------
# SQLite del plan
# ----------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS pdb_recipes (
    recipe_id INTEGER PRIMARY KEY, prof_id INTEGER, profession TEXT, name TEXT,
    required_skill INTEGER, req_borrowed INTEGER, d1 INTEGER, d2 INTEGER, d3 INTEGER, d4 INTEGER,
    crafted_item INTEGER, sources TEXT, vendor TEXT, acquire INTEGER, hidden INTEGER);
CREATE TABLE IF NOT EXISTS pdb_reagents (recipe_id INTEGER, item_id INTEGER, qty REAL, PRIMARY KEY (recipe_id, item_id));
"""


def write_tables(con, recipes):
    """Guarda las recetas de ProfessionDB en el SQLite del plan (sources y vendor en JSON)."""
    import json
    con.executescript(SCHEMA)
    for sid, r in recipes.items():
        d = (list(r.get("diff") or []) + [None] * 4)[:4]
        con.execute("INSERT OR REPLACE INTO pdb_recipes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, r["prof"], r["profession"], r["name"], r["required"], int(bool(r["borrowed"])), *d,
                     r["crafted"], json.dumps(r["sources"]), json.dumps(r["vendor"], ensure_ascii=False),
                     r["acquire"], int(bool(r["hidden"]))))
        for item, qty in (r.get("reagents") or {}).items():
            con.execute("INSERT OR REPLACE INTO pdb_reagents VALUES (?,?,?)", (sid, int(item), qty))
