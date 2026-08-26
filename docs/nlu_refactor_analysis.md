# Analisis del refactor NLU

## Flujo encontrado

- Entrada de audio: `voice.local_listener` graba con `voice.microphone.record_utterance_to_wav`.
- VAD: `voice.vad.EnergyVad` decide por energia RMS.
- STT: `voice.local_listener` usa `faster-whisper` o `whisper.cpp`.
- Wake/session: `voice.gateway.VoiceGateway` quita wake word y mantiene `VoiceSession`.
- Interpretacion previa: `voice.command_router` mezclaba normalizacion, intents, extraccion y seleccion de herramienta.
- Codex: `mcp.server.handle_codex_path` era fallback para comandos abiertos o no entendidos.
- Memoria: `core.memory_files` guarda notas, correcciones, fast intents y respuestas repetitivas.
- Herramientas: `mcp.server.execute_tool` despacha a navegador, YouTube Music, apps, memoria y volumen.

## Problemas de acoplamiento

- Los handlers recibian a veces texto demasiado cercano al habla original.
- El router mezclaba aliases, intents y herramientas.
- Algunas tareas simples, como volumen, se mandaban a Codex aunque ya estaban interpretadas.
- El contexto temporal no estaba separado formalmente de la memoria persistente.
- STT y VAD no tenian un contrato comun visible.

## Arquitectura aplicada

- `voice.interpretation` contiene el DTO `InterpretedCommand`, registry de intents, normalizador conservador, resolver determinista, interfaces de modelo local y razonamiento avanzado.
- `voice.command_router` queda como adaptador entre la interpretacion y el contrato historico de rutas.
- `voice.providers` define contratos ligeros para STT, VAD, intents, reasoning, memoria y musica.
- `ConversationContext` mantiene contexto temporal con TTL en estado local, separado de la memoria persistente.
- Las herramientas reciben argumentos estructurados: musica recibe `query`, `artist` y `album` cuando existen.
- Codex queda como tercer nivel para ambiguedad, instrucciones abiertas o planificacion, no para comandos simples.

## Decisiones

- No se hizo una reescritura completa: el servidor MCP y las herramientas actuales se mantienen.
- La confianza es heuristica, no una probabilidad calibrada.
- Las variantes normales del lenguaje viven como aliases/reglas locales, no como memoria persistente.
- Los errores concretos de ASR recurrentes pueden entrar en `DEFAULT_VOICE_CORRECTIONS`, pero no se guardan automaticamente por cada fallo.
