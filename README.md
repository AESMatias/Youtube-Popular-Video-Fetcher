# Youtube Popular Video Fetcher

Sitio estático hecho con [Astro](https://astro.build) que muestra los vídeos populares de YouTube con resúmenes escritos por un agente de IA. Está publicado en https://videos.rapidmov.online.

## Cómo funciona

Antes el servidor recogía los datos, compilaba y dejaba `astro preview` corriendo con PM2 todo el día, y se llenaban la RAM y el disco. Ahora el servidor solo sirve archivos estáticos.

```
Mac (pipeline.py + agente)  ->  SQLite data/videos.db  ->  src/data/site.json (se sube al repo)
                                                               |
servidor: deploy.sh  ->  git pull + astro build  ->  nginx en Docker (~5 MB de RAM)  <-  cloudflared
```

- `pipeline.py` recoge los vídeos con la YouTube Data API y los guarda en `data/videos.db` (SQLite, no se sube al repo).
- Un agente de IA escribe los resúmenes siguiendo `agent/AGENT.md`.
- `pipeline.py export-site` genera `src/data/site.json`, que sí se sube al repo. Astro lo lee al compilar.
- En el servidor, `deploy.sh` hace pull, compila y sirve `dist/` con nginx dentro de Docker.

No hay Redis ni nada parecido. Es un trabajo por lotes una vez por semana, SQLite basta y cuando no corre no gasta RAM.

## Requisitos

- Mac: Python 3.9 o más nuevo, Node.js 22 y npm.
- Servidor: Docker con el plugin compose, Node.js 22, `git`, `curl`, `flock` (util-linux) y `cloudflared`.

## Configuración

Crea un archivo `.env` en la raíz (está en `.gitignore`):

```env
YOUTUBE_API_KEY=...
```

Ya no hace falta clave de OpenAI.

`config.json` define los idiomas y países, el top de vídeos por defecto (30) y cuántas regiones se recogen en cada ejecución.

## Flujo semanal (en el Mac)

```bash
./sync.sh pull
python3 pipeline.py collect [--top 30] [--regions-per-lang 3] [--langs es,en]
python3 pipeline.py agent-export [--limit 60]
# el agente lee agent/inbox.md y escribe agent/outbox.json siguiendo agent/AGENT.md
python3 pipeline.py agent-import
python3 pipeline.py export-site
./sync.sh push
git commit src/data/site.json -m "Update videos"
git push
```

### Dónde están los datos

- La copia oficial de `data/videos.db` está en el servidor. `./sync.sh pull` la baja y `./sync.sh push` la sube. `push` se niega si el servidor tiene una corrida más nueva que la tuya (`--force` para pasar igual).
- Cada `push` guarda la copia anterior comprimida en `/root/backups/videos-db` y deja las últimas 12.
- `/root/backup-sites.sh` sube esas copias a Google Drive cuando el remoto `gdrive` de rclone está configurado (`rclone config` en el servidor).
- `src/data/site.json` en git también es respaldo: cada semana guarda los videos y resúmenes que se publicaron.
- Para que la base no crezca: al importar resúmenes se borran las transcripciones y comentarios de esos videos, que ya no hacen falta. `python3 pipeline.py prune` hace lo mismo y además compacta la base.

Y luego en el servidor:

```bash
./deploy.sh
```

Para revisar el sitio antes de subirlo: `npm ci && npm run dev`.

### Migrar los datos viejos (una sola vez)

Si tienes el `videos_metadata.json` y la carpeta `sumarios_seo/` del sistema anterior:

```bash
python3 pipeline.py import-legacy <carpeta con videos_metadata.json y sumarios_seo/>
python3 pipeline.py export-site
```

## Tests

```bash
npm test
```

Solo usan la librería estándar de Python. La CI de GitHub (`.github/workflows/ci.yml`) compila el sitio y corre los tests con Python 3.9 y 3.12.

## Servidor

Configuración inicial, una sola vez:

1. Instala Docker y añade tu usuario al grupo `docker` (`sudo usermod -aG docker $USER`, luego cierra sesión y vuelve a entrar).
2. Clona el repo y ejecuta `./deploy.sh`. Si existe el proceso PM2 viejo `astro-server`, el script lo borra y hace `pm2 save` para liberar el puerto 50000.
3. En la configuración de `cloudflared`, la regla de ingress de `videos.rapidmov.online` tiene que apuntar a `http://127.0.0.1:50000`.
4. Quita del crontab la línea vieja de `run_data_and_deploy.sh`. Si quieres que el servidor se actualice solo, añade esta (`crontab -e`):

```
0 * * * * /ruta/al/repo/deploy.sh >> /ruta/al/repo/deploy.log 2>&1
```

Corre cada hora pero no hace nada si no hay commits nuevos. Usa `./deploy.sh --force` para recompilar igual, y `BRANCH=main ./deploy.sh` para elegir otra rama (por defecto usa la rama actual).

Lo viejo que ya se puede borrar en el servidor: `rm -rf venv script_execution.log`.

`deploy.sh` compila en `dist.new/` y solo reemplaza `dist/` si el build termina bien, así que un build roto deja la versión anterior en línea. El contenedor `videos-web` usa nginx con sistema de archivos de solo lectura, 32 MB de memoria máxima y logs limitados a 3 MB.

## El sitio muestra "error code: 502"

Significa que `cloudflared` funciona pero no puede conectar con `127.0.0.1:50000`. Si el túnel estuviera caído, Cloudflare mostraría el error 1033.

```bash
docker ps                           # ¿videos-web aparece como "Up (healthy)"?
docker logs videos-web              # errores de nginx
curl -I http://127.0.0.1:50000/     # ¿responde el origen?
sudo systemctl status cloudflared   # ¿el túnel está activo?
```

Para levantarlo otra vez: `./deploy.sh --force`, o solo `docker compose up -d` si `dist/` ya está compilado.
