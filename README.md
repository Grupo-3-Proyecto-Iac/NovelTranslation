# NovelTranslator

Aplicación Python modular para adquirir novelas web, conservar el original, analizarlas, traducirlas de inglés a español y exportarlas. El proyecto está en:

`C:\Users\Usuario\Desktop\Programación\NovelTranslator`

## Estado actual

Sprint 0 y Sprint 1 están completados: arquitectura modular y persistencia local. No implementa scraping, Lorenovels, Playwright, traducción, modelos de IA, SQLite ni exportación EPUB funcional.

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

Los comandos `inspect`, `download`, `translate` y `export` permanecen como puntos de entrada futuros y no realizan operaciones web o de traducción.

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

## Roadmap

1. Sprint 0: arquitectura, modelos, interfaces, JSON y CLI base.
2. Sprint 1: persistencia filesystem + JSON, progreso, recuperación y CLI de estado.
3. Sprint 2: acceso HTTP, sesiones, detección, rate limiting y reintentos respetuosos.
4. Sprint 3: adaptador de fuente y scraping controlado.
5. Sprint 4: limpieza, análisis, entidades, glosario y memoria.
6. Sprint 5: traductores intercambiables, validación, exportación y CLI operativa.

