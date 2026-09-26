class Pipeline:
    """Orquestador futuro; cada etapa deberá ser reanudable e idempotente."""

    def run(self, *args, **kwargs):
        raise NotImplementedError

