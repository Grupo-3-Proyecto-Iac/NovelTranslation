# NovelTranslator

NovelTranslator es una aplicación Python modular para adquirir novelas web, conservar el original, analizarlas, traducirlas de inglés a español y exportarlas. El proyecto está en:

`C:\Users\Usuario\Desktop\Programación\NovelTranslator`

## Estado actual

Este repositorio contiene Sprint 0 y Sprint 1: arquitectura y persistencia local. No implementa scraping, Lorenovels, Playwright, traducción, modelos de IA, SQLite ni exportación EPUB funcional.

## Arquitectura

El núcleo (`core`) contiene modelos, enums, excepciones e interfaces independientes de cualquier sitio web. Las fuentes se incorporan mediante adaptadores registrados en `sources.SourceRegistry`; el dominio no conoce Lorenovels ni otra fuente concreta. Las capas `access`, `analysis`, `processing`, `translators`, `storage` y `exporters` están separadas para que las implementaciones futuras puedan sustituirse.

El almacenamiento inicial usa filesystem + JSON. Los artefactos de capítulos usan directorios numéricos con padding (`001`, `002`, etc.) y `progress.json` queda preparado para reanudación e idempotencia.

## Persistencia de Sprint 1

Cada novela se almacena en `data/novels/<novel-id>/`, usando un slug seguro derivado del identificador o título. Dentro se guardan `metadata.json`, `glossary.json`, `translation_memory.json` y, cuando existe progreso, `progress.json`. Cada capítulo vive en un directorio numérico (`001`, `002`, …; los capítulos de cuatro cifras conservan las cuatro cifras) y separa `source.json`, `analysis.json` y `translations/<translation-id>/chunk_NNN.json`.

El original nunca se mezcla con traducciones. Las escrituras JSON son atómicas mediante un archivo temporal y `os.replace`; la lectura usa UTF-8, `ensure_ascii=false` y produce `CorruptedDataError` si el documento está dañado. La capa expone existencia de artefactos para permitir idempotencia y `inspect_novel_state()` reconstruye el estado observable desde disco aunque falte `progress.json`.

`ProgressManager` guarda el progreso en cada transición relevante: inicio, capítulo, etapa, chunk, pausa, fallo o finalización. `ResumeService` detecta novelas no completadas sin ejecutar scraping ni traducción.

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

## Estructura

- `src/noveltranslator/core`: dominio e interfaces.
- `src/noveltranslator/sources`: registro y adaptadores de fuentes.
- `src/noveltranslator/storage`: persistencia JSON y progreso.
- `src/noveltranslator/application`: servicios y pipeline futuro.
- `config`: configuración de ejemplo.
- `data`: datos runtime.
- `tests`: pruebas unitarias e integración futura.

## Instalación

Requiere Python 3.12+.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Las dependencias iniciales son Typer, Rich, PyYAML, HTTPX, BeautifulSoup4, lxml y pytest. No se incluyen Transformers, PyTorch, Playwright ni Ollama.

## Ejecución

```bash
noveltranslator --help
python -m noveltranslator --help
noveltranslator source list
noveltranslator novel list
noveltranslator status NOVEL_ID
noveltranslator resume
```

La CLI ya deja previstos `inspect`, `download`, `translate`, `resume`, `status` y `export`; en Sprint 0 muestran mensajes de funcionalidad pendiente.

## Extensiones y fuentes

Una fuente futura implementa `NovelSource` (`can_handle`, `get_novel`, `get_chapters`, `get_chapter`) y se registra con `registry.register(source)`. Después puede resolverse por URL con `registry.resolve(url)`. Esto permite agregar sitios sin acoplar el core.

## Roadmap

1. Sprint 0: arquitectura, modelos, interfaces, JSON y CLI base.
2. Sprint 1: acceso HTTP, sesiones, detección y rate limiting respetuoso.
3. Sprint 2: adaptador de fuente y scraping controlado.
4. Sprint 3: limpieza, análisis, entidades, glosario y memoria.
5. Sprint 4: traductores intercambiables y contexto.
6. Sprint 5: reanudación, validación, exportación y CLI operativa.

