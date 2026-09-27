# Development guide

NovelTranslator es un monolito modular instalado desde `src/`. El flujo principal coordina servicios de aplicación y mantiene separadas las capas de acceso, fuentes, procesamiento, memoria, traducción, validación, almacenamiento y exportación.

## Tests

```powershell
python -m pytest -q
```

Los tests son locales y usan transportes, fuentes y traductores falsos. No descargan modelos ni acceden a Internet. El test E2E principal está en `tests/integration/test_full_pipeline_sprint10.py`.

## Añadir una Source

Implementa `NovelSource` con `can_handle`, `get_novel`, `get_chapters` y `get_chapter`. La fuente debe recibir un `AccessManager` y no escribir directamente en `data/`; registra el adaptador en `sources/loader.py` o mediante una extensión local.

## Añadir un Translator

Implementa `Translator`, `id`, `model_id` y `translate(TranslationRequest)`. Devuelve `TranslationResult`, no guardes archivos desde el backend y registra el adaptador en la factoría de CLI. Los backends opcionales no deben instalar modelos durante `import`.

## Añadir un Exporter

Implementa `Exporter` con `format_id` y `export(ExportRequest, ExportBook)`, regístralo en `ExportService.default_registry()` y conserva la regla de exportación offline. Usa `ChapterAssembler`; no leas directamente chunks desde cada formato.

## Persistencia y seguridad

Las escrituras JSON pasan por `NovelRepository` y son atómicas. Los identificadores de novela, translation IDs y filenames deben permanecer dentro del directorio de datos. No escribas secretos, cookies, prompts completos ni capítulos en logs normales.
