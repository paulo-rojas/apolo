# apolov2 NLU

apolov2 ahora separa la interpretacion de lenguaje natural de la ejecucion de herramientas.

Flujo actual:

```text
transcript -> wake/session -> InputNormalizer -> IntentResolver -> SemanticTree -> ActionPlanner -> MCP/local/Codex
```

## Componentes

- `voice.interpretation.InterpretedCommand`: DTO interno con `raw_text`, `normalized_text`, `intent`, `entities`, `confidence`, `needs_reasoning`, `needs_memory` y `source`.
- `SemanticNode`: arbol semantico ligero para cualquier dominio. Primero se representa la intencion y sus entidades; despues se crean los argumentos de una accion.
- `InputNormalizer`: limpia muletillas, repeticiones simples y autocorrecciones como `abre... no, abre Firefox` de forma conservadora.
- `IntentRegistry`: declara intents, entidades y handler asociado. Agregar intents nuevos no requiere cambiar el DTO.
- `DeterministicIntentResolver`: nivel 1 de baja latencia para aliases, patrones y extraccion simple.
- `LocalModelIntentResolver`: interfaz para un modelo local ligero futuro.
- `ReasoningProvider`: interfaz para Codex u otro modelo avanzado.
- `ConversationContext`: memoria temporal con TTL, guardada aparte de la memoria persistente.
- `voice.command_router.ActionPlanner`: traduce intenciones registradas a un `ActionPlan` tipado usando `IntentSpec.tool_handler`. Las rutas con reglas especiales conservan adaptadores compatibles.
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

## Cerebro general

El diseño toma tres ideas de proyectos open-source con responsabilidades separadas:

- Rasa separa NLU (`intent` y `entities`) de las politicas de dialogo y conserva contexto en slots.
- Jovo separa la interpretacion de la intencion de los handlers de cada capacidad.
- DSPy usa salidas estructuradas y tipadas para que un razonador no entregue texto libre donde se espera una accion.

En Apolo esto se implementa sin imponer un framework pesado: el resolver puede ser determinista, un modelo local o Codex; todos entregan `InterpretedCommand` con `SemanticNode`. `ActionPlanner` solo acepta intenciones conocidas por `IntentRegistry`, y los handlers reciben entidades ya extraidas. Por ejemplo, una futura capacidad de correo puede registrar `send_email` con `to`, `subject` y `body`; no debe aprender a interpretar frases dentro del handler ni añadir reglas a YouTube Music.

`ConversationContext` guarda ahora `lastCommand` para todos los dominios, no solo musica. Esto permite resolver referencias como "lo mismo", "el segundo" o "cancela eso" mediante un resolver contextual posterior, siempre dentro del TTL y sin ejecutar una accion si la referencia sigue siendo ambigua.

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
