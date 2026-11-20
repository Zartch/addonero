# Gráfica de lo que tienes: Alt+clic, tooltip y ventana «Lo que tienes»

Diseño y plan del 20/11/2026, **aprobado por el usuario** («haz las 3»). Cambio mediano.

## Para qué

Ver el historial de precios de los objetos propios sin estar en la subasta ni tener el banco abierto. Oroboros ya guarda bolsas, banco y banco de banda de cada personaje; falta llegar cómodamente a la gráfica.

## Diseño

1. **Alt + clic en cualquier objeto** (bolsas, banco, enlace del chat, profesiones…) abre el panel de precios con los datos guardados.
   - Se engancha a `HandleModifiedItemClick` con `hooksecurefunc`, solo si existe.
   - Sin la subasta abierta, el precio de «hoy» es el último guardado.
2. **Tooltip:** «Oroboros  <precio con iconos>  +8 % frente a su media de 30 días» (verde si está por debajo, rojo si está por encima) y la línea gris «Alt+clic: historial de precios».
   - `PH.TooltipInfo(itemID)` devuelve `{ price, diffPct, tone }` y el tooltip lo pinta.
3. **Ventana «Lo que tienes»** (`Oroboros/Inventory.lua`, `/oro inventario` y un botón en la ventana principal).
   - Junta todos los personajes: bolsas, banco (el último guardado) y banco de banda.
   - Una fila por objeto: icono y nombre, dónde está, unidades, valor total con iconos, 14 barritas de los últimos días y la tendencia frente a la media de 30 días.
   - Ordenada por valor, con buscador por nombre, desplazamiento con la rueda y el total al pie.
   - Al hacer clic en una fila se abre el panel de precios a su lado.
   - **Precio unitario**: el de la subasta si hay unidades publicadas; si no, el «hoy» del resumen; si no, la venta al vendedor (marcada).
   - `Inventory.Rows(filter) -> rows, total` es el modelo, sin dibujar nada.

## Pruebas

- Alt + clic sobre un enlace abre el panel de ese objeto; sin Alt no hace nada.
- `TooltipInfo` da el precio y la diferencia con su tono.
- `Inventory.Rows`:
  - suma bolsas y banco;
  - el valor es unidades × precio;
  - va ordenada de mayor a menor valor;
  - el filtro por nombre funciona;
  - el total es la suma de las filas.
- `/oro inventario` abre la ventana.
