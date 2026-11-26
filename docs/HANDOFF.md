# Estado del proyecto (para quien siga)

Última revisión: 2026-11-26. Todo está en `main`.

## Cómo está armado

1. `pipeline.py collect` baja los videos populares por idioma (`config.json`) y los guarda en `data/videos.db` (SQLite, no se sube a git).
2. `pipeline.py agent-export` deja en `agent/inbox.md` los videos nuevos sin resumen. Un agente los lee y escribe `agent/outbox.json` siguiendo `agent/AGENT.md`.
3. `pipeline.py agent-import` y `pipeline.py export-site` generan `src/data/site.json`, que sí se sube a git y es lo único que lee el sitio.
4. En el server, `./deploy.sh` hace pull, build y sirve `dist/` con nginx en Docker (`docker-compose.yml`, contenedor `videos-web`, puerto local 50000 detrás del túnel de Cloudflare).

Cada video se guarda una sola vez. Si vuelve a estar en tendencia se actualizan sus números y se vuelve a mostrar, pero no se piden de nuevo ni la transcripción ni el resumen.

## Deploy

```bash
ssh vps 'cd /root/Youtube-Popular-Video-Fetcher && ./deploy.sh'
```

`vps` es un alias en `~/.ssh/config` del notebook del dueño. La API key de YouTube va en `.env` (`YOUTUBE_API_KEY=...`), nunca en git.

## Ya hecho

- Sitio caído (502) arreglado: PM2 no volvía tras reiniciar el server. Ahora es nginx en Docker con `restart: unless-stopped`.
- Datos viejos migrados a SQLite. Los "resúmenes" de OpenAI eran todos copias de la descripción, se borraron.
- Idiomas: en, es, pt, fr, de, hi, ja, ko. Top 30 por idioma, 3 países por corrida con rotación.
- Página por idioma, sitemap, robots.txt, JSON-LD, fecha de última actualización.
- Tests del pipeline (`npm test`) y CI con build + tests.
- Interfaz como RapidMov: navbar, footer, links en descripciones, zoom de cards que no se sale de la pantalla, botones con degradé.
- Primera corrida real el 2026-11-26: 228 videos en 8 idiomas, resúmenes escritos por agentes.

## Pendiente

- YouTube bloquea transcripciones si se piden muchas seguidas (`IpBlocked`). Esas se reintentan en la próxima corrida.

- Cron en el server para `deploy.sh` (sale solo si no hay cambios).
- Respaldo de `data/videos.db`: si se pierde, se pierde el historial de videos ya vistos.
- Redirecciones para URLs viejas de títulos con tildes y para `/page/N`.
