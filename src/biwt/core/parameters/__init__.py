"""
biwt.core.parameters — cell-type template library.

Current contents
----------------
xml_defaults     : Default PhysiCell XML snippets for each config section.
cell_templates   : Named cell-type phenotype templates (PhysiCell XML strings).

Future direction
----------------
This subpackage will grow into a versioned cell-type registry / ontology,
eventually spun out into its own repo for independent version control.
Templates will be keyed by canonical cell-type names (with aliases) and
will carry hierarchical relationships (e.g. "CD8+ T cell" ⊂ "T cell").
"""
