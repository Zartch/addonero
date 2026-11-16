# Addonero — proyecto de addons para WoW

Monorepo de addons para **World of Warcraft Forever** (API moderna de Midnight, interfaz 16001 en Forever, Lua 5.1). El usuario (Zartch) habla español: código comentado, textos del juego y documentación en español.

## Estructura

- `addons/<Nombre>/` — un addon por carpeta. Antes de tocar uno, lee su `CLAUDE.md`, su `README.md` y su `docs/`.
- `addons/<Nombre>/<Nombre>/` — lo que va a `Interface/AddOns` (TOC + Lua).

Addons actuales:
- `addons/Oroboros/` — subasta y oro (comando `/oro`). Su `CLAUDE.md` tiene la siguiente tarea.

## Convenciones para todos los addons

- Nombre: comprobar en CurseForge que no existe otro addon con el mismo nombre ni el mismo comando (chocarían la carpeta, SavedVariables y el comando).
- Todo en una tabla privada `ns` (el `...` del archivo); solo son globales lo que el juego exige (SavedVariables, `SLASH_*`, funciones de atajos).
- Eventos y funciones del juego que puedan no existir en Forever: registrar con `pcall` o comprobar antes de llamar.
- Acciones protegidas (comprar, publicar, fabricar, lanzar hechizos…): siempre desde un clic o una tecla. Nada de automatizarlas: es botting y hay baneo.
- Los addons no tienen red ni escriben archivos: los datos salen por SavedVariables (`/reload` o salir) y entran pegando texto.
- Cada addon con pruebas fuera del juego (`tests/`, con `lupa` y una simulación de la API) y que pasen antes de cada commit.
- La carpeta real de WoW no está en el repo. Para probar, enlazar la carpeta del addon en `Interface/AddOns` (ver `README.md`).
- No subir SavedVariables reales: llevan nombres de personajes y oro.
