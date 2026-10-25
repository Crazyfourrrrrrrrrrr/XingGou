"""Public XingGou identity, with existing installation settings kept compatible."""
import os

TOOL = 'XingGou'
DISPLAY_NAME = '星构工具箱'
VERSION = '0.4.0'
LEGACY_TOOLS = ('StarSceneStudio', 'StarScene Studio')


def environment(suffix, default=None):
    """Prefer XINGGOU_* while retaining STARSCENE_* installations.

    An explicitly present new variable, including an empty one, takes priority.
    Settings files and project schemas are intentionally not renamed.
    """
    key = 'XINGGOU_' + suffix
    return os.environ[key] if key in os.environ else os.environ.get('STARSCENE_' + suffix, default)
