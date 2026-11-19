# Rediseño de las ventanas: plan de implementación

> **Para quien lo ejecute:** tarea a tarea (superpowers:executing-plans).

**Objetivo:** ventanas del juego legibles y cuidadas, con gráficas con escala, leyenda y detalle al pasar el ratón, y el precio en vivo correcto.

**Diseño:** `docs/rediseno-ventanas.md` (aprobado el 20/11).

## Restricciones globales

- Textos con tres papeles:
  - etiqueta: 10 px, gris, en mayúsculas;
  - valor: 14 px, blanco;
  - destacado: 20 px.
- Verde: por debajo de su media (buen precio para comprar). Rojo: por encima. Acento: dorado.
- Sin ▲▼: «+»/«-» con color.
- Se mantienen `f.scanButton`, `UI.SetScanning`, `UI.SetStatus`, `UI.frame`, `PH.Show`, `PH.Lines`, `PH.Parse`, `PH.Get`, `PH.AnchorTarget`.
- `CreateLine`, iconos y color de calidad se comprueban antes de usarlos.

## Foco de revisión

1. Sin resumen, o con solo 1 o 2 días de datos: el panel no deja gráficas vacías con escala absurda; muestra «sin datos suficientes».
2. Todos los valores iguales (sin variación): la escala no divide por cero.
3. Búsqueda en la que la primera fila es una subasta propia o un precio raro: el precio en vivo es el mínimo de las demás.
4. Ventana principal con una ruta muy larga: el texto se corta o se recoloca sin salirse.
5. Cliente sin `CreateLine`: la gráfica de días cae a barras finas.

---

### Tarea 1: estilo común y precio en vivo correcto

**Archivos:** crear `Oroboros/Style.lua` (en el TOC, antes de `UI.lua`); `Oroboros/PriceHistory.lua`; `Oroboros/Core.lua` (`/oro precio debug`); `tests/run_tests.py`.

**Interfaces:**
- `ns.Style.C`: los colores (`bg`, `border`, `label`, `value`, `accent`, `good`, `bad`, `muted`).
- `ns.Style.Panel(frame, title) -> header`: fondo, borde, cabecera y «×».
- `ns.Style.Text(parent, role)`: `role` es `"label"`, `"value"`, `"big"`, `"small"` o `"title"`.
- `ns.Style.Button(parent, text, w, h, kind)`: `kind` es `"accent"` o `"neutral"`; responde a `SetText`, `Enable`, `Disable` y `SetButtonState`.
- `PH.LivePrice(rows) -> number|nil`, con `rows` = `{ {unitPrice, qty, mine} }`: el mínimo con `qty > 0` y sin `mine`.
- `PH.lastRows`: las 5 primeras filas de la última búsqueda.

- [ ] Prueba (falla):
  - en la búsqueda simulada de 2996 (fila 1 propia a 400, fila 2 ajena a 450), el panel muestra en vivo 450;
  - `PH.LivePrice` sin filas válidas da `nil`;
  - `/oro precio debug` escribe en el chat las filas de la última búsqueda.
- [ ] Implementar; pruebas en verde; commit.

### Tarea 2: panel de precios rediseñado

**Archivos:** `Oroboros/PriceHistory.lua`.

**Interfaces:** `PH.Model(itemID, live)` devuelve:
- `name`, `quality`, `today`, `diffPct` (con signo; `nil` sin media), `tone` (`"good"`, `"bad"` o `"neutral"`, con ±2 % como neutro);
- `stats`, una lista de `{label, value, sub}` con «MEDIA 7 D», «MEDIA 30 D», «MEDIA 90 D», «MÍNIMO» y «MÁXIMO»; `sub` es la fecha;
- `days` y `weeks`, listas de `{label, value|nil}` con fechas `dd/mm` calculadas desde `lastDay`;
- `bandsText` y `hasHistory`.

Con `nil` cuando no hay resumen. `PH.Lines` se mantiene, construido a partir del modelo.

- [ ] Prueba (falla):
  - con la cadena de prueba, `Model` da `diffPct` -12, `tone` `"good"`, cinco cifras y la fecha del mínimo «12/11»;
  - las etiquetas de los días acaban en «19/11» y la primera semana es «semana del 25/08»;
  - sin resumen, `hasHistory` es falso;
  - `PH.Show` funciona con y sin resumen, y con todos los valores iguales.
- [ ] Implementar el diseño:
  - cabecera con icono y nombre en el color de su calidad;
  - bloque «HOY» destacado y rejilla de cifras;
  - gráfica de 14 días: líneas, puntos, media de 30 días discontinua, escala, fechas extremas y leyenda;
  - gráfica de 13 semanas en barras;
  - zonas invisibles con el detalle (GameTooltip) al pasar el ratón por cada punto o barra;
  - franjas;
  - altura calculada.
- [ ] Pruebas en verde; commit.

### Tarea 3: ventana principal y cierre

**Archivos:** `Oroboros/UI.lua`, `Oroboros/Core.lua` y `Oroboros/Oroboros.toc` (0.8.0), README y hoja de ruta.

- [ ] Ventana principal con `Style`:
  - botones planos («Siguiente» con acento);
  - estado con el papel de valor y la ruta con el de valor pequeño;
  - pie con etiqueta y valor («PRÓXIMO ESCANEO», «ÚLTIMO», «GUARDADOS»);
  - altura según el contenido.
- [ ] Pruebas existentes en verde (botón «Escaneando…», estados); commit.
