# Apolo architecture

Documento de arquitectura (fase 0) movido al directorio canónico `/apolo/`.
# apolo — Fase 0: Investigación y propuesta de arquitectura

Fecha: 2026-08-25

Resumen
-------
Documento de resultados de la Fase 0 para `apolo`: investigación de opciones open-source, justificación de dependencias, diseño de alto nivel, estrategias de sesión, manejo de YouTube Music, recuperación ante fallos y MVP propuesto.

Objetivos de esta fase
----------------------
- Evaluar herramientas open-source y estrategias para controlar Chrome/Chromium.
- Decidir arquitectura mínima y dependencias justificadas.
- Definir cómo se integrará Codex como orquestador sin depender de APIs de pago.
- Diseñar estrategias de persistencia de sesión, ranking de canciones y recuperación ante fallos.
- Entregar un `MVP` y la propuesta de estructura de repo.

1) Herramientas y proyectos a evaluar
------------------------------------

- Playwright (preferido): API madura, multi-plat, soporte nativo para roles/accessibility (`page.accessibility.snapshot()`), control de pestañas, user-data-dir (perfil persistente), buena estabilidad y comunidad activa. Soporta Python y Node.
- Puppeteer / CDP directo: alternativa válida, más centrada en Node. Buen control por CDP, pero Playwright ofrece más APIs de alto nivel (roles, espera automática, selectors con `role=`).
- open-browser-use / Browser Use (proyectos comunitarios): investigar mantenimiento y cobertura. Pueden aportar abstracciones semánticas ya hechas (find-by-role, find-by-text). Si ESTÁN bien mantenidos, reutilizar partes; si no, encapsular ideas.
- Selenium: estable pero más pesado y menos optimizado para accesibilidad moderna.
- OCR/visión (fallback): `pytesseract` o `easyocr` como opción opcional para fallback cuando no se detectan elementos por accesibilidad ni texto DOM. Requiere instalación externa (Tesseract). Dejarlo opcional.

Recomendación inicial: usar Playwright (Python) como capa de control del navegador y construir una capa semántica encima (módulo `browser/`) que exponga las operaciones requeridas.

2) Justificación de dependencias (mínimas)
-----------------------------------------
- `playwright` (open source): control robusto del navegador, accesibilidad, perfiles persistentes.
- `fastapi` + `uvicorn` (opcional): exponer una API local (MCP-like) para que Codex u otras UIs llamen a las herramientas.
- `sqlite3` (stdlib): persistencia ligera para preferencias y último contexto.
- `pytest`: pruebas unitarias.
- `pytesseract` (opcional): OCR fallback.

Razón: todas son open-source y de coste cero; limitamos librerías externas para mantener la complejidad mínima.

3) Componentes principales (propuesta)
------------------------------------

- mcp/ (adapter)
  - Exponer un endpoint local HTTP/JSON (o socket) con acciones: `browser.*`, `youtube_music.*`, `search.*`, `system.*`.
  - Contrato simple: JSON-RPC / REST con `tool`, `args`, `timeout` y respuestas tipadas.

- core/
  - `state/`: estado en memoria + persistencia ligera (SQLite) para preferencias y último contexto.
  - `policies/`: motor de políticas (confirmación para acciones sensibles, niveles de confianza).
  - `recovery/`: lógica de reintentos y categorización de errores.

- mcp/browser/ (impl)
  - Implementa capacidades semánticas: `open`, `search`, `get_state`, `find`, `find_all`, `click`, `type`, `scroll`, `scroll_until`, `back`, `forward`, `reload`, `tabs`, `screenshot`.
  - Uso preferente de árbol de accesibilidad → texto visible → labels → atributos → DOM → screenshot/OCR.

- mcp/youtube_music/
  - Abstracción para `youtube_music.search`, `play`, `pause`, `resume`, `next`, `previous`, `get_current_track`, `get_queue`.
  - Implementación inicial vía Playwright en `music.youtube.com`.

- workflows/ y tests/

4) Comunicación con Codex
-------------------------

Requisito: usar Codex como orquestador minimizando llamadas de pago.

Opciones de integración (ordenadas por seguridad/privacidad y coste):

- Opción A (recomendada inicialmente — manual/segura):
  - `apolo` expone una API local (HTTP). El usuario ejecuta Codex (ChatGPT Plus) manualmente y copia/pega JSON o llamadas a la API (o usa un pequeño Web UI que muestre la forma JSON para pegar en Codex). No requiere automatizar la cuenta de ChatGPT.

- Opción B (semi-automática — más integrada):
  - Automatizar la sesión web de ChatGPT con Playwright para que Codex (a través del chat) haga llamadas a la API local. Tiene ventajas (flujo íntegro) y riesgos (autenticación, cambios UI, seguridad). Recomendado como opcional avanzado y con consentimiento explícito.

- Opción C (API programática):
  - Si el usuario quiere usar OpenAI API, el diseño soporta un conector LLM que envía prompts y recibe instrucciones. *Pero la política de coste del usuario es evitar llamadas de pago*, así que no se diseña el sistema alrededor de esto.

Contrato MCP mínimo: cada herramienta devuelve {ok: bool, result: any, diagnostics: [...], state_delta: {...}}. El LLM (Codex) orquesta consultando herramientas y recibiendo verificación.

5) Estrategia de sesión del navegador
------------------------------------

- Perfil persistente independiente (recomendado por defecto): usar `user-data-dir` de Chromium/Chrome con una carpeta `~/.config/apolo-profile` (o en Windows un path en usuario). Ventajas: persiste cookies/sesiones, extensiones, inicio de sesión.
- Controlar el navegador del usuario directamente (usar su perfil) es posible pasando `--user-data-dir` apuntando a su perfil, pero tiene riesgos:
  - bloqueo por Chrome si instancia ya abierta
  - sobrescritura/daño accidental del perfil
  - riesgos de privacidad/seguridad

Propuesta: iniciar con perfil independiente por defecto y ofrecer una opción avanzada para reusar perfil del usuario con advertencias explícitas.

6) Resolución de ambigüedades en YouTube Music
----------------------------------------------

- Extracción de candidatos: parsear lista de resultados, extraer `title`, `artist`, `badges` (Official, Topic, etc.), duración, tipo (video/audio/playlist) y metadatos (album/mixtape).
- Features para cada candidato: `title_similarity`, `artist_similarity`, `official_badge`, `is_live`, `is_cover`, `is_remix`, `duration_match`, `uploader_trust`.
- Puntuación determinística (ejemplo):
  score = 0.45 * title_sim + 0.40 * artist_sim + 0.10 * official_bonus + 0.05 * duration_bonus - penalties

- Umbrales de confianza:
  - >= 0.85 → confianza alta → reproducir automáticamente
  - 0.6–0.85 → confianza media → reproducir y almacenar candidatos
  - < 0.6 → confianza baja → pedir confirmación mostrando N mejores candidatos

- Reglas para modificadores (original, live, cover): aplicar filtros/boosts según la instrucción (p.ej. `la original` elimina `live`, `cover`, `remix` si existen señales).

7) Verificación de reproducción y control
---------------------------------------

- Verificación post-acción: comprobar estado del player (botón `pause` visible, `aria-label` con título, metadatos en DOM). Si no concuerda, intentar siguiente candidato hasta `MAX_TRIES`.
- Guardar `lastMusicSearch` en `state/` con candidates, selectedIndex, rejected list.

8) Recuperación ante fallos (estrategia)
--------------------------------------

- Categorías de error (ejemplos): `ELEMENT_NOT_FOUND`, `MULTIPLE_MATCHES`, `PAGE_CHANGED`, `NAVIGATION_TIMEOUT`, `SESSION_EXPIRED`, `ACTION_NO_EFFECT`, `POPUP_BLOCKING`, `AMBIGUOUS_TARGET`.
- Flujo general de recuperación:
  1. Reintentar acción hasta `MAX_ACTION_RETRIES` (configurable, p.ej. 3).
  2. Re-`get_state()` y `find` con selectores alternativos.
  3. Hacer `scroll` y volver a intentar.
  4. Usar fallback por accesibilidad → texto → DOM → screenshot/OCR.
  5. Si persiste la ambigüedad, preguntar al usuario.

9) Persistencia y estado
------------------------

- Estado temporal (memoria de sesión): mantener en memoria Python para interpretar comandos consecutivos (`el segundo`, `esa no`, `baja`).
- Preferencias persistentes: SQLite para flags del usuario (`preferir_original=true`, `youtube_music_preference`).

10) Estructura de repositorio propuesta
--------------------------------------

apolo/
├── mcp/
│   ├── server.py        # adaptador HTTP/JSON (MCP-like)
│   ├── browser/         # implementación Playwright
│   └── youtube_music/
├── core/
│   ├── state.py
│   ├── policies.py
│   └── recovery.py
├── memory/
│   └── sqlite.db
├── workflows/
├── tests/
├── docs/
│   └── architecture.md
└── README.md

11) MVP (mínimo viable)
-----------------------

Funciones mínimas para lanzar `apolo` y validar la idea con coste cero:

- `browser.open(url)`, `browser.find(text)`, `browser.click(target)`, `browser.type(target,text)`, `browser.scroll(direction,amount)`, `browser.get_state()` — implementadas sobre Playwright.
- `youtube_music.search(query)` + candidate extraction + `youtube_music.play(candidate)` + verification loop y `youtube_music.pause`.
- `mcp/server.py`: endpoint local que recibe acciones y devuelve resultados.
- Estado de sesión en memoria y logs legibles.
- Tests unitarios para `rank_music_candidates` y lógica de verificación/recuperación.

12) Riesgos técnicos y mitigaciones
---------------------------------

- Riesgo: cambios frecuentes en DOM de YouTube Music.
  - Mitigación: usar accesibilidad y múltiples heurísticas; diseñar ranking tolerante; logs y tests para detectar roturas.
- Riesgo: automatizar sesión real de Chrome (privacidad/daño de perfil).
  - Mitigación: usar perfil independiente por defecto y advertencias para modo avanzado.
- Riesgo: confiar en Codex vía web (automatización de ChatGPT puede romperse).
  - Mitigación: diseñar la API local (MCP) que Codex puede invocar manualmente o mediante un conector ligero; mantener la lógica crítica en código determinista.

13) Siguientes pasos (si apruebas la arquitectura)
-------------------------------------------------

1. Crear el esqueleto del repo y un `mcp/server.py` mínimo que exponga `browser.open`.
2. Implementar `mcp/browser` con Playwright: `open`, `get_state`, `find`, `click`, `type`, `scroll` y tests de integración básicos.
3. Implementar `mcp/youtube_music` (búsqueda + ranking) y pruebas unitarias para el ranking.

Fin de Fase 0

Hecho: este documento cubre los puntos requeridos 1→10. Si estás de acuerdo con esta propuesta, procederé a la Fase 1 (implementación del navegador) y crearé los artefactos iniciales.
