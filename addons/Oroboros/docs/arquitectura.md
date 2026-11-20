# Oroboros — arquitectura y decisiones

Objetivo: ganar oro en **WoW Forever** con un addon de subasta + un planificador externo.

## Decisiones (15/11/2026)
- Versión: WoW Forever (lanzado 4/11/2026). Usa la API moderna de Midnight, subasta tipo Retail con commodities por cantidad. Interfaz **16001** (cliente 1.60.1; corregido el 16/11, antes 120105).
- Forever no tiene todavía API oficial de precios de subasta → **precios y profesiones salen del escaneo en el juego**. Si Blizzard la abre, se añade como segunda fuente.
- Comprar, publicar y fabricar necesitan evento de hardware: **un clic (o tecla) por acción**, nunca automatizado del todo (riesgo de baneo).
- El addon no tiene red: datos fuera vía SavedVariables (`/reload`), ruta dentro pegándola en el addon.
- Los números los calcula código (planificador en Python), no un LLM. Un LLM, si se usa, solo explica, prioriza o propone ideas extra a partir de `--brief`.
- Hasta tener un escaneo real se trabaja con **datos sintéticos** (`tools/make_synthetic.py`).
- La fase del servidor **no** se estima con la hermandad (todos llegan a la vez y tarde): se lee en el mercado. Una fuente externa de población sería un apoyo, no la base.
- El addon lleva un **libro de compras y ventas reales** y guarda las apuestas abiertas; el planificador decide cuándo vender.
- La especulación va **separada** de la ruta normal: presupuesto propio (15 % del oro, solo lo que sobra tras la ruta), ruta propia y objetivos presentados como escenarios con stop.
- **Multipersonaje con banquero**: un personaje de nivel bajo parado en la subasta hace todas las compras y ventas; los demás solo fabrican. Los datos son de la cuenta, así que el banquero conoce las recetas de todos.

## Decisión (16/11/2026): no solapar con el addon de subasta instalado
- El usuario ya usa un addon de subasta que escanea y guarda precios. El escaneo completo tiene un límite de uno cada 15 minutos compartido por todos los addons: escanear dos veces no aporta nada.
- Es **Auctionator 341**. Por defecto no usa `ReplicateItems` (escaneo resumen con `SendBrowseQuery`); el usuario activa su escaneo completo.
- En el juego: con Auctionator escaneando, Oroboros no pide otro `ReplicateItems` y **lee el mismo resultado** (el evento llega a todos los addons). Así conserva profundidad y valor de mercado. `/oro scan forzar` para el propio.
- Fuera del juego: el exportador lee `Auctionator.lua` (su base va en CBOR) y rellena histórico y precios que falten. No se usa su tabla interna desde el juego: su API pública solo da el mínimo.
- Lo que Auctionator no tiene (profundidad, valor de mercado) se estima y baja la confianza. Detalle en `docs/fuentes-de-precios.md`.

## Flujo (v0.5.0)
1. Addon: escaneo completo (ReplicateItems cada 15 min): precio mín./valor de mercado (15 % más barato)/cantidad/profundidad (uds a ≤ mín ×1,10/1,25/1,5/2) + histórico diario 30 días. Recetas aprendidas y no aprendidas con reactivos, origen y enfriamiento. Precios de vendedor. Oro, bolsas, banco y banco de banda con huecos libres. Nivel de objeto. **Libro** (`ledger`): cada compra en subasta (objeto, cantidad, precio real; con la ruta o a mano) y cada venta cobrada por correo. **Apuestas** (`positions`): cada `HOLD` importado con objetivo, stop, fecha y entrada.
2. `tools/oroboros_export.py`: SavedVariables → SQLite (`items, prices, history, characters, inventory(location), slots, professions, recipes, reagents, ledger, positions, config`).
3. `tools/oroboros_plan.py` + `catalog.json`: márgenes por receta con explicación, transformaciones, qué aprender, qué tienes, reventas y rutas dentro del presupuesto (80 % del oro). Salida: `plan.html`, `plan.json`, `ruta_todo.txt` y una ruta por personaje.
4. `tools/oroboros_ideas.py` (lo llama el planificador): apuestas a unos días → pestaña Ideas, `ideas_todo.txt` (con líneas `HOLD`), pestaña Cartera, y `--brief` (resumen del mercado para un LLM).
5. Ruta → addon → botón "Siguiente".

## Varios personajes
- SavedVariables es por cuenta: `chars[charKey]` guarda profesiones, bolsas y banco de cada personaje; hay que entrar con cada artesano y abrir sus profesiones (aviso si tienen > 7 días).
- Banquero: `/oro banquero` (se guarda en `config.banker`) o `--banker Nombre`; `--banker none` = cada uno compra y vende lo suyo.
- Con banquero: todos los `BUY`/`SELL` (ruta, reventas, stock, cartera, ideas) van al banquero; los artesanos solo tienen `CRAFT` y `NOTE` (banco, correo, vendedor). Cada envío por correo tiene su recogida (hay test).
- Ruta del banquero en dos fases: comprar y repartir → "entra con los artesanos" → recoger y vender. Entre artesanos va antes el que fabrica para otro.
- Rutas por personaje en el addon (`routes[charKey]`). Una ruta con secciones `CHAR Nombre` se pega una vez y se reparte; "Añadir a la ruta" suma sin borrar (para la ruta de ideas). La ventana avisa de personajes con pasos pendientes.
- En el juego: `/oro quien <objeto>` y tooltip con precio y quién lo fabrica.
- Correo y vendedor no se automatizan (son NOTE).

## Reglas del planificador
- Precio de venta prudente: el de hoy, pero nunca > mediana 7 días × 1,15.
- Cantidad: lo que el mercado absorbe en el horizonte (48 h por defecto), máx. 30 % de lo publicado, y el enfriamiento.
- **Lote de prueba** (18/11/2026, primer plan real): sin histórico para medir ventas/día (menos de 3 bajadas de cantidad entre días), como mucho 20 unidades o 1 oro por fabricación o reventa. Antes se suponía un 10 % de lo publicado al día y salían cientos de unidades.
- Lo de confianza baja suma como mucho el 30 % del presupuesto.
- Qué aprender: en Forever `GetRecipeSourceText` no da nada y la lista incluye recetas de otras expansiones. Una receta está «a tu alcance» si el catálogo dice su nivel y lo tienes, o si el juego le da dificultad 1–3; con dificultad 0 (ambiguo) va a «nivel sin comprobar», al final.
- Margen mínimo 8 %. Confianza alta/media/baja por volatilidad, ventas/día y días de histórico.
- Selección por beneficio por oro invertido × confianza. Stock propio primero: bolsas → banco → banda → banquero → otro personaje (NOTE de banco/correo).
- No se vende stock de un objeto sobre el que hoy hay señal de compra (ideas).

## Ideas de especulación
| Tipo | Señal | Riesgo |
|---|---|---|
| Despensa | reactivo que la ruta ya compra, ≥ 8 % bajo su mediana 14 d → comprar para 5 días | bajo |
| Rebote | precio ≥ 15 % bajo su mediana 14 d con ventas ≥ 3/día | medio |
| Ciclo semanal | día caro y día barato coinciden en las dos semanas, diferencia ≥ 15 % | medio |
| Oferta que se seca | publicado −30 % en 2 semanas y precio subiendo | medio |
| Evento | fecha en `catalog.json` a 3–35 días (bandas: 9/12/2026) y lista de objetos con multiplicador | medio |
| Progresión | nivel de objeto ≤ 40, con uso a nivel 60. **Compra** solo si lo publicado cae ≥ 12 % en el histórico (regresión) y el precio de los últimos 5 días ya no baja (≥ −0,5 %/día); si no, **vigilancia** con el motivo. Plazo fijo de 21 días (`progression_horizon_days`) | alto |

- Fase del servidor: mediana del cambio de oferta y precio de los materiales de nivel bajo (≤ 40) frente a los de nivel alto (≥ 50). Es contexto; la decisión es objeto por objeto.
- Una idea por objeto (las demás señales quedan como apoyo). Si se sabe fabricar más barato, la idea es fabricarlo.
- Tamaño: mínimo entre 35 % del presupuesto de especulación, lo que hay a ≤ mín ×1,10, el 25 % de las ventas de una semana y los huecos libres (máx. 40 % por idea). Se reparte primero a riesgo bajo.
- Salida: fecha y precio objetivo, precio de equilibrio (entrada ÷ 0,95) y stop a −20 %.
- Multiplicadores de evento y progresión en `catalog.json` son **suposiciones** editables.

## Cartera
- Entrada = media de las compras del libro desde un día antes del `HOLD`; si no hay (fabricado o comprado sin addon), la prevista.
- Cantidad viva = min(plan − vendido, lo que hay en bolsas/banco/banda).
- Estados: objetivo (precio ≥ objetivo), stop (precio ≤ stop), vencida (fecha pasada), espera, cerrada. Objetivo, stop y vencida-en-beneficio añaden un `SELL` a la ruta (mínimo: precio de hoy × 0,92; × 0,85 en stop).
- No se propone una idea nueva sobre un objeto con apuesta abierta.

## Formato de ruta
```
CHAR  <Nombre>
BUY   <itemID> <cantidad> <precioMaxUnidad>
SELL  <itemID> <cantidad> <precioMinUnidad>
CRAFT <recipeID> <veces>
NOTE  <texto>
HOLD  <itemID> <cantidad> <objetivo> <stop> <AAAA-MM-DD> [entrada]
```
Precios en cobre o `1g23s45c`. `#` = comentario.

## Pendiente
- Hoja de ruta por fases (modelo de datos, seguimiento de precios, automatización, cálculos): `docs/hoja-de-ruta.md`. Fase 1 (archivo normalizado, histórico diario, resumen semanal, 8 semanas en bruto) hecha el 19/11.
- Validar en el juego la lectura pasiva del escaneo de Auctionator.
- Clave de mercado: Forever tiene un único reino interno (`CAMWOWEU5Realm5PvE`, sin reinos conectados; `GetRegionalRulesetName()` devuelve `nil`). Falta saber si la subasta se comparte entre facciones; si es así, quitar la facción de `ns.MarketKey`.
- Hecho (20/11): duraciones de Forever (2/8/24 h), publicando a 24 h. `catalog.json` con datos reales (lanzamiento 4/11 y bandas del 9/12); las pruebas usan `tests/catalogo_sintetico.json`.
- Búsqueda puntual de los objetos de la ruta para tener profundidad real cuando los precios vengan solo de Auctionator.
- Validar en el cliente real (escaneo, banco, compra pequeña, publicación, libro de compras y facturas del correo, tooltip).
- Confirmar las reglas de correo entre personajes en Forever (facción, reino, tiempo de entrega).
- Automatizar el correo con un clic por envío (línea `MAIL`), si compensa.
- Ajustar `catalog.json` con datos reales de Forever.
- Fuente externa de población como apoyo, si aparece una fiable.
- Coste real de lo fabricado en la cartera.
- Coste de subir una profesión hasta el nivel que pide una receta.
