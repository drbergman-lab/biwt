"""
Cell-type phenotype template library.

Each entry in ``CELL_TEMPLATES`` maps a canonical cell-type name to a
PhysiCell XML phenotype string.  The ``default`` template is used when no
specific match is found.

Templates are stored in ``cell_templates.toml`` alongside this module.
Users can supply additional templates in their own ``.toml`` files using
the same format (each key is a template name, each value is an XML
``<phenotype>`` string).  Pass paths to ``BiwtInput.extra_cell_template_paths``.
"""

from __future__ import annotations
import importlib.resources


def load_templates_from_file(path: str) -> dict[str, str]:
    """Load a TOML template file and return ``{name: xml_string}``."""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]  # 3.9/3.10 fallback
        except ImportError as exc:
            raise ImportError(
                "Python < 3.11 requires 'tomli' to load template files. "
                "Install it with: pip install tomli"
            ) from exc
    with open(path, "rb") as f:
        return tomllib.load(f)


_builtin_path = str(
    importlib.resources.files("biwt.core.parameters").joinpath("cell_templates.toml")
)

CELL_TEMPLATES: dict[str, str] = load_templates_from_file(_builtin_path)
default_template: str = CELL_TEMPLATES.get("default", "")


def get_template(cell_type_name: str) -> str:
    """Return the XML phenotype string for *cell_type_name*.

    Falls back to ``"default"`` if no specific template exists.
    """
    return CELL_TEMPLATES.get(cell_type_name, CELL_TEMPLATES["default"])
