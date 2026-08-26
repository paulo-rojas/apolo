# apolov2 NLU

apolov2 ahora separa la interpretacion de lenguaje natural de la ejecucion de herramientas.

Flujo actual:

```text
transcript -> wake/session -> InputNormalizer -> DeterministicIntentResolver -> RouteResult -> MCP/local/Codex
```

## Componentes

- `voice.interpretation.InterpretedCommand`: DTO interno con `raw_text`, `normalized_text`, `intent`, `entities`, `confidence`, `needs_reasoning`, `needs_memory` y `source`.
- `SemanticNode`: arbol semantico ligero. Primero se construye una estructura como `play_music -> media_query -> artist/platform`, y luego se derivan `entities`.
- `InputNormalizer`: limpia muletillas, repeticiones simples y autocorrecciones como `abre... no, abre Firefox` de forma conservadora.
- `IntentRegistry`: declara intents, entidades y handler asociado. Agregar intents nuevos no requiere cambiar el DTO.
- `DeterministicIntentResolver`: nivel 1 de baja latencia para aliases, patrones y extraccion simple.
- `LocalModelIntentResolver`: interfaz para un modelo local ligero futuro.
- `ReasoningProvider`: interfaz para Codex u otro modelo avanzado.
- `ConversationContext`: memoria temporal con TTL, guardada aparte de la memoria persistente.
- `voice.providers`: contratos ligeros para STT, VAD, intents, memoria, reasoning y musica.

## Memoria

El NLU no persiste frases fallidas. Solo marca `memory_action: store` cuando la instruccion expresa memoria semanticamente, por ejemplo `recuerda que ...`.

Aliases generales como `pon`, `ponme` o `quiero escuchar` viven en reglas locales, no en memoria persistente. Un alias personalizado deberia persistirse solo si el usuario lo ensena explicitamente.

## Confianza

Los puntajes son heuristicos, no probabilidades reales. Los umbrales viven en `config/apolo.json`:

```json
{
  "nlu": {
    "execute_confidence": 0.85,
    "retry_confidence": 0.60,
    "context_ttl_seconds": 180
  }
}
```

## Compatibilidad

`voice.command_router` funciona como adaptador: conserva rutas existentes hacia `youtube_music.*`, `web.*`, `system.*`, `local`, `memory` y `codex`, pero cada respuesta incluye `interpretation` para observabilidad y migracion gradual.

La frontera de ejecucion esta protegida por `core.tool_contract.validate_structured_tool_args`: ninguna herramienta debe recibir `raw_text`, `normalized_text`, `transcript`, `command` ni strings que parezcan una frase de voz cruda. La regla de arquitectura es: natural language in, structured semantics out.

Los comandos simples como `sube el volumen` y `sube el volumen a 50` se resuelven a `system.set_volume` sin Codex. Si el backend exacto de volumen no esta disponible, falla como herramienta local en vez de escalar a razonamiento.

Para control generico del navegador, `browser.smart_click` lee `dom_snapshot`, compara el nombre pedido con `text`, `aria-label`, `placeholder` y `href` de elementos visibles, y hace clic en el mejor candidato. Esto permite comandos como `dale clic al boton de reproducir`, `boton reproducir` o, dentro de una sesion activa, nombres comunes como `enviar`.

En musica, las preposiciones tienen valor semantico: `de Linkin Park` se interpreta como `artist`, y `en YouTube` como `platform`. Por eso `pon Numb de Linkin Park en YouTube` produce entidades separadas en vez de una sola cadena de busqueda.

Ejemplo de arbol:

```json
{
  "role": "play_music",
  "text": "numb de linkin park",
  "children": [
    {
      "role": "media_query",
      "children": [
        {"role": "query", "text": "numb"},
        {"role": "artist", "text": "linkin park"}
      ]
    },
    {"role": "platform", "text": "youtube"}
  ]
}
```
