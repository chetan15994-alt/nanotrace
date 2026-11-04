from nanotrace.patchers.openai_patcher import patch_openai
from nanotrace.patchers.anthropic_patcher import patch_anthropic

def autoinstrument(tracer) -> dict[str, bool]:
    """Auto-instrument all supported libraries installed in the current Python environment."""
    return {
        "openai": patch_openai(tracer),
        "anthropic": patch_anthropic(tracer),
    }

__all__ = ["autoinstrument", "patch_openai", "patch_anthropic"]
