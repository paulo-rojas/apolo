# apolo

Apolo es un agente personal local, open source y orientado al uso diario. Este directorio (`C:\apolo` en este entorno) es la ubicación canónica del proyecto.

## Instalación

Requiere Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install fastapi uvicorn playwright pytest
python -m playwright install chromium
```

Para el listener local de voz:

```powershell
python -m pip install sounddevice numpy
```

OCR para recuperación visual es opcional:

```powershell
python -m pip install pillow pytesseract
```

## Configuración

La configuración recomendada vive en:

```text
config/apolo.json
```

Ese archivo está ignorado por Git para que puedas guardar rutas locales. Crea uno desde la plantilla:

```powershell
Copy-Item config\apolo.example.json config\apolo.json
```

Edita ahí rutas de navegador, `whisper.cpp`, modelo, timeouts, VAD y sesión de voz.
También puedes habilitar Codex CLI como cerebro bajo demanda:

```json
{
  "codex": {
    "enabled": true,
    "executable": "codex",
    "timeout_seconds": 30,
    "sandbox": "read-only",
    "approval": "never",
    "auto_execute_tools": false
  }
}
```

Con `auto_execute_tools=false`, Apolo solo devuelve la propuesta de Codex. Con `true`, ejecuta herramientas MCP permitidas cuando Codex devuelve una respuesta `{"kind":"mcp", ...}`.

Las variables de entorno siguen funcionando como override:

- `APOLO_BROWSER_PROFILE`: ruta del perfil persistente. Por defecto usa `~/.apolo-profile`.
- `APOLO_BROWSER_PROFILE_DIRECTORY`: nombre de perfil Chromium/Brave/Chrome, por ejemplo `Default` o `Profile 1`.
- `APOLO_BROWSER_CDP_ENDPOINT`: URL para conectarse a un navegador ya abierto con depuración remota, por ejemplo `http://127.0.0.1:9222`.
- `APOLO_BROWSER_HEADLESS`: `true`/`false`, `1`/`0`, `yes`/`no`. Por defecto es `true`.
- `APOLO_BROWSER_RETRIES`: número de reintentos para acciones de navegador. Por defecto es `3`.
- `APOLO_BROWSER_TIMEOUT_MS`: timeout por defecto de operaciones Playwright. Por defecto es `15000`.
- `APOLO_BROWSER_NAVIGATION_TIMEOUT_MS`: timeout de navegación. Por defecto usa `APOLO_BROWSER_TIMEOUT_MS`.
- `APOLO_BROWSER_EXECUTABLE`: ruta exacta al navegador permitido.
- `APOLO_BROWSER_EXECUTABLES_FILE`: ruta a un JSON con navegadores permitidos. Por defecto lee `config/browser_executables.json`.
- `APOLO_BROWSER_NAME`: nombre del navegador dentro del JSON.
- `APOLO_BROWSER_REQUIRE_CONFIGURED`: si es `true`, Apolo falla si no hay navegador definido por el usuario.
- `APOLO_CONFIG_FILE`: ruta alternativa al JSON principal de Apolo.

Ejemplo de overrides:

```powershell
$env:APOLO_BROWSER_HEADLESS = "false"
$env:APOLO_BROWSER_PROFILE = "$HOME\.apolo-profile"
$env:APOLO_BROWSER_PROFILE_DIRECTORY = "Default"
$env:APOLO_BROWSER_CDP_ENDPOINT = "http://127.0.0.1:9222"
$env:APOLO_BROWSER_RETRIES = "4"
$env:APOLO_BROWSER_TIMEOUT_MS = "10000"
$env:APOLO_BROWSER_NAVIGATION_TIMEOUT_MS = "12000"
$env:APOLO_BROWSER_EXECUTABLE = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$env:APOLO_BROWSER_REQUIRE_CONFIGURED = "true"
```

También puedes crear `config/browser_executables.json`:

```json
{
  "default": "chrome",
  "browsers": {
    "chrome": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "edge": "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
  }
}
```

Para nuevos cambios, prefiere `config/apolo.json`; `browser_executables.json` queda soportado por compatibilidad.

Para usar tu perfil real de Brave, usa el directorio raíz `User Data` y separa el perfil:

```json
{
  "browser": {
    "selected": "brave",
    "profile": "%LOCALAPPDATA%\\BraveSoftware\\Brave-Browser\\User Data",
    "profile_directory": "Default"
  }
}
```

Si Brave ya está abierto con ese mismo perfil, Chromium puede bloquear el arranque del perfil persistente. Cierra Brave antes de iniciar Apolo si ves errores de perfil en uso.

Si quieres controlar tu Brave real mientras permanece abierto, inicia Brave con CDP y configura el endpoint:

```powershell
Start-Process "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" -ArgumentList '--remote-debugging-port=9222','--profile-directory=Default'
```

Luego en `config/apolo.json`:

```json
{
  "browser": {
    "selected": "brave",
    "cdp_endpoint": "http://127.0.0.1:9222"
  }
}
```

Para que funcione con el perfil `Default`, Brave debe haber sido abierto con ese puerto de depuración desde el inicio. Si ya estaba abierto sin CDP, ciérralo completo y arráncalo con el comando anterior.

## Ejecutar el MCP

Desde la raíz canónica:

```powershell
cd C:\apolo
python -m uvicorn mcp.server:app --host 127.0.0.1 --port 8000
```

Llamada básica:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/call -ContentType "application/json" -Body '{"tool":"browser.open","args":{"url":"https://example.com"}}'
```

## Probar YouTube Music

Para probar con tu sesión real, usa modo visible y un perfil persistente. La primera vez abre YouTube Music e inicia sesión manualmente si hace falta.

```powershell
$env:APOLO_BROWSER_HEADLESS = "false"
$env:APOLO_BROWSER_PROFILE = "$HOME\.apolo-profile"
$env:APOLO_MUSIC_SEARCH_TIMEOUT_SECONDS = "12"
$env:APOLO_MUSIC_ACTION_TIMEOUT_SECONDS = "20"
$env:APOLO_MUSIC_VERIFY_RETRIES = "5"
$env:APOLO_MUSIC_VERIFY_DELAY_SECONDS = "0.7"
python -m uvicorn mcp.server:app --host 127.0.0.1 --port 8000
```

En otra terminal:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/call -ContentType "application/json" -Body '{"tool":"browser.open","args":{"url":"https://music.youtube.com"}}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/call -ContentType "application/json" -Body '{"tool":"youtube_music.play","args":{"query":"Everlong Foo Fighters la original"}}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/call -ContentType "application/json" -Body '{"tool":"youtube_music.get_current_track","args":{}}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/call -ContentType "application/json" -Body '{"tool":"youtube_music.esa_no","args":{}}'
```

## Probar Voz

La arquitectura local de voz es:

```text
microfono -> VAD -> whisper.cpp -> transcripcion -> Voice Gateway -> MCP/Codex
```

Apolo usa una union perezosa con el navegador: no abre ni inspecciona Brave solo para
entender una frase. Primero traduce la instruccion. Solo ejecuta acciones cuando el
router devuelve una herramienta MCP concreta, por ejemplo `youtube_music.play` o
`browser.open`.

Configura `whisper.cpp` en `config/apolo.json`:

```json
{
  "whisper": {
    "executable": "C:\\ruta\\a\\whisper-cli.exe",
    "model": "small",
    "model_path": "C:\\ruta\\a\\models\\ggml-small.bin",
    "language": "es"
  }
}
```

Modelos permitidos por variable:

```text
tiny
base
small
medium
large-v2
large-v3
large-v3-turbo
```

Arranca el MCP:

```powershell
$env:APOLO_BROWSER_HEADLESS = "false"
$env:APOLO_BROWSER_EXECUTABLE = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
python -m uvicorn mcp.server:app --host 127.0.0.1 --port 8000
```

En otra terminal, graba una instrucción, transcríbela con `whisper.cpp` y ejecútala:

```powershell
python -m voice.local_listener
```

Para probar sin ejecutar herramientas:

```powershell
python -m voice.local_listener --dry-run
```

La página `/voice` sigue disponible como interfaz de desarrollo para enviar transcripciones desde el navegador:

```text
http://127.0.0.1:8000/voice
```

Frases soportadas:

- `pon Everlong Foo Fighters la original`
- `busca Soda Stereo de musica ligera`
- `esa no`
- `pausa`
- `continua`
- `siguiente`
- `que suena`

También puedes probar el parser sin micrófono:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/voice-command -ContentType "application/json" -Body '{"text":"pon Everlong Foo Fighters la original","dry_run":true}'
```

## Tests

```powershell
cd C:\apolo
python -m pytest -q
```

Los tests del navegador se omiten si `playwright` no está instalado. Para ejecutarlos con navegador real, instala Chromium con `python -m playwright install chromium`.

## Música

El módulo de YouTube Music conserva `lastMusicSearch` en SQLite cuando se le pasa una instancia de `State`. Esto permite el flujo conversacional `esa_no()`: descarta el candidato actual y prueba el siguiente resultado. El modificador `la original` penaliza resultados marcados como `live`, `cover`, `remix`, `acoustic`, `karaoke`, `slowed` y variantes similares.
