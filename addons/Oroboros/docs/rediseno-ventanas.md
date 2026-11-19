# Rediseño de las ventanas del juego

Diseño del 20/11/2026, **aprobado por el usuario** («hazlo»). Cambio mediano: solo toca las dos ventanas del addon.

## Para qué

Las ventanas funcionan, pero cuestan de leer (captura del usuario, 20/11):

- En el panel de precios, la línea «Hoy…» ocupa dos líneas y se monta encima de la siguiente, porque las posiciones son fijas.
- Etiquetas y cifras tienen el mismo tamaño y color: hay que leerlo todo para encontrar un número.
- Las gráficas no tienen escala, fechas, leyenda ni detalle al pasar el ratón.
- La ventana principal tiene mucho hueco vacío y el pie en letra diminuta.
- Fallo: «Hoy 7c» cuando la subasta mostraba 11s 71c. El panel cogía la primera fila de la búsqueda, no la más barata de otros vendedores.

El usuario pide que sea cómodo, bonito y fácil de ver; el aspecto de Blizzard le da igual, y deja el diseño en nuestras manos.

## Objetivos

- Leer de un vistazo el precio de hoy y si es bueno, y luego las cifras clave.
- Gráficas con escala, fechas, leyenda y detalle al pasar el ratón.
- Nada solapado y nada de hueco vacío: la altura se ajusta al contenido.
- El precio en vivo, correcto.

## Fuera de alcance

- Otros cambios de función en las ventanas (la cola, la importación… se quedan igual).
- Opciones de tema o colores configurables.

## Enfoques

| Enfoque | Decisión |
|---|---|
| **Estilo propio oscuro y plano**, dibujado con lo que trae el juego | **Elegido**: sin dependencias y a juego con EllesmereUI, que usa el usuario |
| Usar la apariencia de EllesmereUI | Descartado: depende de código ajeno que puede cambiar |
| Una librería de interfaz (AceGUI…) | Descartado: añade una dependencia para dos ventanas |

## Diseño

**Estilo común** (`Oroboros/Style.lua`):

- Fondo casi negro al 92 % y borde de 1 px.
- Cabecera con el título y una «×» plana.
- Botones planos: de acento (dorado) o neutros, con estado pulsado y desactivado visible.
- Textos con tres papeles:
  - **etiqueta**: 10 px, gris, en mayúsculas;
  - **valor**: 14 px, blanco;
  - **destacado**: 20 px.
- Colores: verde si es buen precio para comprar (por debajo de su media), rojo si está por encima, dorado de acento.
- Fuente del juego (`STANDARD_TEXT_FONT`).

**Panel de precios:**

- Cabecera con el icono del objeto y el nombre en el color de su calidad.
- **Hoy**, en grande y coloreado, con «-23 % frente a su media de 30 días».
- Rejilla de etiqueta sobre cifra: medias de 7, 30 y 90 días; mínimo y máximo con su fecha.
- Gráfica **«Precio · 14 días»**: línea con puntos, línea discontinua de la media de 30 días, escala (máximo y mínimo), primera y última fecha, y leyenda. Al pasar el ratón por un punto: fecha y precio.
- Gráfica **«Precio · 13 semanas»**: barras con la misma escala, leyenda y detalle al pasar el ratón («semana del dd/mm · precio»). Las semanas sin datos se ven como hueco.
- Línea de franjas, si las hay.
- La altura se calcula según lo que haya.

**Precio en vivo:** el más bajo de todos los resultados de la búsqueda, sin contar las subastas propias. `/oro precio debug` escribe en el chat las primeras filas que devolvió el juego.

**Ventana principal:** el mismo estilo; el estado en texto legible; el pie en formato etiqueta y valor («PRÓXIMO ESCANEO 12:44 · ÚLTIMO 19/11 20:09 · GUARDADOS 5/12»); la altura se ajusta al contenido.

## Restricciones

- Lua 5.1, interfaz 16001, todo en `ns`. Las funciones que puedan no existir en Forever (iconos, color de calidad, `CreateLine`) se comprueban antes de usarlas, con alternativa.
- Sin caracteres que la fuente del juego quizá no tenga (nada de ▲▼): se usan «+» y «-» con color.
- Se mantienen los nombres que usa la lógica y las pruebas (`f.scanButton`, `UI.SetScanning`, `PH.Show`…).

## Decisiones del constructor

- Medidas y colores exactos; la ventana principal mantiene su sitio a la derecha de la subasta y el panel va debajo.
