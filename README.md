# NovelTranslator

Aplicación Python modular para adquirir novelas web, conservar el original, analizarlas, traducirlas de inglés a español y exportarlas. El proyecto está en:

`C:\Users\Usuario\Desktop\Programación\NovelTranslator`

## Estado actual

Sprint 0 a Sprint 6 están completados: arquitectura modular, persistencia, acceso, fuente, procesamiento y traducción incremental. No implementa todavía modelos pesados, descarga paralela, SQLite ni exportación EPUB funcional.

## Arquitectura

El núcleo (`core`) contiene modelos, enums, excepciones e interfaces independientes de cualquier sitio web. Las fuentes se incorporan mediante adaptadores registrados en `sources.SourceRegistry`. Las capas `access`, `analysis`, `processing`, `translators`, `storage` y `exporters` están separadas para permitir implementaciones futuras intercambiables.

## Persistencia de Sprint 1

Cada novela se almacena en `data/novels/<novel-id>/`, usando un slug seguro derivado del identificador o título. Se guardan `metadata.json`, `glossary.json`, `translation_memory.json` y, cuando existe progreso, `progress.json`.

Cada capítulo vive en un directorio numérico (`001`, `002`, …; los capítulos de cuatro cifras conservan las cuatro cifras) y separa `source.json`, `analysis.json` y `translations/<translation-id>/chunk_NNN.json`.

El original nunca se mezcla con traducciones. Las escrituras JSON son atómicas mediante archivo temporal y `os.replace`; la lectura usa UTF-8 y `ensure_ascii=false`. Un JSON dañado produce `CorruptedDataError`. La capa expone comprobaciones de existencia para idempotencia, y `inspect_novel_state()` reconstruye el estado observable desde disco aunque falte `progress.json`.

`ProgressManager` guarda cada transición relevante: inicio, capítulo, etapa, chunk, pausa, fallo o finalización. `ResumeService` detecta novelas incompletas sin ejecutar scraping ni traducción.

Ejemplo:

```text
data/novels/example-novel/
├── metadata.json
├── glossary.json
├── translation_memory.json
├── progress.json
└── chapters/001/
    ├── metadata.json
    ├── source.json
    ├── analysis.json
    └── translations/default/chunk_001.json
```

## Instalación

Requiere Python 3.12+.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Dependencias iniciales: Typer, Rich, PyYAML, HTTPX, BeautifulSoup4, lxml y pytest. No se incluyen Transformers, PyTorch, Playwright ni Ollama.

## CLI

```bash
noveltranslator --help
python -m noveltranslator --help
noveltranslator source list
noveltranslator novel list
noveltranslator status NOVEL_ID
noveltranslator resume
```

`inspect` y `download` realizan adquisición controlada; `translate` ejecuta traducción incremental con `mock` u `ollama`; `export` sigue siendo un punto de entrada futuro.

`download` ya es el primer flujo operativo completo de adquisición:

```bash
noveltranslator download URL --limit 3
noveltranslator resume NOVEL_ID
noveltranslator status NOVEL_ID
```

## Download pipeline de Sprint 4

El flujo es secuencial y persistente:

```text
URL → SourceRegistry → Source → Storage → capítulo → source.json → checkpoint → siguiente capítulo
```

`DownloadService` coordina el proceso, pero no conoce HTML específico. La fuente resuelve metadata y capítulos; el repositorio registra los artefactos; `ProgressManager` escribe checkpoints antes y después de cada capítulo. `AccessManager` mantiene timeout, rate limiting y retries.

En la primera ejecución se registra la novela, se actualiza su metadata y se registran todos los capítulos. En ejecuciones posteriores se vuelven a consultar metadata/lista de capítulos para detectar publicaciones nuevas, pero un `source.json` válido se considera evidencia principal y el capítulo se salta sin otra request de capítulo. Los capítulos locales nunca se borran automáticamente.

`source.json` es válido cuando es JSON correcto, contiene una lista `paragraphs` no vacía y todos sus elementos son texto no vacío. Un archivo corrupto no se reemplaza silenciosamente: el capítulo queda `FAILED`, se registra el error y puede repararse explícitamente con `--force`.

Los estados principales son `PENDING → DOWNLOADING → DOWNLOADED`; los errores quedan en `FAILED` y `resume NOVEL_ID` vuelve a evaluar el capítulo fallido. `Ctrl+C` marca el capítulo actual como `PAUSED` y conserva el checkpoint. `resume` sin identificador solo lista tareas; `resume NOVEL_ID` ejecuta la continuación.

`--limit` cuenta únicamente capítulos pendientes descargados en esa ejecución. También existen `--from-chapter`, `--to-chapter` y `--force` para selecciones explícitas. La política predeterminada ante error es `stop`, configurable en `config/config.yaml` o mediante `config.example.yaml`.

## Processing and Analysis de Sprint 5

Los capítulos descargados se preparan localmente con este flujo:

```text
source.json → normalize → split → analyze → glossary → analysis.json
```

La normalización solo limpia espacios y párrafos vacíos; no cambia mayúsculas, puntuación, comillas, diálogos ni Unicode. El hash SHA-256 se calcula sobre el texto normalizado y permite detectar cambios reproduciblemente.

`TextSplitter` respeta límites de párrafo, usa tamaño objetivo/máximo configurable y divide párrafos excesivamente largos por oraciones antes de recurrir a cortes acotados. Los chunks se guardan en `chapters/NNN/processing/chunks.json` junto con `source_hash`, índices y límites de párrafo. Sus índices son estables para el mismo contenido/configuración.

`AnalysisService` procesa únicamente capítulos con `source.json`, guarda entidades candidatas locales (sin IA), términos encontrados y metadata en `analysis.json`, y crea candidatos en `glossary.json`. Si el hash coincide, el análisis se omite; si cambia, se recalcula y se conserva la traducción futura separada.

El `GlossaryManager` evita duplicados sin convertir la forma visible a minúsculas, permite actualizar, confirmar, rechazar y bloquear términos. Las decisiones `locked`/manuales tienen prioridad y no son reemplazadas por candidatos automáticos. `ContextBuilder` prepara el chunk actual, contexto anterior limitado, entidades y solo los términos del glosario que aparecen en ese contexto.

Comandos:

```bash
noveltranslator analyze NOVEL_ID --limit 1
noveltranslator glossary list NOVEL_ID
noveltranslator glossary show NOVEL_ID "Shadow Sovereign"
noveltranslator glossary set NOVEL_ID "Shadow Sovereign" --translation "Shadow Sovereign"
noveltranslator glossary lock NOVEL_ID "Shadow Sovereign"
```

El análisis usa los estados `ANALYZING` y `ANALYZED`, actualiza `progress.json` y puede reanudarse con `resume NOVEL_ID`. No se han añadido modelos de traducción, IA, embeddings ni dependencias pesadas.

## Access Layer de Sprint 2

Las fuentes futuras deben acceder a Internet mediante esta cadena:

```text
Source → AccessManager → HttpClient → RateLimiter + RetryPolicy → Internet
```

El cliente es síncrono porque el MVP no necesita concurrencia asíncrona y así mantiene una API sencilla. Usa `httpx.Client` con cookies y conexiones persistentes durante la ejecución; `close()` y el context manager liberan los recursos. Playwright queda reservado para una futura implementación de `BrowserClient`.

`AccessConfig` permite configurar timeouts, headers explícitos, redirects, tamaño máximo de respuesta, pausas y requests por minuto. El `RateLimiter` aplica la pausa entre requests y una ventana móvil de frecuencia; acepta reloj, sleeper y randomizador inyectables para tests sin esperas reales.

`RetryPolicy` limita los intentos. Reintenta timeouts, errores de red y `429`, `502`, `503` y `504`; no reintenta normalmente `400`, `401`, `403` ni `404`. Usa backoff exponencial con máximo configurable y respeta `Retry-After` en segundos o fecha HTTP, limitado por `max_retry_after_seconds`.

`AccessStatus` clasifica respuestas HTTP y heurísticas conservadoras para CAPTCHA, login requerido y JavaScript requerido. Estas señales solo se detectan y reportan: no existe bypass ni evasión. `AccessResponse` desacopla las fuentes de HTTPX e incluye URL final, estado, headers, tamaño, intentos y tiempo. `AccessStats` mantiene métricas básicas sin guardar cookies ni contenido completo en logs.

El diagnóstico controlado es:

```bash
noveltranslator access check https://example.com --no-delay
```

`--no-delay` solo desactiva las pausas para ese diagnóstico explícito; no cambia la configuración de producción. Los tests usan `httpx.MockTransport` y no dependen de Internet real.

## Extensiones y fuentes

Una fuente futura implementa `NovelSource` (`can_handle`, `get_novel`, `get_chapters`, `get_chapter`) y se registra con `registry.register(source)`. Después puede resolverse por URL con `registry.resolve(url)`, sin acoplar el core a un sitio concreto.

Lorenovels es la primera implementación real. Reconoce `lorenovels.com` y `www.lorenovels.com`, obtiene metadata y capítulos mediante HTTPX/`AccessManager`, y extrae capítulos individuales desde el contenedor WordPress `.entry-content.wp-block-post-content`. La fuente no guarda datos, no descarga masivamente y no intenta resolver CAPTCHA; si el acceso está bloqueado, lo reporta.

## Translation de Sprint 6

El motor de traducción procesa capítulos que ya tienen `source.json` y `processing/chunks.json`. Cada chunk se traduce secuencialmente y se guarda en `translations/<translation-id>/chunk_NNN.json`, conservando texto original, hash, traductor y modelo.

`TranslationService` construye contexto con chunks anteriores, glosario y entidades. Los términos bloqueados o marcados para preservar se protegen con placeholders resistentes a colisiones, se restauran y se validan antes de persistir. Si cambia el hash del original, el resultado deja de ser válido y se reprocesa.

El backend `mock` sirve para pruebas y desarrollo local. `ollama` es un adaptador opcional que llama a un servidor Ollama local ya instalado; NovelTranslator no instala Ollama ni descarga modelos.

```bash
noveltranslator translator list
noveltranslator translate NOVEL_ID --translator mock
noveltranslator translate NOVEL_ID --limit 1 --translation-id default
noveltranslator translation show NOVEL_ID 1 1
noveltranslator resume NOVEL_ID
```

La traducción es idempotente por hash y checkpoint: los chunks válidos existentes se omiten y una interrupción deja progreso para `resume`. `--force` permite reprocesar explícitamente.

## Roadmap

1. Sprint 0: arquitectura, modelos, interfaces, JSON y CLI base.
2. Sprint 1: persistencia filesystem + JSON, progreso, recuperación y CLI de estado.
3. Sprint 2: acceso HTTP, sesiones, detección, rate limiting y reintentos respetuosos.
4. Sprint 3: adaptador de fuente y scraping controlado.
5. Sprint 4: limpieza, análisis, entidades, glosario y memoria.
6. Sprint 5: traductores intercambiables, validación, exportación y CLI operativa.

