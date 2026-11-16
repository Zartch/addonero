# Addonero

Proyecto para crear addons de **World of Warcraft** (de momento, para WoW Forever) con ayuda de Claude.

Cada addon vive en `addons/<Nombre>/`, con la carpeta que se copia al juego, sus herramientas, sus pruebas y su documentación.

## Addons

| Addon | Qué hace | Estado |
|---|---|---|
| [Oroboros](addons/Oroboros/README.md) | Subasta y oro: precios, recetas de todos tus personajes, rutas de compra → fabricación → venta con banquero, ideas de especulación y cartera. Comando `/oro`. | 0.5.0 · probado con simulación y datos sintéticos, pendiente de probar en el juego |

## Estructura de cada addon

```
addons/<Nombre>/
├── <Nombre>/          ← la carpeta que va a Interface/AddOns (TOC + Lua)
├── tools/             ← scripts fuera del juego (Python)
├── tests/             ← simulación de la API de WoW y pruebas
├── docs/              ← decisiones y arquitectura
├── examples/          ← salidas de ejemplo
├── README.md          ← uso y funciones
└── CLAUDE.md          ← contexto para seguir trabajando con Claude Code
```

## Instalar un addon para desarrollo

Enlaza la carpeta en lugar de copiarla, así cada cambio se ve en el juego con `/reload`:

- Windows (cmd como administrador):
  `mklink /D "<WoW>\<Forever>\Interface\AddOns\<Nombre>" "<repo>\addons\<Nombre>\<Nombre>"`
- macOS/Linux:
  `ln -s <repo>/addons/<Nombre>/<Nombre> "<WoW>/<Forever>/Interface/AddOns/<Nombre>"`
