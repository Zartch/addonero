# Libranzas y precio de venta en «Qué tienes» (27/11)

## Qué pide el usuario

1. En «Qué tienes», para todo lo que llevas (equipo incluido): subasta o vendedor. Si va a subasta, cuánto se vende al día y a qué precio publicarlo. Si conviene ponérselo o no lo decide otro addon (ProItem): aquí no se mira.
2. Las libranzas del artesano (pergaminos que dan una misión de fabricación): vender la libranza o cumplir la misión.

## Lo que hay

- `inventory_view` ya elige entre subasta, vendedor, guardar o ruta, pero solo dice «~X neto cada uno». `stats()` ya calcula las ventas al día (`vol`, de dónde salen y si son supuestas) y el precio de venta (`sell`, con techo `LOW_CEIL`).
- Las libranzas se venden en la subasta: unas 200 a la semana de cada tipo y casa, a 0,5–2 oro. Lo que piden fabricar suele costar unas platas.
- Nadie sabe la recompensa de cada misión: ni la API ni el addon la guardan.

## Cómo se hace

**Addon (`Oroboros/Misiones.lua`).** Al abrir la ventana de una misión que empieza con un objeto (`QUEST_DETAIL`, primer argumento: el objeto), apunta en `OroborosDB.questItems[objeto]`:
- el dinero, la experiencia, los objetos de recompensa y los de elegir;
- el texto de objetivos y la hora.

Si el juego no da el objeto, usa el último que usaste de la bolsa en los últimos 15 segundos (`hooksecurefunc` sobre `C_Container.UseContainerItem`, que solo mira). No acepta la misión ni hace nada por ti: solo lee lo que la ventana ya enseña. Aceptar seguramente gasta la libranza, así que hay que leerla antes de aceptar.

**Exportar.** Nueva tabla `quest_items (item_id, quest_id, title, money, xp, rewards, choices, objective, t)`, con las recompensas en JSON.

**Plan.**
- `Data.quest_items` lee esa tabla; si el SQLite es antiguo, queda vacía.
- Es una libranza si el nombre empieza por «Libranza del artesano:» o si hay recompensa apuntada para ese objeto.
- **Lo que pide:**
  - El objeto es el que tiene el mismo nombre que lo que va detrás de los dos puntos.
  - La cantidad es el primer número del texto de objetivos que va junto al nombre. Si no se encuentra, se supone 1 y se dice que es supuesto.
  - El coste es `best_source`: fabricarlo, subasta o vendedor, lo más barato. Si ya lo llevas encima, cuenta lo que sacarías vendiéndolo.
- **Lo que da:** el dinero, más los objetos (lo que sacarías vendiéndolos), más el mejor de los objetos de elegir. La experiencia no se pasa a oro: se dice.
- **Decisión:**
  - **Con recompensa apuntada:** si lo que da menos lo que cuesta supera lo que sacas vendiendo la libranza, «cumplir»; si no, subasta.
  - **Sin recompensa apuntada:** si cumplirla cuesta más que venderla, subasta («ni regalada la recompensa compensa»); si no, «mirar» («abre la misión en el juego para que se apunte la recompensa»).
- **Ventas al día y precio recomendado:** cada fila que va a subasta lleva `vol`, `vol_est` y `price`:
  - `price` es el precio de publicación por unidad: `stats()["sell"]`, el que usa el plan.
  - `floor` es el mínimo: el mismo 85 % que ya usa la ruta.
  - La página lo enseña en la columna «Qué hacer».

## Pruebas

- **Addon:** `QUEST_DETAIL` con objeto apunta el dinero, los objetos y lo que se puede elegir. Sin objeto pero con uno usado hace un momento, apunta el usado. Sin ninguno, no apunta nada.
- **Exportar:** la tabla `quest_items`.
- **Plan:**
  - Libranza sin recompensa y barata de cumplir: «mirar».
  - Sin recompensa y cara de cumplir: subasta.
  - Con recompensa que compensa: «cumplir».
  - Con recompensa que no compensa: subasta.
  - Las filas de subasta llevan ventas al día y precio.

## Por comprobar en el juego

- Que `QUEST_DETAIL` da el objeto en Forever.
- Que la cantidad sale bien del texto de objetivos.
- Si aceptar gasta la libranza.
