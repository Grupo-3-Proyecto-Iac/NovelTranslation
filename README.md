# NovelTranslator

Aplicación Python modular para adquirir novelas web, conservar el original, analizarlas, traducirlas de inglés a español y exportarlas. El proyecto está en:

`C:\Users\Usuario\Desktop\Programación\NovelTranslator`

## Estado actual

Sprint 0 a Sprint 10 están completados: arquitectura modular, persistencia, acceso, fuente, procesamiento, traducción incremental, validación y exportación. El MVP mantiene fuera GUI, API web, SQLite, descarga paralela y modelos pesados obligatorios.

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

`inspect` y `download` realizan adquisición controlada; `translate`, `validate` y `export` completan el flujo local del MVP con `mock` u `ollama` opcional.

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

El backend `mock` sirve para pruebas y desarrollo local. `ollama` es opcional. También existe el backend opcional `huggingface`, cuyo modelo predeterminado es `Helsinki-NLP/opus-mt-en-es`; sus dependencias se instalan por separado con `pip install -e ".[huggingface]"` y el modelo se descarga únicamente al ejecutar una traducción real.

```bash
noveltranslator translator list
noveltranslator translate NOVEL_ID --translator mock
noveltranslator translate NOVEL_ID --translator huggingface --limit 1
noveltranslator translate NOVEL_ID --limit 1 --translation-id default
noveltranslator translation show NOVEL_ID 1 1
noveltranslator resume NOVEL_ID
```

La traducción es idempotente por hash y checkpoint: los chunks válidos existentes se omiten y una interrupción deja progreso para `resume`. `--force` permite reprocesar explícitamente.

## Translation Memory y Context Memory de Sprint 7

La memoria se guarda por novela en `translation_memory.json` y `context_memory.json`, con escritura JSON atómica y UTF-8. Las entradas de traducción conservan `chapter_number`, `chunk_index`, `source_hash` y `translation_id` para trazabilidad.

La búsqueda reutilizable es exacta o por coincidencia simple de palabras normalizadas (espacios y `casefold`); no hay embeddings ni base vectorial. Las entradas repetidas se deduplican, los cambios de traducción se marcan como `CONFLICT` y las entradas cuyo hash ya no coincide se marcan como `STALE` sin borrarlas. La prioridad prevista es `glossary locked > glossary confirmed > preferred translation memory > modelo`.

Después de completar un capítulo se genera `chapters/NNN/chapter_context.json` y se actualiza la memoria narrativa con entidades y resúmenes conservadores. El contexto enviado al traductor está limitado por configuración y solo incluye memoria relevante de capítulos anteriores, para evitar enviar toda la novela al prompt.

Comandos:

```bash
noveltranslator memory add NOVEL_ID --source "Your Highness" --translation "Su Alteza"
noveltranslator memory list NOVEL_ID
noveltranslator memory search NOVEL_ID "Your Highness"
noveltranslator context show NOVEL_ID
noveltranslator context show NOVEL_ID --chapter 1
```

La reconciliación vuelve a registrar memoria a partir de un chunk traducido válido si el proceso se interrumpió después de guardar la traducción y antes de actualizar la memoria.

## Validation de Sprint 8

La validación lee los chunks traducidos, evalúa su integridad y persiste el resultado en `chapters/NNN/validation/<translation-id>.json`. No modifica ni reescribe traducciones.

Se distinguen tres estados: `OK`, `WARNING` y `FAILED`. Se comprueban traducciones vacías, placeholders, términos locked/preserve, hash del original, metadata, chunks faltantes, ratios de longitud, Unicode inválido y posibles fragmentos de inglés sin traducir. Estas heurísticas detectan anomalías, pero no sustituyen una revisión humana de calidad literaria.

Los warnings marcan `needs_review` y permiten continuar; los fallos conservan la traducción para revisión, pero impiden considerar válido el capítulo. La configuración se encuentra en `config/config.yaml` o `config.example.yaml`.

```bash
noveltranslator validate NOVEL_ID --translation-id default
noveltranslator validation show NOVEL_ID 1
noveltranslator validation list NOVEL_ID --status warning
noveltranslator validation report NOVEL_ID
```

## Exportación de Sprint 9

La exportación es completamente offline y nunca modifica `source.json`, `analysis.json` ni los chunks de traducción. `ChapterAssembler` reconstruye cada capítulo ordenando los chunks por `chunk_index` y solo usa el `translation_id` solicitado.

Por defecto se exportan únicamente capítulos con traducción completa y validación `OK`. Los capítulos con warnings requieren `--include-warnings`; los capítulos `FAILED`, sin validación o con chunks faltantes se omiten. Los archivos se guardan en `data/novels/<novel-id>/exports/` con nombres seguros para Windows. No se sobrescriben sin `--overwrite`.

Formatos disponibles:

```bash
noveltranslator export NOVEL_ID --format txt --translation-id default
noveltranslator export NOVEL_ID --format json --translation-id default
noveltranslator export NOVEL_ID --format html --translation-id default
noveltranslator export NOVEL_ID --format epub --translation-id default
```

TXT, JSON y HTML conservan Unicode; HTML escapa el contenido como texto. EPUB se genera con la biblioteca estándar, incluye metadata, tabla de contenidos, CSS, capítulos XHTML y portada únicamente si existe localmente. No se realizan requests para obtener portadas remotas durante la exportación.

Flujo típico del MVP:

```bash
noveltranslator download URL
noveltranslator analyze NOVEL_ID
noveltranslator translate NOVEL_ID
noveltranslator validate NOVEL_ID
noveltranslator export NOVEL_ID --format epub
```

## Estado final del MVP (0.1.0)

El flujo soportado es `download -> analyze -> translate -> validate -> export`, con persistencia local, reanudación e idempotencia. Los formatos de exportación son TXT, JSON, HTML y EPUB. La suite local cubre storage, acceso, fuentes, procesamiento, traducción, memoria, validación, exportación y un pipeline E2E con mocks.

El backend real opcional es Ollama; la instalación base no descarga modelos ni navegadores. Lorenovels es la fuente real incluida actualmente. La exportación no realiza red y los warnings de validación requieren autorización explícita.

## Roadmap

1. Sprint 0: arquitectura, modelos, interfaces, JSON y CLI base.
2. Sprint 1: persistencia filesystem + JSON, progreso, recuperación y CLI de estado.
3. Sprint 2: acceso HTTP, sesiones, detección, rate limiting y reintentos respetuosos.
4. Sprint 3: adaptador de fuente y scraping controlado.
5. Sprint 4: limpieza, análisis, entidades, glosario y memoria.
6. Sprint 5: traductores intercambiables, validación, exportación y CLI operativa.

