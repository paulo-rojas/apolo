# Checklist de reconocimiento de voz

Esta prueba mide primero que tan bien el reconocedor de voz transcribe lo que
dijiste, y despues verifica si Apolo interpreta bien esa transcripcion. Di cada
frase una sola vez, con tono y distancia normales. No la leas demasiado despacio
ni la repitas para corregirla.

La columna mas importante es `Detecto`: ahi copia literalmente la linea
`voice listener: heard ...`. La ruta esperada sirve para saber si el error fue de
transcripcion o de interpretacion.

## Preparacion

1. Inicia el MCP en una terminal:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn mcp.server:app --host 127.0.0.1 --port 8000
   ```

   Si aparece `WinError 10048`, no inicies otra instancia: el MCP ya está
   activo en ese puerto. Puedes verificarlo abriendo `http://127.0.0.1:8000/voice`.

2. En otra terminal inicia el listener de comandos sin ejecutar acciones y en modo continuo:

   ```powershell
   .\.venv\Scripts\python.exe -m voice.local_listener --dry-run --continuous --transcriber faster-whisper
   ```

3. Di una frase, espera la linea `voice listener: heard ...`, y recien ahi di
   la siguiente.

4. Despues de cada frase, copia la transcripcion que aparece en la linea
   `voice listener: heard ...` en la columna `Detectó`.

5. Copia tambien el JSON que imprime `--dry-run` si quieres revisar la ruta,
   intención y entidades despues de terminar la tanda.

Si el primer arranque tarda por carga de modelo, puedes darle mas margen:

```powershell
$env:APOLO_REALTIMESTT_TIMEOUT_SECONDS = "90"
.\.venv\Scripts\python.exe -m voice.local_listener --dry-run --continuous
```

Para revisar el nivel real del microfono antes de elegir un umbral:

```powershell
.\.venv\Scripts\python.exe -m voice.local_listener --diagnose --transcriber faster-whisper
```

Si todas las frases salen con `transcribing 8000ms`, el umbral esta demasiado
bajo para tu ruido de fondo. Vuelve al valor por defecto o prueba un punto medio:

```powershell
.\.venv\Scripts\python.exe -m voice.local_listener --dry-run --continuous --transcriber faster-whisper --threshold 0.012
```

## Dictado libre

Para probar parrafos largos sin wake word, sin NLU y sin sesgo hacia comandos de
Apolo:

```powershell
.\.venv\Scripts\python.exe -m voice.local_listener --dictate --continuous --transcriber realtime-stt
```

En este modo compara solo el campo `text` de la salida `{"kind":"dictation"}`.
No importa si aparece o no la palabra Apolo, porque no se usa para activar
comandos.

RealtimeSTT queda como modo experimental para comandos cortos. En este equipo
ha reconocido bien dictados largos, pero puede tardar varios segundos en cerrar
turnos breves o juntar comandos consecutivos.

## Criterio rapido

Marca `STT OK` si la transcripcion conserva la intencion y las palabras clave,
aunque cambien articulos, signos, mayusculas o acentos.

Marca `Ruta OK` si el JSON de `--dry-run` coincide con la herramienta o ruta
esperada.

Si Apolo responde con `feedback: "repeat"`, queda esperando la siguiente frase
sin exigir la palabra Apolo durante la ventana de sesión. En ese caso repite
solo la instrucción, por ejemplo `pausa` o `pon Numb de Linkin Park`.

## Frases de prueba

| ID | Di esta frase | Detectó | Ruta esperada | STT OK | Ruta OK |
| --- | --- | --- | --- | --- | --- |
| V01 | Apolo |  | Activacion de sesion, sin accion | [ ] | [ ] |
| V02 | Apolo, pausa |  | `youtube_music.pause` | [ ] | [ ] |
| V03 | Apolo, continua |  | `youtube_music.resume` | [ ] | [ ] |
| V04 | Apolo, siguiente cancion |  | `youtube_music.next` | [ ] | [ ] |
| V05 | Apolo, anterior cancion |  | `youtube_music.previous` | [ ] | [ ] |
| V06 | Apolo, que suena |  | `youtube_music.get_current_track` | [ ] | [ ] |
| V07 | Apolo, pon Numb |  | `youtube_music.play`, query `numb` | [ ] | [ ] |
| V08 | Apolo, pon Numb de Linkin Park |  | `youtube_music.play`, query `numb`, artist `linkin park` | [ ] | [ ] |
| V09 | Apolo, reproduce Everlong de Foo Fighters |  | `youtube_music.play`, query `everlong`, artist `foo fighters` | [ ] | [ ] |
| V10 | Apolo, busca hoteles en Lima en Google |  | `web.search_google`, query `hoteles en lima` | [ ] | [ ] |
| V11 | Apolo, esa no |  | `youtube_music.esa_no` | [ ] | [ ] |
| V12 | Apolo, sube el volumen |  | `system.set_volume`, direction `up` | [ ] | [ ] |
| V13 | Apolo, baja el volumen a treinta |  | `system.set_volume`, level `30` | [ ] | [ ] |
| V14 | Apolo, abre el navegador |  | `browser.ensure_cdp` | [ ] | [ ] |
| V15 | Apolo, abre Firefox |  | `web.open`, target `firefox` | [ ] | [ ] |
| V16 | Apolo, inicia Brave |  | `browser.ensure_cdp` | [ ] | [ ] |
| V17 | Apolo, recuerda que prefiero jazz |  | ruta `memory`, text `prefiero jazz` | [ ] | [ ] |
| V18 | Apolo, dime la hora actual |  | ruta `local`, command `time` | [ ] | [ ] |
| V19 | Apolo, pon pon Numb |  | normaliza repeticion y produce `youtube_music.play` | [ ] | [ ] |
| V20 | Apolo, abre, no, abre Firefox |  | conserva la correccion y produce `web.open` | [ ] | [ ] |
| V21 | Hola, por lo muchas |  | `repeat`, followup sin wake word | [ ] | [ ] |
| V22 | pausa |  | despues de V21, `youtube_music.pause` sin decir Apolo | [ ] | [ ] |

## Registro de resultado

Para cada fila marca `STT OK` y `Ruta OK` por separado:

- La columna `Detectó` conserva el significado de la frase, aunque cambien
  articulos, signos, acentos o mayusculas.
- La ruta o intencion coincide con `Ruta esperada`.

Si falla, anota el motivo debajo de la fila. Esto ayuda a saber si hay que tocar
el modelo/prompt de STT o las reglas de NLU:

```text
ID:
Detectó:
Resultado obtenido:
Fallo: [ ] activación  [ ] transcripción  [ ] intención  [ ] entidad  [ ] ejecución
Ruido o circunstancia:
```

## Comparación posterior

Cuando termines, comparte las líneas `heard` y las respuestas JSON del modo
`--dry-run`. La comparación se hará en este orden:

1. Transcripcion: diferencia entre lo dicho y lo detectado.
2. Normalizacion: repeticiones, muletillas y correcciones.
3. Intencion y entidades: ruta MCP, cancion, artista, nivel o destino.
4. Confianza y latencia: si la salida incluye esos datos.

No borres las frases fallidas: son las muestras más útiles para ajustar el
modelo, el prompt o las reglas del resolver.
