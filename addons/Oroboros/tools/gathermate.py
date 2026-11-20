"""
Oroboros: lee los nodos de recolección de GatherMate2_Data (carpeta Forever) y el nombre de cada tipo de nodo
(GatherMate2/Constants.lua). Solo lectura, desde la carpeta de addons del juego; no se copia nada al repositorio.

GatherMate2 dice dónde hay nodos, no qué sueltan: eso lo pone el botín de los nodos de AzerothCore (por nombre).
"""
import os
import re

KINDS = {"herb": "HerbalismData.lua", "mine": "MiningData.lua"}
MAP_RE = re.compile(r"^\s*\[(\d+)\]\s*=\s*\{")
NODE_RE = re.compile(r"^\s*\[\d+\]\s*=\s*(\d+)\s*,")
NAME_RE = re.compile(r'^\s*\["([^"]+)"\]\s*=\s*(?:(\d+)|\{\s*$)')
ID_RE = re.compile(r"^\s*id\s*=\s*(\d+)")


def find(path):
    """Busca la carpeta de addons con GatherMate2_Data/Forever subiendo desde `path`. None si no está."""
    d = os.path.abspath(path)
    while True:
        for cand in (d, os.path.join(d, "Interface", "AddOns")):
            if os.path.isdir(os.path.join(cand, "GatherMate2_Data", "Forever")):
                return os.path.normpath(cand)
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _names(path):
    """{id del tipo de nodo: nombre en inglés}. Las líneas comentadas (--) no cuentan."""
    out, pending = {}, None
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.lstrip().startswith("--"):
                continue
            m = NAME_RE.match(line)
            if m:
                pending = None
                if m.group(2):
                    out.setdefault(int(m.group(2)), m.group(1))
                else:
                    pending = m.group(1)
                continue
            m = ID_RE.match(line)
            if m and pending:
                out.setdefault(int(m.group(1)), pending)
                pending = None
    return out


def load(base):
    """{"herb": {uiMapID: {tipo: nodos}}, "mine": {...}, "names": {tipo: nombre}} desde la carpeta de addons."""
    out = {"names": _names(os.path.join(base, "GatherMate2", "Constants.lua"))}
    for kind, fname in KINDS.items():
        maps, cur = {}, None
        path = os.path.join(base, "GatherMate2_Data", "Forever", fname)
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    m = NODE_RE.match(line)
                    if m and cur is not None:
                        t = int(m.group(1))
                        cur[t] = cur.get(t, 0) + 1
                        continue
                    m = MAP_RE.match(line)
                    if m:
                        cur = maps.setdefault(int(m.group(1)), {})
        out[kind] = maps
    return out
