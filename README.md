# apolov2

apolov2 es un agente personal local, open source y orientado al uso diario. Este directorio (`C:\apolo` en este entorno) es la ubicación canónica del proyecto.

## Instalación

Requiere Python 3.12. Python 3.14 todavia tiene incompatibilidades practicas
con paquetes de audio en Windows, especialmente `PyAudio` y `webrtcvad`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install fastapi uvicorn playwright pytest PySide6 kokoro-onnx soundfile sounddevice numpy faster-whisper keyboard
python -m pip install "RealtimeSTT[faster-whisper]" silero-vad
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
Por seguridad, Apolo usa un perfil de navegador aislado y solo inicia o conecta
Playwright cuando va a ejecutar una herramienta. No controla tu navegador personal
en segundo plano.

El Core HTTP/WebSocket se configura en la clave `core`. Si no defines nada,
Apolo conserva el modo local histórico:

```json
{
  "core": {
    "host": "127.0.0.1",
    "port": 8000,
    "url": "http://127.0.0.1:8000"
  }
}
```

`ApoloManager`, el servidor MCP y `voice.local_listener` leen esos valores. Esto
permite mover el Core a otro host o puerto sin cambiar lógica de negocio. También
puedes usar `APOLO_CORE_HOST`, `APOLO_CORE_PORT` y `APOLO_CORE_URL`.

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

Con `auto_execute_tools=false`, apolov2 solo devuelve la propuesta de Codex. Con `true`, ejecuta herramientas MCP permitidas cuando Codex devuelve una respuesta `{"kind":"mcp", ...}`.

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
- `APOLO_BROWSER_REQUIRE_CONFIGURED`: si es `true`, apolov2 falla si no hay navegador definido por el usuario.
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

Para usar tu perfil real de Brave, usa el directorio raíz `User Data` y separa el perfil.
Esto es opcional y permite que Apolo comparta tus cookies y pestañas:

```json
{
  "browser": {
    "selected": "brave",
    "profile": "%LOCALAPPDATA%\\BraveSoftware\\Brave-Browser\\User Data",
    "profile_directory": "Default"
  }
}
```

Si Brave ya está abierto con ese mismo perfil, Chromium puede bloquear el arranque del perfil persistente. Cierra Brave antes de iniciar apolov2 si ves errores de perfil en uso.

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

Si cambiaste `core.host` o `core.port`, usa esos mismos valores al arrancar el
servidor. La interfaz de escritorio los toma automáticamente desde
`config/apolo.json`.

## Apolo Core, Runtime y Protocol

Apolo mantiene el flujo local actual y suma una ruta distribuida opcional:

```text
microfono -> STT -> Voice Gateway -> MCP -> herramienta local

Voice Gateway -> Apolo Core -> DeviceRouter -> Apolo Runtime -> herramienta remota
```

- **Apolo Core** vive en Python. Interpreta lenguaje natural, enruta herramientas,
  usa memoria/Codex y decide si una acción se ejecuta localmente o en un Runtime.
- **Apolo Runtime** vive en `runtime/` como proyecto Rust independiente. Corre en
  un dispositivo, anuncia capabilities, valida permisos y ejecuta acciones locales
  permitidas.
- **Apolo Protocol** es JSON sobre WebSocket con `protocol_version: "0.1"`.
- **Apolo Node** es cualquier dispositivo que ejecuta Apolo Runtime.

Diagrama:

```text
                  APOLO CORE
                    Python
                      |
              Apolo Protocol
                 WebSocket
                      |
          +-----------+-----------+
          |           |           |
      Runtime      Runtime     Runtime
      Windows      Linux       Android
```

El Core expone el WebSocket `/ws/runtime` solo para Runtimes. La primera versión
espera que el Runtime envíe `device.register`, después acepta
`device.heartbeat` y correlaciona `tool.result` usando `request_id`.

Mensajes iniciales del protocolo:

```text
hello
device.register
device.registered
device.heartbeat
tool.execute
tool.result
error
```

Ejemplo de registro:

```json
{
  "protocol_version": "0.1",
  "type": "device.register",
  "request_id": "uuid",
  "device": {
    "id": "laptop-paulo",
    "name": "Laptop",
    "platform": "windows",
    "capabilities": ["system.info"]
  }
}
```

Ejemplo de ejecución remota:

```json
{
  "tool": "system.info",
  "device": "laptop-paulo",
  "args": {}
}
```

Sin `device`, `execute_tool(...)` usa exactamente el fallback local existente.

## Ejecutar Apolo Runtime

El Runtime inicial está en Rust:

```powershell
cd C:\apolo\runtime
cargo run
```

Por defecto se conecta a:

```text
ws://127.0.0.1:8000/ws/runtime
```

Para apuntarlo a otro Core:

```powershell
$env:APOLO_CORE_WS_URL = "ws://192.168.1.20:8000/ws/runtime"
cargo run
```

La primera versión implementa una whitelist explícita:

```text
system.info
system.open_app
system.close_app
```

No implementa shell arbitrario, filesystem, navegador, Playwright, mouse,
teclado, audio, micrófono ni YouTube Music. Es intencional: el Runtime no
interpreta lenguaje natural ni toma decisiones inteligentes.

## Ejecutar la interfaz de escritorio

Desde la raíz del proyecto y con el entorno virtual activado:

```powershell
python -m ui.app
```

La interfaz usa Qt Widgets, mantiene el backend separado mediante `ApoloManager` y
se minimiza a la bandeja del sistema al cerrar la ventana. El comando `Salir` del
menú de la bandeja detiene apolov2 correctamente.

La voz local usa Kokoro-82M v1.0 mediante ONNX Runtime. En Windows, los modelos
se guardan en `models/kokoro/` y la voz española se configura en `config/apolo.json`
con `kokoro.voice`: `ef_dora`, `em_alex` o `em_santa`. La configuración incluida
usa `em_alex` y el modelo de precisión completa.

El listener admite dos modos: `voice.mode: "open"` mantiene la escucha activa y
`voice.mode: "push_to_talk"` escucha solo mientras mantienes `voice.hotkey`
(`ctrl+space` por defecto). También puedes usar `--mode push_to_talk --hotkey
ctrl+space` al iniciar el listener.

Para conversación interactiva, el backend configurado es `faster-whisper` con el
modelo `medium` en CUDA y `float16`. El modelo se precarga al arrancar el listener:
la primera vez puede descargarlo desde Hugging Face, pero después evita la espera
de carga al terminar cada frase. El VAD usa bloques cortos y pre-roll para no perder
el inicio de comandos breves; en `push_to_talk`, la grabación empieza en cuanto
presionas la tecla.

El acceso directo de Windows usa el icono propio `assets/apolo.ico` y ejecuta la
interfaz con el Python del entorno virtual, sin abrir una consola.

apolov2 usa un bloqueo único de instancia en `ui.app`: si se abre el icono mientras
ya existe una interfaz activa, el segundo lanzamiento termina sin crear otra
ventana, otro backend ni otro monitor de micrófono.

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

La arquitectura local de voz recomendada es:

```text
microfono -> RealtimeSTT/WebRTC+Silero VAD -> faster-whisper -> Voice Gateway -> MCP/Codex
```

apolov2 usa una union perezosa con el navegador: no abre ni inspecciona Brave solo para
entender una frase. Primero traduce la instruccion. Solo ejecuta acciones cuando el
router devuelve una herramienta MCP concreta, por ejemplo `youtube_music.play` o
`browser.open`.

Configura `RealtimeSTT` en `config/apolo.json`. El listener lo ejecuta en un proceso
trabajador con timeout y vuelve a `faster-whisper` si falla, para evitar que Apolo se
quede bloqueado esperando audio o modelos:

```json
{
  "whisper": {
    "backend": "realtime-stt",
    "model": "small",
    "device": "cuda",
    "compute_type": "float16",
    "language": "es"
  },
  "realtime_stt": {
    "fallback_backend": "faster-whisper",
    "timeout_seconds": 25,
    "webrtc_sensitivity": 2,
    "silero_sensitivity": 0.45
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

Los tests nuevos cubren registro de dispositivos, actualización de capabilities,
desconexión, validación de protocolo, mensajes inválidos, capability inexistente,
correlación de `request_id`, fallback local, selección explícita de Runtime y
desconexión durante ejecución.

Para validar el Runtime Rust necesitas tener instalado el toolchain de Rust:

```powershell
cd C:\apolo\runtime
cargo fmt --check
cargo test
```

## Música

El módulo de YouTube Music conserva `lastMusicSearch` en SQLite cuando se le pasa una instancia de `State`. Esto permite el flujo conversacional `esa_no()`: descarta el candidato actual y prueba el siguiente resultado. El modificador `la original` penaliza resultados marcados como `live`, `cover`, `remix`, `acoustic`, `karaoke`, `slowed` y variantes similares.
