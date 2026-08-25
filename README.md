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

OCR para recuperación visual es opcional:

```powershell
python -m pip install pillow pytesseract
```

## Configuración

El navegador Playwright acepta estas variables de entorno:

- `APOLO_BROWSER_PROFILE`: ruta del perfil persistente. Por defecto usa `~/.apolo-profile`.
- `APOLO_BROWSER_HEADLESS`: `true`/`false`, `1`/`0`, `yes`/`no`. Por defecto es `true`.
- `APOLO_BROWSER_RETRIES`: número de reintentos para acciones de navegador. Por defecto es `3`.

Ejemplo:

```powershell
$env:APOLO_BROWSER_HEADLESS = "false"
$env:APOLO_BROWSER_PROFILE = "$HOME\.apolo-profile"
$env:APOLO_BROWSER_RETRIES = "4"
```

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

## Tests

```powershell
cd C:\apolo
python -m pytest -q
```

Los tests del navegador se omiten si `playwright` no está instalado. Para ejecutarlos con navegador real, instala Chromium con `python -m playwright install chromium`.

## Música

El módulo de YouTube Music conserva `lastMusicSearch` en SQLite cuando se le pasa una instancia de `State`. Esto permite el flujo conversacional `esa_no()`: descarta el candidato actual y prueba el siguiente resultado. El modificador `la original` penaliza resultados marcados como `live`, `cover`, `remix`, `acoustic`, `karaoke`, `slowed` y variantes similares.
