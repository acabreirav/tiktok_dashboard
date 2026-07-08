# CLAUDE.md — Radar de Tracción (monitor de cuentas TikTok)

> Este archivo es la memoria del proyecto. Léelo completo antes de escribir código.
> Contiene el objetivo, las decisiones ya tomadas, la arquitectura, y **cómo guiar a la persona**,
> que sabe programar a nivel básico pero **nunca ha desplegado nada en GitHub**.

---

## 0. Cómo trabajar conmigo (leer primero)

- **Nunca he usado git para desplegar ni configurado GitHub Actions, Secrets o Pages.** Asume cero conocimiento de despliegue.
- Explica **cada comando** antes de que lo corra: qué hace, qué debería ver como resultado, y qué hacer si falla.
- Para pasos en la web de GitHub (crear repo, agregar secrets, activar Pages), dame **instrucciones clic a clic**, no solo el nombre del menú.
- Avanza en **incrementos pequeños y verificables**. Después de cada paso, dime exactamente qué revisar antes de seguir.
- **Prueba local antes de subir.** Nada llega a GitHub sin haber corrido en mi máquina primero.
- **Pide confirmación antes de cualquier cosa que gaste dinero** (correr actors de Apify) o sea irreversible (borrar, force-push).
- Explica el *por qué* en una frase cuando introduzcas algo nuevo (git, cron, secrets). Quiero aprender, no solo copiar.
- Si algo puede hacerse simple o "elegante-pero-complejo", elige **simple**. Es un proyecto pequeño.

---

## 1. Qué estamos construyendo

Un panel/reporte que se genera **periódicamente** con métricas de crecimiento y tracción de un conjunto de
cuentas públicas de TikTok (de terceros, no propias), para detectar cuáles ganan momentum y por qué.

### El insight que define toda la arquitectura
TikTok **no entrega histórico** de cuentas ajenas: cualquier fuente da solo una **foto del momento**
(seguidores, likes totales, y por cada video sus views/likes/comentarios/shares actuales).
**Por lo tanto las tasas de crecimiento no vienen de la API: las generamos nosotros** tomando fotos
periódicas y guardándolas. El corazón del proyecto es: `snapshot → guardar → comparar contra la foto
anterior → reportar el delta`. **Sin base de datos propia de snapshots, no hay growth rate.** La
periodicidad es lo que produce los datos.

### Lo que NO se puede obtener (no intentarlo)
Analytics interno de TikTok (alcance real, impresiones, fuentes de seguidores, demografía), contenido
privado o borrado. Solo trabajamos con **data pública**.

---

## 2. Decisiones ya tomadas (no re-litigar)

- **Fuente de datos:** Apify (actors de scraping de TikTok). La persona **ya tiene cuenta y API token**.
- **Cómputo + scheduler:** **GitHub Actions** con cron (gratis, corre en la nube aunque el PC esté apagado).
- **Almacenamiento:** el **repo mismo es la base de datos** — snapshots como archivos JSON commiteados.
  Nada de servidor ni base de datos externa. (SQLite es una opción futura si crece mucho; JSON basta para empezar.)
- **Publicación del reporte:** **GitHub Pages** sirviendo la carpeta `docs/`. El dashboard se regenera en cada corrida.
- **Lenguaje del pipeline:** **Python** (fetch, cómputo, generación de data). El dashboard es HTML/CSS/JS estático.
- **Presupuesto:** empezar en **free tier** (Apify da ~$5 de crédito/mes). Objetivo inicial: que quepa gratis.
- **Escala:** empezar con **~20 cuentas** para validar consumo real, luego subir hacia 50.
- **Diseño del reporte:** ya existe un prototipo funcional (ver §7). Hay que **respetar su lenguaje visual**.

---

## 3. Arquitectura y flujo

```
[GitHub Actions · cron diario]
        │
        ├─ fetch.py       → llama a Apify, guarda snapshot crudo en data/snapshots/AAAA-MM-DD.json
        │
        ├─ build_report.py→ lee TODOS los snapshots, calcula métricas por ventana (7/14/30d),
        │                     escribe docs/data.json (métricas ya computadas)
        │
        └─ git commit + push → GitHub Pages sirve docs/index.html, que carga docs/data.json
```

El dashboard (`docs/index.html`) es estático: **no calcula nada pesado**, solo lee `docs/data.json` y pinta.
Toda la lógica de métricas vive en Python (`build_report.py`), así queda testeable y reproducible.

---

## 4. Estructura del repo (objetivo)

```
radar-traccion/
├─ CLAUDE.md                  # este archivo
├─ README.md                  # cómo correr local + cómo funciona
├─ .gitignore                 # ignora .env, __pycache__, etc.
├─ .env.example               # muestra qué variables hacen falta (SIN valores reales)
├─ requirements.txt           # dependencias Python
├─ config/
│   └─ accounts.json          # lista de handles a monitorear (la persona la edita)
├─ src/
│   ├─ fetch.py               # snapshot: Apify → data/snapshots/
│   ├─ build_report.py        # snapshots → docs/data.json
│   ├─ metrics.py             # funciones puras de cálculo de métricas (testeables)
│   └─ apify_client.py        # wrapper delgado sobre la API de Apify
├─ data/
│   └─ snapshots/             # histórico: un JSON por corrida (esto es la "base de datos")
├─ docs/                      # lo que sirve GitHub Pages
│   ├─ index.html             # el dashboard (basado en el prototipo)
│   └─ data.json              # métricas computadas (regenerado cada corrida)
├─ tests/
│   └─ test_metrics.py        # tests de las fórmulas con data de ejemplo
└─ .github/workflows/
    └─ snapshot.yml           # cron + fetch + build + commit
```

---

## 5. Modelo de datos

### `config/accounts.json` (editable por la persona)
```json
{ "accounts": ["cocina.express", "martina.fit", "dato.curioso"] }
```

### Snapshot crudo `data/snapshots/2026-07-06.json`
Guarda por cuenta, para esta fecha: metadatos de perfil + lista de videos recientes.
**No inventes los nombres de campo** — dependen del actor de Apify (ver §6). Normaliza a este esquema interno:
```json
{
  "date": "2026-07-06T09:00:00Z",
  "accounts": [
    {
      "handle": "cocina.express",
      "followers": 95120, "following": 312, "likesTotal": 1840000, "videoCount": 402,
      "verified": false,
      "videos": [
        { "id": "...", "postedAt": "2026-07-04T...", "views": 51200,
          "likes": 6100, "comments": 210, "shares": 340, "caption": "..." }
      ]
    }
  ]
}
```
Guardar **crudo lo suficiente** para poder recalcular métricas después si cambiamos fórmulas. El snapshot es la fuente de verdad; `data.json` es derivado y desechable.

---

## 6. Integración con Apify (leer con cuidado — aquí se gasta plata)

- La persona tiene un **APIFY_TOKEN**. En local va en `.env` (nunca commiteado). En Actions va como **GitHub Secret**.
- **Antes de construir el parser: corre un test mínimo (2–3 cuentas) e inspecciona el JSON real que devuelve el actor.**
  Los nombres de campo varían entre actors. No asumas el esquema; verifícalo con una corrida chica y de ahí escribe el normalizador.
- Actors candidatos (elige uno tras probar salida y costo): `clockworks/tiktok-profile-scraper`,
  `apidojo/tiktok-scraper`, u otro equivalente perfil+videos. Prioriza el que dé perfil **y** videos recientes barato.
- **Guardas de costo (obligatorias):**
  - Nunca dispares una corrida grande sin confirmación mía.
  - Limita videos recientes por cuenta (empezar en **~10–15**).
  - Muéstrame el costo estimado antes de escalar de 3 → 20 → 50 cuentas.
  - Tras la primera semana real, revisamos el crédito consumido en Apify y ajustamos cadencia.
- **Cadencia inicial (simple primero):** un solo workflow **diario** que trae perfil + ~10-15 videos recientes.
  Optimizamos después con data real (ej. perfil diario + videos cada 2 días) si hace falta para caber en free tier.
- Manejar errores del actor: si una cuenta viene privada/borrada, registrar el error y **seguir con las demás**, no abortar la corrida.

---

## 7. El reporte / dashboard

**Existe un prototipo funcional** (`radar-traccion.html`, que la persona puede aportar al repo como referencia de diseño).
El dashboard de producción debe **igualar su lenguaje visual** y adaptarlo para leer `docs/data.json` real.

### Lenguaje visual (v2 ejecutiva, decidida 2026-07-07 — reemplaza al prototipo oscuro)
- **Tema claro ejecutivo**: fondo #F7F8FA, cards blancas con borde #E4E8EF y sombra suave, tinta #1A2233.
- **El color codifica BLOQUE POLÍTICO** (así piensa el lector): **gobierno = azul petróleo #17679E**, **oposición = terracota #C2410C**, independientes = gris #6B7280. Paleta validada para daltonismo; deliberadamente ninguno es color de campaña de un partido (neutralidad visual).
- Verde #15803D = subidas, rojo #DC2626 = bajadas — siempre con signo y flecha ▲▼, nunca color solo.
- Tipografía: Space Grotesk (títulos), JetBrains Mono (números), Inter (texto).
- **Una sola fila de filtros** gobierna todas las secciones: ventana 7/14/30d, **red (global/TikTok/Instagram)**, sector, coalición, partido, territorio, buscador de legislador.
- **Cada métrica declara su fuente** con un chip: audiencia/crecimiento = TikTok, IG o TikTok+IG según la red activa; contenido (Δviews, engagement, velocidad, breakouts, momentum) = siempre TikTok. En modo Instagram (perfil-only) las secciones de contenido se declaran "n/d en IG" en vez de mostrar ceros; audiencia/crecimiento/cobertura siguen. Global suma seguidores de ambas redes.

### Secciones (en orden)
1. **El período en 4 números** (tiles): crecimiento del conjunto, atención capturada (Δviews), legislador con más momentum, video de la semana.
2. **Bloques en comparación**: gobierno vs oposición — crecimiento agregado, share of voice (barra dividida), engagement mediano, cobertura (con cuenta / total / activas 30d), desglose por coalición.
3. **Mapa de momentum**: scatter X=crecimiento, Y=tracción, color=bloque, etiqueta=apellido; 4 cuadrantes (*En ascenso*, *Viral sin capturar*, *Crecen en frío*, *En pausa*).
4. **Ranking de legisladores**: tabla ordenable con chip de partido; clic en fila abre la ficha.
5. **Ficha individual** (misma página): stats, curva de seguidores, comparación vs la mediana de su bloque, videos top con badge de breakout.
6. **Terreno cedido**: sin cuenta de TikTok o sin publicar >30 días.
7. **Lecturas del período**: insights determinísticos generados sobre el conjunto filtrado.

División del trabajo: métricas por cuenta en Python (`build_report.py` → `data.json`, incluye `roster` con la base completa); agrupaciones/filtros en JS (livianos).

---

## 8. Métricas a calcular (definiciones exactas)

Todas se calculan sobre una **ventana** (7/14/30 días) comparando snapshots. Implementar en `metrics.py` como funciones puras.

**Por cuenta:**
- **Crecimiento de seguidores** — absoluto (`f_fin − f_inicio`) y porcentual.
- **Aceleración** — crecimiento de la 2ª mitad de la ventana vs la 1ª mitad. Ratio >1.25 = *acelera*, <0.8 = *enfría*, medio = *estable*.
- **Engagement rate** — mediana por video de `(likes + comentarios + shares) / views × 100`.
- **Velocidad de views (tracción)** — mediana de `Δviews/día` de los videos activos, **normalizada por cada 1.000 seguidores** (para comparar cuentas de distinto tamaño). Requiere ≥2 snapshots del mismo video.
- **Velocidad temprana** — views acumuladas en las primeras 24–48h tras publicar. Es el **mejor predictor de viralidad**, pero requiere snapshots frecuentes los primeros días. Implementar cuando la cadencia lo permita; dejar el gancho listo.
- **Cadencia de publicación** — videos nuevos por semana (de `videoCount` o de fechas de posteo).
- **Views por seguidor** — mediana de `views_video / seguidores`. Detecta cuentas que rinden sobre su tamaño.

**Comparativas / eventos:**
- **Breakout** — video con `views ≥ 3 × mediana de views de esa cuenta`, publicado dentro de la ventana.
- **Alertas** — aceleración fuerte, enfriamiento, caída de cadencia (< 60% de la cadencia previa), breakout.

Usar **mediana, no promedio**, en métricas por-video (los outliers virales distorsionan el promedio).

---

## 9. Insights inteligentes (dos capas)

- **Capa calculada (determinística, GRATIS):** las reglas de §8. Es la base del reporte y **debe funcionar sin conexión ni costo**. Corre siempre en el pipeline.
- **Capa narrativa con IA (opcional):** un resumen en prosa generado por Claude (API de Anthropic) que interpreta las métricas del período. En el pipeline requiere una **ANTHROPIC_API_KEY** (costo pequeño por corrida) — hacerla **opcional vía variable de entorno**: si no está la key, el reporte se genera igual sin la narrativa. No la hagas un requisito duro.

---

## 10. Despliegue (guiar a la persona clic a clic)

Cuando lleguemos a esta fase, guiar en este orden, explicando cada paso:
1. **Repo:** crear el repositorio en GitHub (privado está bien) y conectarlo al proyecto local con git.
2. **.gitignore primero:** confirmar que `.env` está ignorado **antes** del primer commit. El token nunca debe llegar a GitHub.
3. **Primer push:** explicar `git add` / `commit` / `push` en lenguaje simple.
4. **Secret:** en GitHub → repo → *Settings* → *Secrets and variables* → *Actions* → *New repository secret* → nombre `APIFY_TOKEN`, valor el token. (Ídem `ANTHROPIC_API_KEY` si usamos IA.)
5. **Workflow:** explicar qué es el cron en `snapshot.yml` y cómo lanzarlo manualmente la primera vez (*Actions* → *Run workflow*) para probar sin esperar al horario.
6. **Pages:** *Settings* → *Pages* → servir desde la carpeta `docs/` de la rama principal. Explicar que la URL del dashboard queda pública (advertir si es sensible).
7. Verificar el ciclo completo: correr workflow → ver commit nuevo con snapshot → ver dashboard actualizado en Pages.

---

## 11. Convenciones y límites

- **Nunca commitear secretos.** `.env` en `.gitignore` desde el minuto cero. Solo `.env.example` con nombres, sin valores.
- **Solo data pública.** No intentar login, contenido privado ni endpoints de auth.
- Código legible y comentado en español donde ayude. Funciones de métricas **puras y testeadas**.
- El snapshot crudo es sagrado: no lo sobreescribas, un archivo por corrida.
- Antes de cambiar una fórmula de métrica, actualizar su test.
- Manejo de fallos con voz de interfaz: si una cuenta falla, se registra y se continúa.

---

## 12. Plan de construcción (fases — seguir en orden, confirmar entre cada una)

**Fase 0 — Setup local.** Estructura de carpetas, `requirements.txt`, `.gitignore`, `.env.example`, `config/accounts.json` con 2-3 cuentas de prueba. Correr un "hola mundo" que confirme que Python y el entorno funcionan. *(Sin tocar GitHub ni Apify todavía.)*

**Fase 1 — Fetch mínimo.** `apify_client.py` + `fetch.py` para **2-3 cuentas**. Inspeccionar el JSON real de Apify, escribir el normalizador al esquema de §5, guardar un snapshot. **Confirmar costo antes de correr.**

**Fase 2 — Métricas + reporte con 1 solo snapshot.** `metrics.py` con tests, `build_report.py` que genera `docs/data.json`. Adaptar el prototipo (`docs/index.html`) para leer datos reales. Verás el dashboard con data real aunque sin crecimiento aún (solo hay una foto).

**Fase 3 — Segundo snapshot → aparecen las tasas.** Correr fetch un segundo día (o simular una segunda fecha para probar la lógica de ventanas). Confirmar que crecimiento, aceleración, velocidad y breakouts se calculan bien con 2+ puntos.

**Fase 4 — Despliegue.** Guía de §10: repo, secret, workflow, Pages. Lanzar el workflow a mano, verificar el ciclo completo.

**Fase 5 — Escalar y calibrar.** Subir a ~20 cuentas, revisar consumo de crédito Apify tras una semana, ajustar cadencia/depth para caber en free tier. Luego hacia 50.

**Fase 6 (opcional).** Capa narrativa con IA; velocidad temprana (24-48h); notificación por email del reporte.

**Fase 7 — Mantenedor de cuentas.** Herramienta para administrar la lista de cuentas monitoreadas sin editar JSON a mano. *Alcance por definir cuando lleguemos — ideas anotadas:*
- Agregar y quitar cuentas (¿CLI simple? ¿página aparte en el dashboard que edite via PR/commit?).
- Filtrar/etiquetar cuentas (ej. por categoría o campaña) y poder ver el dashboard filtrado.
- **Tope duro de cuentas a scrapear** para no reventar la cuota de Apify: el fetch se niega a correr si las cuentas activas superan el máximo (hoy `MAX_CUENTAS = 60` en `src/fetch.py`; pasaría a configuración).
- Decidir qué pasa con el histórico de una cuenta que se quita (¿se archiva? los snapshots viejos no se tocan).
- Validar handles al agregarlos (que existan y sean públicos) antes de gastar crédito en una corrida completa.

---

## 13. "Listo" de la Fase 1 (primer hito real)
Un `git`-repo local que, corriendo `python src/fetch.py`, produce un snapshot válido de 2-3 cuentas en
`data/snapshots/`, con el token leído de `.env`, sin errores, y con el costo Apify conocido y aceptado.

---

## 14. Estado actual del proyecto
> Claude Code: mantén esta sección actualizada al final de cada sesión.

- [x] Fase 0 — setup local *(2026-07-07: estructura, requirements, .gitignore, .env.example, accounts.json con 3 cuentas de prueba; `python src/check_env.py` corre sin errores)*
- [x] Fase 1 — fetch mínimo (2-3 cuentas) *(2026-07-07: primera corrida real con clockworks/tiktok-profile-scraper OK — 30 items, 3 cuentas; esquema verificado (fans→followers, heart→likesTotal, playCount→views); normalizador con tests; primer snapshot en `data/snapshots/2026-07-07.json`. **Costo real: $0.18 de $5 tras ~2 corridas (~$0.09/corrida de 3 cuentas×10 videos)** → diario con 3 cuentas ≈ $2.7/mes cabe en free tier, pero 20 cuentas diarias ≈ $18/mes NO cabe: calibrar en Fase 5 — menos videos, cadencia cada 2 días, o actor más barato)*
- [x] Fase 2 — métricas + reporte (1 snapshot) *(2026-07-07: `metrics.py` con 8 métricas puras + 20 tests en verde; `build_report.py` genera `docs/data.json` por ventana 7/14/30d; dashboard `docs/index.html` con lenguaje visual del §7 — momentum, tiles, insights, tabla ordenable, gráficos, breakouts, alertas — verificado en navegador con 1 foto (estados vacíos) y con fotos simuladas (camino de crecimiento completo, no commiteadas))*
- [~] Fase 3 — segundo snapshot, tasas funcionando *(2026-07-07: primera foto de las 4 cuentas nuevas tomada; hubo 2 corridas el mismo día por pruebas de Actions, así que ya hay señal de velocidad de views entre horas — pero crecimiento/aceleración de verdad recién se ven con la foto de mañana, tomada sola por el cron)*
- [x] Fase 4 — desplegado en GitHub (Actions + Pages) *(2026-07-07: workflow `snapshot.yml` corre diario a las 12:00 UTC (~08:00 Chile) + lanzamiento manual; `APIFY_TOKEN` en Secrets; repo pasado a público para poder usar Pages gratis; Pages sirviendo `main` → `/docs`; dashboard en vivo en https://acabreirav.github.io/tiktok_dashboard/)*
- [ ] Fase 5 — escalado a 20-50 cuentas y calibrado
- [~] Fase 7 — mantenedor de cuentas *(2026-07-07: panel ejecutivo v2 con filtros por sector/coalición/partido/territorio, comparación de bloques (share of voice, cobertura), ficha individual y "terreno cedido" — tema claro, color=bloque político. Pendiente del mantenedor: alta/baja de cuentas sin editar el CSV a mano y validación automática de handles)*

*(2026-07-07: lista de cuentas cambiada a conyschons, diego_ibanezc, gaelyeomans, gonzalowinter — el snapshot del 2026-07-07 con las 3 cuentas de prueba queda en el histórico pero sale del reporte en cuanto exista un snapshot de las nuevas.)*

*(2026-07-08, expansión a RM completa VALIDADA: 52 legisladores, **49 cuentas activas** (Álvaro validó todos los handles a mano; solo Pascual, Barraza y Santibáñez quedan "sin cuenta"). Sector "neutro" nuevo para PDG (Jiles, Contreras/Dr. File, Parisi, T. Ramírez). MAX_CUENTAS=60. Costo: ~539 items/corrida ≈ $1.46 × 4-5 corridas/mes ≈ **$6-7/mes — SUPERA el free tier de $5**: Álvaro decidió costearlo, hay que habilitar pago en Apify (tarjeta) para que la corrida no falle a fin de mes. Decisión comercial: crecer cuanto antes en universo e Instagram — el histórico es el activo. Plan comercial en Notion: "Radar de Tracción — Plan comercial". Primera foto de las 49 cuentas tomada el 2026-07-08 vía workflow manual, sin errores. **Instagram perfil-only ARMADO** (columna `handle_instagram` en el CSV — vacía, Álvaro la llena y valida; actor `apify/instagram-profile-scraper`; snapshots en `data/snapshots/instagram/`; si IG falla no tumba la corrida TikTok; ficha del dashboard muestra ambas redes). El esquema real del actor IG se verifica en la primera corrida con handles (regla §6).)*

*(2026-07-07, giro de alcance: el proyecto monitorea legisladores chilenos en TikTok. `config/legisladores.csv` es la fuente de verdad — 24 legisladores de D10/D11/D13 + senadores RM, período 2026-2030, con partido/coalición/sector/territorio, handle validado a mano por Álvaro y flag `scrape`. "sin cuenta" es dato válido (ausencia de TikTok = señal). `accounts.json` eliminado; fetch lee el CSV (23 cuentas activas, tope 30); diego_ibanezc (D6) fuera de esta iteración. Cadencia pasada a SEMANAL (lunes 12:00 UTC): ~$0.70/corrida × 4/mes ≈ $3/mes, cabe en free tier. La metadata política ya viaja en docs/data.json (campo `legislador`); filtros del dashboard pendientes para Fase 7.)*
