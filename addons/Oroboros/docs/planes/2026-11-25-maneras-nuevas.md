# Fase 7: maneras nuevas — plan

**Objetivo:** tres fuentes de oro que el plan no miraba, cada una con una regla que no prometa de más.

## 1. Aguasnegras → tu casa

- La API ya descarga la casa neutral de nuestro reino (117). `oroboros_api.neutral_house` la encuentra por la clave de mercado (`<reino>-Neutral`).
- `find_neutral` (planificador) recorre la lista de precios de Aguasnegras de barato a caro y compra mientras quede el margen mínimo de una reventa (15 %) vendiendo en tu casa justo por debajo de lo más barato de allí, sin pasar de la mediana de 7 días. Al comprar no hay comisión; al vender en tu casa, el 5 %, más el depósito.
- Filtros: solo lo que se apila (el equipo con sufijo mezcla productos distintos), sin objetos con variantes, y **solo con ventas comprobadas en tu casa**: las de tus escaneos (3 días o más) o las de la API ya calibrada. Las ventas supuestas no valen.
- Cantidad: como mucho la mitad de lo que se vende en el horizonte.
- No entra en la ruta normal (hay que ir a una subasta neutral): va en su lista, con sus líneas `BUY` para pegar allí. Usa el oro que queda para apuestas después de las ideas.
- Dice si compensa el viaje: 2 oro o más en total, y con una foto de menos de 3 h.

## 2. Enfriamientos como renta diaria

- `catalog.json`, sección `recipes`: enfriamiento en horas de las transmutaciones (arcanita y legionita 47 h, esencias 23 h, hierro a oro y mitril a veraplata 1 h), con fuente y sin comprobar.
- `cooldown_groups`: las transmutaciones comparten un enfriamiento (sin confirmar en Forever; se supone que sí para no contar dos veces). En la ruta, por personaje se queda la que más da. En «qué aprender», las demás dicen que no se suman.
- «Qué aprender» valora estas recetas por lo que dan al día: beneficio por uso × usos al día, con un máximo de 2 usos al día (nadie entra cada hora).

## 3. Gangas en el panel

- `oroboros_api.bargains`: subastas que **aparecen en la última foto** al menos un 30 % por debajo de la mediana de 7 días del objeto, con 50 platas o más de diferencia ya sin comisión.
- No cuenta si ya había subastas más viejas a ese precio (es el precio nuevo, no una ganga), ni el equipo con variantes, ni lo que no tiene ventas estimadas. Mientras el archivo no tenga variantes guardadas, tampoco lo que no se apila.
- La cantidad no pasa de la mitad de lo que se vende al día.
- La pestaña Inicio del panel las lista (`/api/inicio`, clave `bargains`).

## Pruebas

En `tests/run_tests.py`, bloque «Fase 7»: casa neutral, gangas (aparece, ya estaba, descuento corto, sin apilar, con variantes), `find_neutral` (compra, presupuesto, variantes, foto vieja, sin ventas comprobadas), enfriamiento compartido, catálogo y renta diaria.
