"""Step: assign each final cell type a cell-parameter template, or none."""

from __future__ import annotations
import os
from collections import Counter
from typing import Optional

from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFileDialog, QInputDialog,
    QScrollArea, QWidget, QMessageBox, QPushButton, QToolButton,
    QButtonGroup, QRadioButton, QComboBox,
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QStandardItem, QStandardItemModel, QColor

from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow
from biwt.gui.widgets import (
    GoBackButton, ContinueButton, ROW_LABEL_MAX_WIDTH, RelabelledComboBox,
    action_icon, dropped_local_paths, row_arrow, row_label,
)
from biwt.core import templates as core_templates
from biwt.core.cell_types import alpha_key
from biwt.types import HOST_SOURCE

# Model payload for the "(none)" row.  Deliberately not ``None``: that already
# means "no information" (a section header, or a combo mid-rebuild), and an
# explicit "leave this type unassigned" must stay distinguishable from it.
class _NoTemplate:
    def __repr__(self) -> str:            # pragma: no cover - debugging aid
        return "(none)"


_NO_TEMPLATE = _NoTemplate()
_NO_TEMPLATE_LABEL = "(none)"

# Each action exists twice — once per cell type, once for all of them — and the
# glyph is what ties the two together, so it is defined in one place.
#
# Each action exists at two scopes and carries the same icon at both, so the
# pairing between a row button and its "Set all" counterpart is visible.
#
# Icons rather than text glyphs: a glyph is drawn by whatever font the host's
# fallback chain provides, which made the three marks different sizes and weights
# on the same screen — a gear at 14x15 next to a reload arrow at 13x11 — and
# unpredictable inside an embedding application.  The gear itself survives that
# change: a template *is* a parameter set.  (A star was rejected for meaning, a
# house for legibility.)
_ICON_AUTO    = "auto_match"
_ICON_DEFAULT = "default_template"
_ICON_NONE    = "no_template"
# 20 px inside a 30x28 button: as large as fits with a margin, and the
# same size at both scopes so the pairing reads.
_ACTION_ICON_SIZE = QSize(20, 20)

# Per-row tooltips.  Terse on purpose: the "Set all" row directly above pairs the
# same three glyphs with words, so a row button only has to name its action, not
# re-explain it or repeat which cell type it sits beside.
_TIP_AUTO    = "Auto-match"
_TIP_DEFAULT = "Assign default"
_TIP_NONE    = f"Assign {_NO_TEMPLATE_LABEL}"

# Marker shown beside a row whose template name is not unique.  Informational
# rather than a warning: the selection is valid, there just happened to be more
# than one candidate.  Clicking dismisses it; see _refresh_row_flags.
_ICON_TIE = "ⓘ"


def _minimal_unique_suffixes(filepaths: list[str]) -> dict[str, str]:
    """Return the shortest path suffix that uniquely identifies each filepath.

    Paths are shortened to the minimal trailing suffix (basename, then
    parent/basename, etc.) that avoids collisions within this group.
    """
    if not filepaths:
        return {}

    parts = {fp: list(reversed(fp.replace("\\", "/").split("/"))) for fp in filepaths}
    max_depth = max(len(p) for p in parts.values())

    for depth in range(1, max_depth + 1):
        candidate = {fp: "/".join(reversed(ps[:depth])) for fp, ps in parts.items()}
        if max(Counter(candidate.values()).values()) == 1:
            return candidate

    return {fp: fp for fp in filepaths}      # fallback: full paths


class LoadCellParametersWindow(BiwinformaticsWalkthroughWindow):
    """Let the user assign each final cell type a parameter template, or none.

    BIWT ships no templates: they come from ``BiwtInput.cell_template_paths``
    and from files the user loads here.  Template contents are opaque — read as
    text, handed back to the host untouched.

    The host's own cell types (``BiwtInput.host_cell_type_names``) are candidates
    too, under the reserved source ``types.HOST_SOURCE``.  They match on equal
    footing with file templates and carry no content: assigning one says "the host
    already defines this type", and the host decides what that means.  They are
    labelled with the host's name, cannot be removed, and supply the ``default``
    baseline when they define one — see ``_baseline_key``.

    The set of files in play lives on the session (``template_library_paths``),
    so it survives this window being rebuilt after the user goes back and changes
    an earlier step.  Only **Remove templates from file…** takes a file out.

    The template database is keyed by ``(name, path)`` so identically named
    templates from different files coexist without overwriting each other.
    Radio buttons switch between two display modes:

    * **By Name** — all templates alphabetically.  Once two or more files are
      loaded, each entry is tagged with the shortest path suffix that names its
      source, since with several files even a unique name leaves you guessing
      which file supplied it.
    * **By Source** — templates grouped under bold section headers per file.

    Every run reaches this step, and every run can leave it empty: **Skip**
    unassigns everything, and each dropdown offers ``(none)``.  Unassigned types
    are simply absent from ``BiwtResult.cell_templates``.

    Three actions exist at both scopes, sharing a glyph so the pairing reads at a
    glance: **⟳** auto-match (by name, then ``default``, then none), **⚙** the
    ``default`` template, **∅** none.  The ``Set all`` row applies them to every
    cell type; the compact buttons beside each dropdown apply them to that type
    alone.

    Template files can be added and removed here.  Either way the types the user
    has not picked for themselves, tracked in ``_touched``, re-auto-match against
    whatever the library now holds; a row whose template was removed loses its
    pick and rejoins them.  Auto-match — at either
    scope — takes a row *out* of that set, since it then holds exactly what
    auto-matching computes.
    """

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        s = walkthrough.session

        # --- template database: (name, path) → content -----------------------
        # The library lives on the session, not on this window: it survives the
        # window being rebuilt when the user goes back and changes an earlier
        # step.  Re-reading the files each time also picks up edits on disk, and
        # drops any that have become unreadable.
        self._template_db: dict[tuple[str, str], str] = {}
        seed = (
            s.biwt_input.cell_template_paths
            if s.template_library_paths is None
            else s.template_library_paths
        )
        # dict.fromkeys dedupes while keeping order: a host that passes one path
        # twice, or twice by different spellings of the same file, would otherwise
        # list it twice — and removing it then took one entry out and left the other,
        # so the templates came back on the next rebuild.
        s.template_library_paths = list(dict.fromkeys(
            loaded for loaded in (self._load_template_file(p) for p in seed) if loaded
        ))
        # The host's own cell types are candidates too, under a reserved source
        # that is not a path.  They carry no content: assigning one says "this is
        # a type you already define", and what to do about that is the host's
        # call — see biwt.types.HOST_SOURCE.  Deduped and order-independent,
        # since a host may pass anything.
        for name in dict.fromkeys(s.biwt_input.host_cell_type_names):
            if isinstance(name, str) and name.strip():
                self._template_db[(name, HOST_SOURCE)] = ""

        # Sort mode: True = by name, False = by source
        self._sort_by_name: bool = True
        # True while the shared model is being torn down and rebuilt, when the
        # dropdowns transiently report selections nobody chose.
        self._rebuilding: bool = False

        # Shared model and dropdowns
        self._model = QStandardItemModel(self)
        self._dropdowns: list[tuple[str, QComboBox]] = []
        # Cell types whose dropdown the user has picked from, i.e. those that
        # deliberately diverge from what auto-matching would choose.  Loading a
        # further template file refreshes only the others.
        self._touched: set[str] = set()

        # --- layout -----------------------------------------------------------
        vbox = QVBoxLayout()

        # Sort radio buttons
        sort_group = QButtonGroup(self)
        by_name_rb  = QRadioButton("By Name")
        by_src_rb   = QRadioButton("By Source")
        by_name_rb.setChecked(True)
        sort_group.addButton(by_name_rb, 0)
        sort_group.addButton(by_src_rb,  1)
        sort_group.idToggled.connect(self._sort_toggled)
        hbox_sort = QHBoxLayout()
        hbox_sort.addWidget(QLabel("Sort templates:"))
        hbox_sort.addWidget(by_name_rb)
        hbox_sort.addWidget(by_src_rb)
        hbox_sort.addStretch()
        vbox.addLayout(hbox_sort)

        # Bulk actions, applied to every cell type at once.  Each carries the
        # same glyph as its per-row counterpart, so the pairing is visible.
        self._auto_btn = QPushButton(action_icon(_ICON_AUTO), "Auto-match")
        self._auto_btn.setIconSize(_ACTION_ICON_SIZE)
        self._auto_btn.setToolTip(
            "Assign each cell type the template whose name matches it, falling "
            "back to 'default' and then to (none). Overrides your picks."
        )
        self._auto_btn.clicked.connect(self._auto_match_cb)
        self._default_btn = QPushButton(action_icon(_ICON_DEFAULT), "All to default")
        self._default_btn.setIconSize(_ACTION_ICON_SIZE)
        self._default_tooltip = "Assign the template named 'default' to every cell type."
        self._default_btn.setToolTip(self._default_tooltip)
        self._default_btn.clicked.connect(self._all_default_cb)
        self._none_btn = QPushButton(action_icon(_ICON_NONE), f"All to {_NO_TEMPLATE_LABEL}")
        self._none_btn.setIconSize(_ACTION_ICON_SIZE)
        self._none_btn.setToolTip("Leave every cell type without a template.")
        self._none_btn.clicked.connect(self._all_none_cb)
        hbox_bulk = QHBoxLayout()
        hbox_bulk.addWidget(QLabel("Set all:"))
        hbox_bulk.addWidget(self._auto_btn)
        hbox_bulk.addWidget(self._default_btn)
        hbox_bulk.addWidget(self._none_btn)
        hbox_bulk.addStretch()
        vbox.addLayout(hbox_bulk)

        vbox.addWidget(QLabel("Select parameter templates for your cell types:"))

        # Scrollable cell-type → dropdown rows, each with the same three actions
        # as the "Set all" row, scoped to that one type.
        inner = QGridLayout()
        inner.setColumnStretch(3, 1)
        self._row_auto: dict[str, QToolButton] = {}
        self._row_default: dict[str, QToolButton] = {}
        self._row_flag: dict[str, QToolButton] = {}
        for row, cell_type in enumerate(s.cell_types_list_final):
            flag = QToolButton()
            flag.setText(_ICON_TIE)
            flag.setAutoRaise(True)
            flag.setFixedWidth(20)
            flag.setCursor(Qt.PointingHandCursor)
            # Dismissal is not remembered: the next refresh re-shows it if the
            # name is still shared.  A per-row "already silenced" memory would be
            # more machinery than the notice is worth.
            flag.clicked.connect(flag.hide)
            flag.hide()
            self._row_flag[cell_type] = flag
            inner.addWidget(flag, row, 0)
            inner.addWidget(row_label(cell_type), row, 1)
            inner.addWidget(row_arrow(), row, 2)
            dd = RelabelledComboBox()
            # Popup items can be short (grouped under a file header); the closed
            # box always names the source.  See RelabelledComboBox.
            dd.display_for_index = self._closed_label
            dd.setModel(self._model)
            dd.currentIndexChanged.connect(self._handle_dropdown_change)
            # activated fires only for a real user pick, unlike
            # currentIndexChanged, which also fires for every programmatic one.
            dd.activated.connect(lambda _i, ct=cell_type: self._touched.add(ct))
            self._dropdowns.append((cell_type, dd))
            inner.addWidget(dd, row, 3)

            # Pinning the buttons to the dropdown's height lets the glyphs grow
            # without the rows growing with them.
            row_height = dd.sizeHint().height()
            self._row_auto[cell_type] = self._row_action(
                inner, row, 4, _ICON_AUTO, _TIP_AUTO,
                lambda _c=False, ct=cell_type: self._auto_match_one(ct),
                height=row_height,
            )
            self._row_default[cell_type] = self._row_action(
                inner, row, 5, _ICON_DEFAULT, _TIP_DEFAULT,
                lambda _c=False, ct=cell_type: self._default_one(ct),
                height=row_height,
            )
            self._row_action(
                inner, row, 6, _ICON_NONE, _TIP_NONE,
                lambda _c=False, ct=cell_type: self._none_one(ct),
                height=row_height,
            )

        # Pack the rows at the top; without this the scroll area spreads a short
        # list of cell types over its full height.
        inner.setRowStretch(len(s.cell_types_list_final), 1)

        scroll_widget = QWidget()
        scroll_widget.setLayout(inner)
        scroll_area = QScrollArea()
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        vbox.addWidget(scroll_area)

        # Library files: add / remove.  Dropping files anywhere in this window
        # does the same as Add — an accelerator, never the only route, since a
        # streamed remote session never receives a drop at all.
        self.setAcceptDrops(True)
        add_btn = QPushButton("Add templates from file…")
        add_btn.clicked.connect(self._add_templates_cb)
        self._remove_btn = QPushButton("Remove templates from file…")
        self._remove_btn.setToolTip("Drop a loaded template file, including one the host supplied.")
        self._remove_btn.clicked.connect(self._remove_templates_cb)
        hbox_files = QHBoxLayout()
        hbox_files.addWidget(add_btn)
        hbox_files.addWidget(self._remove_btn)
        vbox.addLayout(hbox_files)
        self._drop_hint = QLabel("…or drop .toml files here")
        self._drop_hint.setAlignment(Qt.AlignCenter)
        self._drop_hint.setStyleSheet("color: #999; font-size: 11px;")
        vbox.addWidget(self._drop_hint)

        # Navigation
        skip_btn = QPushButton("Skip")
        skip_btn.setToolTip("Assign no template to any cell type and continue.")
        skip_btn.clicked.connect(self._skip_cb)
        hbox_nav = QHBoxLayout()
        hbox_nav.addWidget(GoBackButton(self, walkthrough))
        hbox_nav.addWidget(skip_btn)
        hbox_nav.addWidget(ContinueButton(self, self.process_window))
        vbox.addLayout(hbox_nav)

        self.setLayout(vbox)

        # Populate model, pre-select, publish to the session, then size to fit
        self._rebuild_model()
        self._restore_selections(self._default_keys())
        self._sync_session()
        self._refresh_action_buttons()
        self._fit_width(s)

    # ------------------------------------------------------------------
    # Template loading
    # ------------------------------------------------------------------

    def _load_template_file(self, path: str) -> Optional[str]:
        """Load *path* (TOML) into ``_template_db``; return its absolute path.

        Returns ``None`` if the file could not be read, so callers can keep it
        out of the library rather than re-warning about it on every rebuild.
        """
        # Absolute, so a relative host path is not resolved against BIWT's cwd
        # by the host later, and so re-adding the same file overwrites itself
        # rather than appearing as a second source.
        path = os.path.abspath(path)
        try:
            data = core_templates.load_templates_from_file(path)
        except Exception as exc:
            QMessageBox.warning(
                self, "Template Load Error",
                f"Could not load template file:\n{path}\n\n{exc}",
            )
            return None
        for name, content in data.items():
            self._template_db[(name, path)] = content
        return path

    def _add_templates_cb(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open template files", "",
            "TOML files (*.toml);;All files (*)",
        )
        self._add_template_files(paths)

    def _add_template_files(self, paths) -> None:
        """Load every path in *paths* into the library, then re-match once.

        One re-match at the end, not one per file: untouched cell types should
        match against the library as it finally stands, rather than being
        re-decided by each file in turn.
        """
        if not paths:
            return
        saved = self._save_selections()
        library = self.walkthrough.session.template_library_paths
        added = False
        for path in paths:
            loaded = self._load_template_file(path)
            if loaded is None:
                continue                       # unreadable: warned, and skipped
            added = True
            if loaded not in library:
                library.append(loaded)
        if added:
            self._remerge(saved)

    # ------------------------------------------------------------------
    # Drag and drop
    # ------------------------------------------------------------------

    def _set_drop_active(self, active: bool) -> None:
        self._drop_hint.setStyleSheet(
            "color: #4c9a4c; font-size: 11px; font-weight: bold;" if active
            else "color: #999; font-size: 11px;"
        )

    def dragEnterEvent(self, event) -> None:      # noqa: N802
        if dropped_local_paths(event, {".toml"}):
            self._set_drop_active(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:      # noqa: N802
        self._set_drop_active(False)

    def dropEvent(self, event) -> None:           # noqa: N802
        self._set_drop_active(False)
        # Several at once is the point here, unlike the data-file drop on the
        # landing screen: libraries accumulate rather than replace each other.
        paths = dropped_local_paths(event, {".toml"})
        if not paths:
            return
        event.acceptProposedAction()
        self._add_template_files(paths)

    def _remove_templates_cb(self) -> None:
        """Drop one loaded template file, chosen by its display label.

        Files only: the host's own cell types are not something BIWT loaded, so
        they are not something it can unload.
        """
        labels = self._source_display_names()
        by_label = {labels[fp]: fp for fp in self._library_paths()}
        if not by_label:
            return
        choice, ok = QInputDialog.getItem(
            self, "Remove templates from file",
            "Stop offering the templates from:", sorted(by_label, key=alpha_key), 0, False,
        )
        if not ok or choice not in by_label:
            return
        path = by_label[choice]

        saved = self._save_selections()
        for ct, key in list(saved.items()):
            if isinstance(key, tuple) and key[1] == path:
                # The template this row pointed at is gone.  There is no user
                # choice left to preserve, so the row re-auto-matches with the
                # others rather than silently taking some other template.
                saved[ct] = None
                self._touched.discard(ct)
        for key in [k for k in self._template_db if k[1] == path]:
            del self._template_db[key]
        paths = self.walkthrough.session.template_library_paths
        if path in paths:
            paths.remove(path)
        self._remerge(saved)

    def _remerge(self, saved: dict) -> None:
        """Rebuild after the library changed, re-auto-matching untouched types.

        A file arriving can name a better match than anything previously on
        offer, and a file leaving can take a match away — either way the types
        the user picked for themselves are decisions, not defaults to refresh.
        """
        defaults = self._default_keys()
        merged = {
            ct: saved.get(ct) if ct in self._touched else defaults.get(ct, saved.get(ct))
            for ct, _ in self._dropdowns
        }
        self._rebuild_and_restore(merged)

    # ------------------------------------------------------------------
    # Sort mode
    # ------------------------------------------------------------------

    def _sort_toggled(self, btn_id: int, checked: bool) -> None:
        if not checked:
            return
        saved = self._save_selections()
        self._sort_by_name = (btn_id == 0)
        self._rebuild_and_restore(saved)

    # ------------------------------------------------------------------
    # Model construction
    # ------------------------------------------------------------------

    def _source_paths(self) -> list[str]:
        """Every source in the database, the host's reserved one first.

        Ordering matches the matching preference, so the group that wins a tie is
        also the group listed first.
        """
        return sorted(
            {fp for _, fp in self._template_db},
            key=lambda fp: (fp != HOST_SOURCE, alpha_key(fp)),
        )

    def _library_paths(self) -> list[str]:
        """Only the real files — what *Remove templates from file…* can act on."""
        return [fp for fp in self._source_paths() if fp != HOST_SOURCE]

    def _source_display_names(self) -> dict[str, str]:
        """Short display label for each source (used in headers and qualifiers).

        The host's entries are labelled with the host's own name, so a row reads
        ``Tumor (Studio)`` rather than exposing the reserved sentinel: the
        sentinel is an API signal, not something to show a user.
        """
        labels = _minimal_unique_suffixes(self._library_paths())
        if any(fp == HOST_SOURCE for _, fp in self._template_db):
            labels[HOST_SOURCE] = self.walkthrough.session.biwt_input.host_label
        return labels

    def _build_by_name_labels(self) -> dict[tuple[str, str], str]:
        """Display label for every db entry in By Name mode.

        With a single file loaded the source is never in question, so the label is
        the bare template name.  A host entry is always qualified regardless: the
        qualifier is what says this is a cell type the host already has rather
        than a template, which is information at any count.
        """
        labels = self._source_display_names()
        qualify_files = len(self._source_paths()) > 1
        return {
            (name, fp): f"{name} ({labels[fp]})"
            if fp == HOST_SOURCE or qualify_files else name
            for name, fp in self._template_db
        }

    def _closed_label(self, index: int):
        """What a closed dropdown should read at *index*, or None for its own text.

        The template name, plus its source file as a right-aligned qualifier once
        more than one library is loaded.  Whichever sort mode built the list: the
        popup can lean on a group header for context, a closed box cannot.
        """
        if index < 0:
            return None
        item = self._model.item(index)
        key = None if item is None else item.data(Qt.UserRole)
        if not isinstance(key, tuple):
            return None                       # the (none) row, or a header
        name, path = key
        if path != HOST_SOURCE and len(self._source_paths()) < 2:
            return name
        return name, self._source_display_names()[path]

    def _rebuild_and_restore(self, saved: dict) -> None:
        """Rebuild the shared model, restore *saved*, and publish the result."""
        self._rebuilding = True
        try:
            self._rebuild_model()
            self._restore_selections(saved)
        finally:
            self._rebuilding = False
        # setCurrentIndex does not signal when the index is unchanged, so sync
        # explicitly rather than relying on the restore to have emitted.
        self._sync_session()
        self._refresh_action_buttons()

    def _row_action(self, grid, row: int, col: int, label: str,
                    tooltip: str, slot, height: int = 0) -> QToolButton:
        """Add a compact per-row action button at *(row, col)* and return it.

        *height* pins the button to the row's dropdown, so the glyph can be set
        large enough to read without the row growing to accommodate it.
        """
        btn = QToolButton()
        btn.setIcon(action_icon(label))
        btn.setIconSize(_ACTION_ICON_SIZE)
        btn.setToolTip(tooltip)
        btn.setAutoRaise(True)
        btn.setFixedWidth(30)
        if height:
            btn.setFixedHeight(height)
        # Set on the button itself, which outranks both the window rule and any
        # palette the host installed: whether this action is available is
        # information, and it has to survive being embedded.
        #
        btn.setStyleSheet(
            "QToolButton { border: none; color: #333; }"
            "QToolButton:disabled { color: #c9c9c9; }"
            "QToolButton:hover:enabled { color: #000; background-color: #e6e6e6;"
            " border-radius: 3px; }"
        )
        btn.clicked.connect(slot)
        grid.addWidget(btn, row, col)
        return btn

    def _baseline_key(self) -> Optional[tuple[str, str]]:
        """The entry named ``default`` that the ``default`` actions assign.

        The host's own ``default`` wins whenever it exists: it is the host's notion
        of a baseline, which is what this action means.  It also settles the case
        that would otherwise have no answer — several libraries each defining
        ``default``, none of them *the* baseline.

        Without a host ``default``, exactly one library ``default`` is the baseline
        and two or more is ambiguous, so the action is withdrawn rather than
        resolved by path order: the user picks the one they mean from the dropdown,
        where both are labelled with their source.
        """
        host_key = (core_templates.DEFAULT_TEMPLATE_NAME, HOST_SOURCE)
        if host_key in self._template_db:
            return host_key
        library = self._library_default_keys()
        return library[0] if len(library) == 1 else None

    def _library_default_keys(self) -> list[tuple[str, str]]:
        """Templates from files named ``default`` — the host's entry excluded."""
        return [
            k for k in self._template_db
            if k[0] == core_templates.DEFAULT_TEMPLATE_NAME and k[1] != HOST_SOURCE
        ]

    def _refresh_action_buttons(self) -> None:
        """Enable each action, bulk and per-row, only where it can do something."""
        has_templates = bool(self._template_db)
        default_key = self._baseline_key()
        ambiguous = default_key is None and bool(self._library_default_keys())
        if ambiguous:
            why = ("Multiple 'default' templates found. "
                   "Manually select which template to apply.")
        elif default_key is None:
            why = "Nothing available is named 'default'."
        else:
            why = None

        self._auto_btn.setEnabled(has_templates)
        self._remove_btn.setEnabled(bool(self._library_paths()))
        self._default_btn.setEnabled(default_key is not None)
        self._default_btn.setToolTip(why or self._default_tooltip)
        for btn in self._row_auto.values():
            btn.setEnabled(has_templates)
        for btn in self._row_default.values():
            btn.setEnabled(default_key is not None)
            btn.setToolTip(why or _TIP_DEFAULT)

    def _rebuild_model(self) -> None:
        self._model.clear()
        # Row 0 in both modes: a stable restore target, a guaranteed selectable
        # row when no templates are loaded at all, and it keeps a bold section
        # header out of row 0 in By Source mode (Qt would auto-select it).
        none_item = QStandardItem(_NO_TEMPLATE_LABEL)
        none_item.setData(_NO_TEMPLATE, Qt.UserRole)
        self._model.appendRow(none_item)

        if self._sort_by_name:
            self._build_by_name_model()
        else:
            self._build_by_source_model()

    def _build_by_name_model(self) -> None:
        labels = self._build_by_name_labels()
        for key in sorted(labels, key=lambda k: (alpha_key(k[0]), alpha_key(k[1]))):
            item = QStandardItem(labels[key])
            item.setData(key, Qt.UserRole)
            self._model.appendRow(item)

    def _build_by_source_model(self) -> None:
        src_labels = self._source_display_names()

        for fp in self._source_paths():
            # Section header — enabled but not selectable
            header = QStandardItem(src_labels[fp])
            header.setFlags(Qt.ItemIsEnabled)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setBackground(QColor("#e8e8e8"))
            header.setData(None, Qt.UserRole)
            self._model.appendRow(header)

            for name, path in sorted(
                (k for k in self._template_db if k[1] == fp),
                key=lambda k: alpha_key(k[0]),
            ):
                item = QStandardItem(f" {name}")  # em-space indent
                item.setData((name, path), Qt.UserRole)
                self._model.appendRow(item)

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _current_key(self, dd: QComboBox):
        """``(name, path)``, ``_NO_TEMPLATE``, or ``None``.

        ``None`` is *no information* — index -1, which every combo transiently
        reports while the shared model is cleared, or a section header.
        ``_NO_TEMPLATE`` is the user explicitly choosing to assign nothing.
        """
        idx = dd.currentIndex()
        if idx < 0:
            return None
        item = self._model.item(idx)
        return None if item is None else item.data(Qt.UserRole)

    def _save_selections(self) -> dict:
        return {ct: self._current_key(dd) for ct, dd in self._dropdowns}

    def _restore_selections(self, saved: dict) -> None:
        for ct, dd in self._dropdowns:
            key = saved.get(ct)
            if key is None:
                continue
            for row in range(self._model.rowCount()):
                item = self._model.item(row)
                if item is not None and item.data(Qt.UserRole) == key:
                    dd.setCurrentIndex(row)
                    break

    def _first_key_for_name(self) -> dict[str, tuple[str, str]]:
        """Name → the key that wins it, so a shared name resolves the same way
        regardless of load order or display mode.

        The host's own cell type wins outright; among files, the path-sorted first
        does.  Preferring the host needs no scoring: a name is either the host's or
        it is not, so where two sources offer the same name there is exactly one
        candidate to put at the front of the list — and "your model already has
        this type" is the better answer than "here is a template for one".
        """
        out: dict[str, tuple[str, str]] = {}
        for name, path in sorted(self._template_db, key=self._preference_key):
            out.setdefault(name, (name, path))
        return out

    @staticmethod
    def _preference_key(key: tuple[str, str]):
        """Sort key ordering the database by name, then by source preference."""
        name, path = key
        return (alpha_key(name), path != HOST_SOURCE, alpha_key(path))

    def _default_keys(self) -> dict:
        """The auto-matched selection per cell type, resolved to model keys.

        A name that matched resolves through ``_first_key_for_name``, which prefers
        the host where both offer that name.  A cell type nothing matched takes the
        baseline — the same one the ``default`` actions assign, so the two controls
        cannot disagree about what ``default`` means.
        """
        s = self.walkthrough.session
        matched = core_templates.matched_candidates(
            s.cell_types_list_final or [],
            [name for name, fp in self._template_db if fp != HOST_SOURCE],
            matches=s.name_matcher,
            host_names=[name for name, fp in self._template_db if fp == HOST_SOURCE],
        )
        first_key_for = self._first_key_for_name()
        baseline = self._baseline_key() or _NO_TEMPLATE
        return {
            ct: first_key_for.get(name, _NO_TEMPLATE) if name else baseline
            for ct, name in matched.items()
        }

    # ------------------------------------------------------------------
    # Bulk actions
    # ------------------------------------------------------------------

    def _apply_selections(self, keys: dict) -> None:
        self._restore_selections(keys)
        # _restore_selections goes through setCurrentIndex, which stays silent
        # when the index is already right, so publish explicitly.
        self._sync_session()

    def _set_all(self, key) -> None:
        """Assign *key* to every cell type as a deliberate choice."""
        self._touched.update(ct for ct, _ in self._dropdowns)
        self._apply_selections({ct: key for ct, _ in self._dropdowns})

    def _auto_match_cb(self) -> None:
        # Every row now holds what auto-matching computes, so none of them
        # diverges any more: a later file load may refresh them all.
        self._touched.clear()
        self._apply_selections(self._default_keys())

    def _all_default_cb(self) -> None:
        key = self._baseline_key()
        if key is not None:
            self._set_all(key)

    def _all_none_cb(self) -> None:
        self._set_all(_NO_TEMPLATE)

    # --- the same three, scoped to one cell type ----------------------------

    def _set_one(self, cell_type: str, key) -> None:
        """Assign *key* to *cell_type* as a deliberate choice."""
        self._touched.add(cell_type)
        self._apply_selections({cell_type: key})

    def _auto_match_one(self, cell_type: str) -> None:
        # Mirrors the bulk version: this row now holds the computed value, so it
        # no longer diverges and a later file load may refresh it.
        self._touched.discard(cell_type)
        key = self._default_keys().get(cell_type, _NO_TEMPLATE)
        self._apply_selections({cell_type: key})

    def _default_one(self, cell_type: str) -> None:
        key = self._baseline_key()
        if key is not None:
            self._set_one(cell_type, key)

    def _none_one(self, cell_type: str) -> None:
        self._set_one(cell_type, _NO_TEMPLATE)

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    def _entry(self, key: tuple[str, str]) -> tuple[str, str, str]:
        """The ``BiwtResult`` triple for *key*: ``(path, name, content)``."""
        name, path = key
        return (path, name, self._template_db[key])

    def _sync_session(self) -> None:
        """Rebuild ``session.cell_templates`` from the dropdowns.

        The single write site.  Rebuilding rather than mutating means insertion
        order follows ``cell_types_list_final``, a type switched to ``(none)``
        leaves no stale entry behind, and the call is idempotent — so defaults,
        dropdown changes, Skip and Continue can all route through it.
        """
        if self._rebuilding:
            return
        entries = {}
        for ct, dd in self._dropdowns:
            key = self._current_key(dd)
            # A tuple key is a real template; None and _NO_TEMPLATE are not.
            if isinstance(key, tuple):
                entries[ct] = self._entry(key)
        self.walkthrough.session.cell_templates = entries
        self._refresh_row_flags()

    def _refresh_row_flags(self) -> None:
        """Mark each row whose template's name is not unique.

        The marker is the notice: it is visible without hovering anything, and it
        carries the text.  The dropdown deliberately has no tooltip of its own —
        two copies of one sentence is one too many.

        Two libraries can both define ``Tumor``.  Matching then has two equally
        good candidates and resolves the tie by path order, which is arbitrary
        from the user's side — so say so rather than let the choice look
        considered.  A tooltip because it costs no layout: the dropdown already
        shows *which* file won, so this only has to add that there was a contest.
        """
        labels = self._source_display_names()
        ordered = sorted(self._template_db, key=self._preference_key)
        matcher = self.walkthrough.session.name_matcher

        for cell_type, dd in self._dropdowns:
            key = self._current_key(dd)
            others = self._rival_keys(key, ordered, matcher) if isinstance(key, tuple) else []
            if others:
                # Only the part the screen does not already show: the dropdown
                # label names the source the shown candidate came from.  A rival
                # spelled differently is named, since the label does not show it.
                parts = [
                    labels[path] if name == key[0] else f"{labels[path]} (as '{name}')"
                    for name, path in others
                ]
                why = f"'{key[0]}' also defined by " + ", ".join(sorted(parts, key=alpha_key)) + "."
            else:
                why = ""
            flag = self._row_flag[cell_type]
            flag.setToolTip(why)
            flag.setVisible(bool(why))

    @staticmethod
    def _rival_keys(key, ordered, matcher) -> list:
        """Entries from other sources that name the same cell type as *key*.

        "Same" is the matching rule, not string equality, so ``tumor`` in one
        library and ``Tumor`` in another count as the one contest they are.
        """
        name, path = key
        folded = name.casefold()
        return [
            k for k in ordered
            if k[1] != path and (k[0].casefold() == folded or matcher(name, k[0]))
        ]

    def _handle_dropdown_change(self) -> None:
        self._sync_session()

    def _skip_cb(self) -> None:
        """Leave every type unassigned and move on.

        Drives the dropdowns rather than writing ``{}`` directly: this is the
        last step, so Back-then-forward can bring this very window back, and it
        must not show selections that contradict what was returned.
        """
        self._all_none_cb()
        self.process_window()

    def process_window(self) -> None:
        self._sync_session()
        self.walkthrough.session.parameters_loaded = True
        self.walkthrough.advance()

    # ------------------------------------------------------------------
    # Window sizing
    # ------------------------------------------------------------------

    def _fit_width(self, s) -> None:
        """Resize so the longest label + longest cell-type name fit without truncation."""
        fm = self.fontMetrics()
        labels = list(self._build_by_name_labels().values()) + [_NO_TEMPLATE_LABEL]
        max_dd  = max((fm.horizontalAdvance(v) for v in labels), default=200)
        max_lbl = min(ROW_LABEL_MAX_WIDTH, max(
            (fm.horizontalAdvance(ct) for ct in s.cell_types_list_final),
            default=100,
        )) if s.cell_types_list_final else 100
        # Add the marker column (~20 px), the three per-row action buttons
        # (~90 px), scrollbar (~20 px) and layout margins (~60 px)
        self.resize(max(max_dd + max_lbl + 190, 580), 600)
