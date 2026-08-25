VOICE_PAGE_HTML = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Apolo Voz</title>
  <style>
    :root { color-scheme: dark; font-family: Segoe UI, system-ui, sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #101114; color: #f6f7f9; }
    main { width: min(720px, calc(100vw - 40px)); }
    h1 { font-size: 32px; margin: 0 0 18px; letter-spacing: 0; }
    .panel { border: 1px solid #333844; border-radius: 8px; padding: 20px; background: #17191f; }
    button { border: 0; border-radius: 999px; padding: 14px 22px; font-weight: 700; cursor: pointer; }
    #listen { background: #f6f7f9; color: #111318; }
    #stop { background: #30343d; color: #f6f7f9; margin-left: 8px; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; min-height: 120px; background: #0b0c0f; border-radius: 8px; padding: 14px; }
    .muted { color: #a6adbb; }
  </style>
</head>
<body>
  <main>
    <h1>Apolo Voz</h1>
    <div class="panel">
      <p class="muted">Di algo como: "pon Everlong Foo Fighters la original", "esa no", "pausa" o "que suena".</p>
      <button id="listen">Escuchar</button>
      <button id="stop">Detener</button>
      <pre id="output">Listo.</pre>
    </div>
  </main>
  <script>
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const output = document.querySelector("#output");
    const listen = document.querySelector("#listen");
    const stop = document.querySelector("#stop");
    let recognition;

    async function send(text) {
      output.textContent = `Oido: ${text}\\n\\nEjecutando...`;
      const res = await fetch("/voice-command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text })
      });
      const data = await res.json();
      output.textContent = JSON.stringify(data, null, 2);
    }

    if (!SpeechRecognition) {
      output.textContent = "Este navegador no expone SpeechRecognition. Prueba con Edge o Chrome.";
    } else {
      recognition = new SpeechRecognition();
      recognition.lang = "es-ES";
      recognition.interimResults = false;
      recognition.continuous = false;

      recognition.onstart = () => output.textContent = "Escuchando...";
      recognition.onerror = (event) => output.textContent = `Error de voz: ${event.error}`;
      recognition.onresult = (event) => {
        const text = event.results[0][0].transcript;
        send(text).catch((error) => output.textContent = String(error));
      };
    }

    listen.addEventListener("click", () => recognition && recognition.start());
    stop.addEventListener("click", () => recognition && recognition.stop());
  </script>
</body>
</html>
"""
