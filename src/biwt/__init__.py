"""
biwt — BioInformatics WalkThrough

Core public surface:
    from biwt import BiwtInput, BiwtResult, DomainSpec

GUI (requires biwt[gui]):
    from biwt.gui import create_biwt_widget
"""

from biwt.types import DomainSpec, BiwtInput, BiwtResult

__version__ = "0.1.0"
__all__ = ["DomainSpec", "BiwtInput", "BiwtResult"]
