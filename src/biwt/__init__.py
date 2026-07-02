"""
biwt — BioInformatics WalkThrough

Core public surface:
    from biwt import BiwtInput, BiwtResult, DomainSpec

GUI (requires biwt[gui]):
    from biwt.gui import create_biwt_widget
"""

from importlib.metadata import PackageNotFoundError, version as _version

from biwt.types import DomainSpec, BiwtInput, BiwtResult

try:
    __version__ = _version("biwt")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["DomainSpec", "BiwtInput", "BiwtResult"]
