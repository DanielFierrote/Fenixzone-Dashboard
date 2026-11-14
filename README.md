# FZ-DB — FenixZone Dashboard

Página hecha por fans para ver en vivo los servidores de FenixZone (GTA San Andreas Multiplayer): estado, jugadores conectados, estadísticas y un asistente IA que responde dudas del servidor.

> No es una página oficial de FenixZone.

## Qué tiene

- Estado de todos los servidores (online, jugadores, ping, reinicios)
- Lista de jugadores con buscador, orden por columnas, páginas (50 / 100 / 200 / todos) y enlace al perfil de cada uno
- Estadísticas por tiempo
- Asistente IA (OpenRouter) con base de conocimiento en `conocimiento/`

## Cómo usarlo (Windows)

1. Instalá [Python 3](https://www.python.org/downloads/) y después:
   ```
   py -m pip install flask waitress
   ```
2. Copiá `claves.ejemplo.bat` como `claves.bat` y completalo (este archivo no se sube a GitHub):
   - `AI_API_KEY`: la API key de la IA (OpenRouter `sk-or-...` o Groq `gsk_...`)
   - `FZDB_CLAVE`: opcional, contraseña para entrar a la página
   - `FZDB_TOKEN`: opcional, la misma clave que usa `programa.py` en la otra PC
   - `FZDB_LUA_ARCHIVO`: opcional, ruta del archivo que lee el Lua de ServerSwitcher
3. Abrí `servidor.bat` y entrá a http://127.0.0.1:8765
4. Para compartirla con otros: instalá [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) y abrí `compartir.bat`. Te da un link `https://....trycloudflare.com`.

## Versión pública (GitHub Pages)

La página también funciona sin el servidor de Python, publicada con GitHub Pages. En ese modo lee los datos públicos de [SAMonitor](https://sam.markski.ar), que se actualizan cada pocos minutos. Funcionan los servidores, la lista de jugadores, la búsqueda y las estadísticas. El asistente IA y las sugerencias necesitan el servidor propio.

Para probar ese modo en otro lado, agregá `?publico` al final de la dirección.

## Archivos

| Archivo | Para qué es |
|---|---|
| `fzdb.html` | La página |
| `index.html` | Abre `fzdb.html` (para GitHub Pages) |
| `fzdb_server.py` | El servidor: consulta los servidores SAMP y atiende la página y el asistente |
| `programa.py` | Opcional: corre en otra PC con el juego y manda la lista completa de jugadores |
| `analizar_preguntas.py` | Resume qué le preguntan al asistente y qué respuestas votaron mal |
| `conocimiento/` | Lo que sabe el asistente (comandos, reglas, correcciones) |
