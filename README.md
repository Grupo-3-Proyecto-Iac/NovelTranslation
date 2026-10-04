# NovelTranslator

## Descripción del proyecto

NovelTranslator es una aplicación modular de Python para adquirir novelas web,
conservar su contenido original, analizarlo, traducirlo del inglés al español,
validar la integridad de los resultados y exportarlos en formatos legibles.
Está diseñada como un monolito modular: el núcleo no depende de una página web
concreta ni de un único modelo de traducción.

El proyecto separa las fuentes web, el acceso HTTP, el procesamiento de texto,
los traductores, la memoria de traducción, la validación, el almacenamiento y
la exportación. Esto permite incorporar nuevas fuentes o traductores sin
reescribir el pipeline principal.

La persistencia está basada en archivos JSON. Cada operación deja artefactos y
checkpoints en disco para que el programa pueda cerrarse y continuar después
sin repetir automáticamente el trabajo válido. La fuente Lorenovels está
incluida, pero la arquitectura permite agregar otras fuentes mediante
adaptadores.

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

Para ejecutar el flujo completo con una sola orden y ver el avance en tiempo real:

```bash
noveltranslator run "https://lorenovels.com/surviving-in-a-romance-fantasy-novel/" --limit 1 --translator mock --format epub
```

`run` encadena descarga, análisis, traducción, validación y exportación. Rich muestra la etapa actual, el capítulo, los chunks, el tiempo transcurrido y una estimación del tiempo restante cuando es posible. También puedes usar los comandos individuales: `download`, `analyze`, `translate` y `validate` muestran la misma clase de progreso.

El flujo es reanudable e idempotente. Si un capítulo ya tiene un artefacto válido, se muestra como `omitido` y se busca el siguiente pendiente. Por ejemplo, con `--limit 1`, un capítulo 001 ya descargado no consume el límite: se salta y se descarga el primer capítulo pendiente. `--force` solo debe usarse cuando quieras reprocesar explícitamente.

En `run`, la exportación final se actualiza por defecto para que repetir la orden después de descargar o traducir capítulos nuevos no falle porque ya existe el EPUB. Usa `--no-overwrite` si prefieres detenerte cuando el archivo final ya existe.

Opciones útiles de `run`:

```bash
noveltranslator run URL --limit 1 --translator huggingface --translation-id hf-opus --format epub
noveltranslator run URL --translator mock --format txt --include-warnings
noveltranslator run URL --force --overwrite
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
noveltranslator translate NOVEL_ID --translator huggingface --from-chapter 1 --to-chapter 1 --force
noveltranslator translate NOVEL_ID --limit 1 --translation-id default
noveltranslator translation show NOVEL_ID 1 1
noveltranslator resume NOVEL_ID
```

La traducción conserva los límites de párrafo del original: los párrafos se traducen individualmente y se persisten separados por una línea en blanco. Es idempotente por hash y checkpoint: los chunks válidos existentes se omiten y una interrupción deja progreso para `resume`. `--force` permite reprocesar explícitamente; `--from-chapter` y `--to-chapter` permiten corregir un rango concreto sin reprocesar toda la novela.

## Audio sincronizable

El flujo principal de NovelTranslator termina en la traducción y el EPUB. `run`
y `export` no generan audio ni lo incluyen dentro del EPUB. Para la reproducción
sincronizada, NovelReader usa el servidor WebSocket de `NovelReader/server`:
Supertonic se carga una vez en el servidor, devuelve PCM16 por segmentos y el
teléfono lo reproduce directamente en memoria con `AudioTrack`. No se guardan
WAV/MP3/OGG en el servidor ni en el teléfono.

El comando local siguiente se conserva como herramienta experimental/legacy y
sí escribe WAV en `data/`; no forma parte del flujo remoto recomendado:

El audio local se genera dentro de NovelTranslator mediante el extra opcional de Supertonic:

```powershell
python -m pip install -e ".[audio]"
```

El comando procesa las unidades de texto de forma secuencial, con un límite configurable de hilos de CPU. Guarda únicamente un WAV completo por capítulo y un `manifest.json` con el texto y los tiempos para que NovelReader pueda resaltar la unidad que se está reproduciendo. Las unidades largas se dividen en límites seguros y se añade silencio final para evitar que se corte la última sílaba:

```powershell
noveltranslator audio surviving-in-a-romance-fantasy-novel `
  --translation-id hf-opus-v3 `
  --from-chapter 0 `
  --to-chapter 0 `
  --voice M5 `
  --speed 1.40 `
  --steps 8 `
  --threads 4 `
  --max-unit-characters 900 `
  --tail-silence-seconds 0.35
```

Los archivos quedan en `data/novels/<novel-id>/chapters/NNN/audio/`. La versión actual une los textos del capítulo antes de crear las unidades, elimina repeticiones en límites de chunks y agrupa onomatopeyas aisladas con la oración vecina. La carpeta incluye la configuración de velocidad y pasos, por lo que una prueba con `--steps 6` no sobrescribe la de 8 pasos. Menos pasos aceleran la síntesis, aunque pueden reducir ligeramente la calidad. El proceso es idempotente por capítulo: si el texto traducido y la configuración no cambiaron, el capítulo se omite; `--overwrite` lo regenera explícitamente. La sincronización disponible es por unidad de texto, no por palabra.

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

## Acceso asistido opcional

El flujo HTTP normal continúa siendo el predeterminado. Si una fuente devuelve un bloqueo, puedes activar un navegador visible para completar manualmente el CAPTCHA o verificación, siempre respetando las reglas del sitio:

```powershell
pip install -e ".[browser]"
python -m playwright install chromium
$env:NOVELTRANSLATOR_ASSISTED_BROWSER = "1"
noveltranslator download "https://lorenovels.com/surviving-in-a-romance-fantasy-novel/" --from-chapter 17 --to-chapter 17 --limit 1
```

El navegador usa un perfil local en `data/sessions/browser` para conservar la sesión durante ejecuciones posteriores. NovelTranslator no resuelve ni evita CAPTCHAs automáticamente: abre el navegador, espera a que el usuario complete la verificación y reintenta una vez. Para volver al comportamiento normal, cierra la consola o ejecuta `$env:NOVELTRANSLATOR_ASSISTED_BROWSER = "0"`.

Para capturar HTML visible en una única ventana, con una pausa mínima de 15 segundos entre capítulos:

```powershell
noveltranslator capture-html `
  "https://lorenovels.com/surviving-in-a-romance-fantasy-novel/" `
  --from-chapter 19 `
  --to-chapter 25 `
  --delay-seconds 30
```

Los archivos se guardan en `data/sessions/captures/<novel-id>/`. La captura se detiene si el HTML no contiene párrafos de capítulo procesables; no intenta superar bloqueos ni automatiza CAPTCHAs.

Para incorporar capturas existentes al almacenamiento de la novela:

```powershell
noveltranslator import-html surviving-in-a-romance-fantasy-novel
```

Este comando no usa la red, crea o actualiza `source.json` y marca los capítulos como descargados. Omite los capítulos que ya tienen un `source.json`, salvo que se use `--force`.

+## Guía completa de instalación y ejecución

Esta guía está pensada para Windows y PowerShell. Los comandos de Python también
funcionan en otros sistemas con los equivalentes de activación del entorno.

### 1. Preparar el proyecto

    cd "C:\Users\Usuario\Desktop\Programación\NovelTranslator"
    py -3.12 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    python -m pip install -e ".[dev]"

Comprueba que se usa el Python correcto:

    python -c "import sys; print(sys.executable)"
    python -m noveltranslator --help
    python -m pytest -q

La prueba debe ejecutarse desde la carpeta NovelTranslator; de lo contrario,
pytest puede descubrir proyectos ajenos ubicados en la carpeta superior.

Si PowerShell bloquea la activación:

    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

### 2. Configurar NovelTranslator

El programa usa config/config.yaml. Si no existe, carga
config/config.example.yaml. Para crear la configuración local:

    Copy-Item config\config.example.yaml config\config.yaml

config/config.yaml está ignorado por Git. Puedes modificarlo sin afectar el
repositorio. Las rutas relativas, como data/novels, parten de la raíz del
proyecto.

Instalación de extras opcionales:

    python -m pip install -e ".[huggingface]"
    python -m pip install -e ".[audio]"
    python -m pip install -e ".[browser]"

- huggingface instala Transformers y PyTorch para traducir localmente en CPU.
- audio instala Supertonic, ONNX Runtime y NumPy para generar WAV.
- browser instala Playwright para el navegador asistido.
- No es necesario instalar todos los extras.

### 3. Parámetros de configuración YAML

Los cambios en config/config.yaml se aplican al iniciar el siguiente comando.

#### storage y language

| Parámetro | Ejemplo | Uso |
| --- | --- | --- |
| storage.base_directory | data/novels | Raíz del almacenamiento de novelas. |
| language.source | en | Idioma original. |
| language.target | es | Idioma de destino. |

#### access

| Parámetro | Ejemplo | Uso |
| --- | ---: | --- |
| access.concurrency | 1 | Concurrencia de acceso; mantener 1 para ser respetuoso. |
| access.timeout.connect_seconds | 10 | Tiempo máximo para conectar. |
| access.timeout.read_seconds | 30 | Tiempo máximo esperando la respuesta. |
| access.timeout.write_seconds | 30 | Tiempo máximo enviando datos. |
| access.timeout.pool_seconds | 10 | Tiempo máximo esperando conexión disponible. |
| access.delay.min_seconds | 8 | Pausa mínima entre peticiones. |
| access.delay.max_seconds | 15 | Pausa máxima aleatoria entre peticiones. |
| access.requests_per_minute | 4 | Límite de solicitudes por minuto. |
| access.follow_redirects | true | Sigue redirecciones HTTP. |
| access.max_response_size_mb | 10 | Tamaño máximo de respuesta aceptado. |
| access.headers | mapa | User-Agent, Accept y otros headers HTTP. |

No uses access.check --no-delay para descargar capítulos. Esa opción solo
sirve para un diagnóstico HTTP puntual.

#### retry

| Parámetro | Ejemplo | Uso |
| --- | ---: | --- |
| retry.max_attempts | 3 | Máximo de intentos totales. |
| retry.base_delay_seconds | 30 | Espera inicial del backoff. |
| retry.max_delay_seconds | 300 | Límite de la espera exponencial. |
| retry.backoff_factor | 2 | Multiplicador entre intentos. |
| retry.max_retry_after_seconds | 300 | Límite de Retry-After del servidor. |

Los reintentos son limitados. El sistema no evade CAPTCHA ni bloqueos HTTP.

#### download y processing.chunking

| Parámetro | Ejemplo | Uso |
| --- | ---: | --- |
| download.on_chapter_error | stop | Detiene o permite continuar tras un error. |
| download.skip_existing | true | Omite source.json válido. |
| download.refresh_metadata | true | Actualiza metadata y lista de capítulos. |
| processing.chunking.max_characters | 2200 | Máximo de caracteres por chunk. |
| processing.chunking.target_characters | 1700 | Tamaño objetivo al agrupar texto. |
| processing.chunking.overlap_paragraphs | 0 | Párrafos repetidos como contexto entre chunks. |

Un chunk mayor reduce el número de solicitudes, pero necesita más memoria y
tarda más en traducirse. target_characters no puede superar max_characters.

#### analysis.context

| Parámetro | Ejemplo | Uso |
| --- | ---: | --- |
| analysis.context.previous_chunks | 1 | Chunks anteriores enviados como contexto. |
| analysis.context.include_glossary | true | Usa términos relevantes del glosario. |
| analysis.context.include_entities | true | Incluye entidades detectadas. |

#### translation

| Parámetro | Ejemplo | Uso |
| --- | --- | --- |
| translation.provider | mock | Proveedor usado por run/resume. |
| translation.source_language | en | Idioma de entrada. |
| translation.target_language | es | Idioma de salida. |
| translation.model | qwen2.5:7b | Modelo configurado para Ollama. |
| translation.huggingface_model | Helsinki-NLP/opus-mt-en-es | Modelo HF. |
| translation.huggingface_device | cpu | Dispositivo de Hugging Face. |
| translation.context.previous_chunks | 1 | Contexto previo para traducir. |
| translation.behavior.preserve_locked_terms | true | Protege términos bloqueados. |
| translation.behavior.skip_existing | true | Omite chunks válidos existentes. |
| translation.output.translation_id | default | Identificador persistido. |
| translation.retry.max_attempts | 2 | Intentos ante fallo de traducción. |

mock sirve para pruebas y no es una traducción final. huggingface requiere el
extra correspondiente y descarga el modelo la primera vez. ollama requiere
Ollama instalado y un modelo disponible.

#### memory y validation

| Parámetro | Ejemplo | Uso |
| --- | ---: | --- |
| memory.enabled | true | Activa memoria de traducción y contexto. |
| memory.translation.max_entries_per_request | 20 | Máximo de entradas enviadas. |
| memory.translation.exact_match | true | Prioriza coincidencias exactas. |
| memory.context.previous_chapters | 2 | Capítulos anteriores considerados. |
| memory.context.max_items | 20 | Máximo de elementos narrativos. |
| memory.conflict_policy | warn | Marca conflictos para revisión. |
| validation.enabled | true | Activa validación estructural. |
| validation.auto_validate_after_translation | true | Valida tras traducir. |
| validation.length_ratio.min | 0.35 | Ratio mínimo traducción/original. |
| validation.length_ratio.max | 2.50 | Ratio máximo traducción/original. |
| validation.untranslated_detection.enabled | true | Detecta posibles restos en inglés. |
| validation.untranslated_detection.warning_threshold | 0.30 | Umbral de advertencia. |
| validation.locked_terms.missing_is_failure | true | Término protegido ausente es fallo. |

La validación comprueba integridad, hashes, chunks faltantes, placeholders,
Unicode, términos protegidos, ratios y posibles fragmentos no traducidos. No
sustituye una revisión humana de estilo.

## Flujo normal de uso

### Opción A: pipeline completo

    noveltranslator run "https://lorenovels.com/surviving-in-a-romance-fantasy-novel/" --limit 1 --translator mock --translation-id prueba --format epub

Para traducción real con Hugging Face:

    noveltranslator run "https://lorenovels.com/surviving-in-a-romance-fantasy-novel/" --translator huggingface --translation-id hf-opus-v3 --format epub

Para un rango:

    noveltranslator run "https://lorenovels.com/surviving-in-a-romance-fantasy-novel/" --from-chapter 0 --to-chapter 10 --translator huggingface --translation-id hf-opus-v3 --format epub --overwrite

run ejecuta descarga, análisis, traducción, validación y exportación. Muestra
progreso en tiempo real y omite artefactos válidos. --force reprocesa artefactos;
--overwrite reemplaza el archivo exportado.

### Opción B: etapas separadas

    noveltranslator download "https://lorenovels.com/surviving-in-a-romance-fantasy-novel/" --limit 1
    noveltranslator analyze surviving-in-a-romance-fantasy-novel --from-chapter 0 --to-chapter 0
    noveltranslator translate surviving-in-a-romance-fantasy-novel --translator huggingface --translation-id hf-opus-v3 --from-chapter 0 --to-chapter 0
    noveltranslator validate surviving-in-a-romance-fantasy-novel --translation-id hf-opus-v3 --from-chapter 0 --to-chapter 0
    noveltranslator export surviving-in-a-romance-fantasy-novel --format epub --translation-id hf-opus-v3 --from-chapter 0 --to-chapter 0 --overwrite

Esta modalidad permite revisar el glosario entre etapas.

### Reanudar y consultar estado

    noveltranslator resume
    noveltranslator resume surviving-in-a-romance-fantasy-novel --limit 1
    noveltranslator status surviving-in-a-romance-fantasy-novel

resume usa el checkpoint persistido y no inicia una nueva tarea si no hay
trabajo pendiente.

## Parámetros del comando audio

El audio local es opcional. Instala primero:

    python -m pip install -e ".[audio]"

Ejemplo completo:

    noveltranslator audio surviving-in-a-romance-fantasy-novel --translation-id hf-opus-v3 --from-chapter 0 --to-chapter 0 --voice M5 --speed 1.40 --steps 8 --pause-seconds 0.25 --tail-silence-seconds 0.35 --threads 4 --max-unit-characters 900

| Parámetro | Rango o valor predeterminado | Uso |
| --- | --- | --- |
| --translation-id | hf-opus-v3 | Traducción que se narrará. |
| --voice | M5 | Estilo de voz Supertonic. |
| --speed | 0.5–2.0; 1.40 | Velocidad de lectura. 1.0 es natural; 1.25–1.40 acelera. |
| --steps | 1–100; 8 | Pasos de síntesis. Menos suele ser más rápido, con posible pérdida de estabilidad. |
| --from-chapter | desde 0 | Primer capítulo incluido. |
| --to-chapter | desde 0 | Último capítulo incluido. |
| --pause-seconds | >= 0; 0.25 | Silencio entre unidades; usa 0 para continuidad máxima. |
| --tail-silence-seconds | >= 0; 0.35 | Silencio final para evitar cortar la última sílaba. |
| --threads | 1–16; 4 | Hilos del motor local; más hilos aumentan CPU. |
| --max-unit-characters | >= 100; 900 | Tamaño máximo de una unidad de síntesis. |
| --overwrite | desactivado | Regenera capítulos aunque el audio ya sea reutilizable. |

Para el portátil:

- Equilibrado: speed 1.25–1.40, steps 8, threads 4.
- Menor consumo: speed 1.0–1.25, steps 6, threads 2.
- Menos pausas: pause-seconds 0; conserva tail-silence-seconds 0.25–0.35.
- CPU alta: baja primero threads y luego steps.
- max-unit-characters mayor produce menos unidades, pero cada unidad tarda más.
- El comando crea un WAV y manifest.json por capítulo, no un audio por palabra.
- Usa --overwrite solo tras cambiar parámetros o si quieres regenerar.

Los archivos se guardan en:

    data/novels/<novel-id>/chapters/NNN/audio/

La sincronización disponible es por unidad de texto, no por palabra.

## Comandos de revisión y mantenimiento

    noveltranslator translator list
    noveltranslator glossary list surviving-in-a-romance-fantasy-novel
    noveltranslator glossary set surviving-in-a-romance-fantasy-novel "Cheongdo Palace" --translation "Palacio Cheongdo"
    noveltranslator glossary lock surviving-in-a-romance-fantasy-novel "Cheongdo Palace"
    noveltranslator repair-translations surviving-in-a-romance-fantasy-novel --translation-id hf-opus-v3 --dry-run
    noveltranslator validation report surviving-in-a-romance-fantasy-novel --translation-id hf-opus-v3
    noveltranslator memory search surviving-in-a-romance-fantasy-novel "Your Highness"
    noveltranslator context show surviving-in-a-romance-fantasy-novel --chapter 1

Para HTML capturado localmente:

    noveltranslator import-html surviving-in-a-romance-fantasy-novel --directory data/sessions/captures/surviving-in-a-romance-fantasy-novel

Este comando no usa la red. Después ejecuta analyze, translate y validate.

## Archivos locales y seguridad

El código, tests, README, configuración de ejemplo y plantillas sí deben estar
en Git. No subas .venv, config/config.yaml si contiene datos privados,
data/novels, data/sessions, data/cache, data/logs, modelos, EPUB, WAV ni
perfiles de navegador. Esos directorios están ignorados para evitar subir
capítulos y artefactos pesados.

Para usar el navegador asistido:

    python -m pip install -e ".[browser]"
    python -m playwright install chromium
    $env:NOVELTRANSLATOR_ASSISTED_BROWSER = "1"

El navegador visible requiere intervención manual cuando el sitio presenta un
CAPTCHA o una verificación. NovelTranslator no intenta evadirlos.

## Solución de problemas

- Comando no encontrado: activa .venv o usa python -m noveltranslator.
- Error de Transformers/PyTorch: instala el extra huggingface.
- Primera traducción lenta: el modelo se descarga y carga una vez.
- CPU alta en audio: baja --threads y después --steps.
- Capítulo omitido: ya existe un artefacto válido; usa --force explícitamente.
- Exportación sin capítulos: ejecuta validate y revisa validation report.
- Acceso bloqueado: usa captura asistida manual; no se evaden CAPTCHAs.
- Tests inesperados: ejecuta pytest desde la carpeta NovelTranslator.


## Roadmap

1. Sprint 0: arquitectura, modelos, interfaces, JSON y CLI base.
2. Sprint 1: persistencia filesystem + JSON, progreso, recuperación y CLI de estado.
3. Sprint 2: acceso HTTP, sesiones, detección, rate limiting y reintentos respetuosos.
4. Sprint 3: adaptador de fuente y scraping controlado.
5. Sprint 4: limpieza, análisis, entidades, glosario y memoria.
6. Sprint 5: traductores intercambiables, validación, exportación y CLI operativa.

