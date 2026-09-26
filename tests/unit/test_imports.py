def test_application_imports() -> None:
    import noveltranslator
    from noveltranslator.core import models, interfaces
    from noveltranslator.cli.commands import app

    assert noveltranslator.__version__ == "0.1.0"
    assert models and interfaces and app

