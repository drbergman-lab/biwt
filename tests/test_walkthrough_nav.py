"""Navigation through the real controller: advance, go back, re-import.

The pure-Python suite evaluates step predicates on hand-built sessions, which
cannot catch an ordering bug between ``process_window``, ``advance`` and the
downstream invalidation — the reported ``KeyError: None`` lived exactly there.
These tests drive ``BioinformaticsWalkthrough`` itself, headless.
"""
from __future__ import annotations

import copy
import dataclasses

import pytest

pytest.importorskip("PyQt5")

from biwt.gui.walkthrough import _STEP_FIELDS, _STEP_ORDER


def _name(widget) -> str:
    return type(widget.window).__name__


def _continue(widget) -> None:
    """Click Continue on the current window."""
    widget.window.process_window()


def _answer(widget, yes: bool) -> None:
    """Pick Yes or No on a radio-button query window."""
    (widget.window.yes_rb if yes else widget.window.no_rb).setChecked(True)


# ---------------------------------------------------------------------------
# Spot deconvolution ⇄ spatial query sequencing
# ---------------------------------------------------------------------------

class TestSpotDeconvolutionSequencing:
    """spot_deconv.csv has both coordinates and *_probability columns."""

    def test_first_window_is_the_deconvolution_query(self, make_widget, drive_import):
        w, _ = make_widget()
        drive_import(w, "spot_deconv.csv")
        assert _name(w) == "SpotDeconvolutionQueryWindow"

    def test_yes_skips_cluster_column_and_spatial_query(self, make_widget, drive_import):
        w, _ = make_widget()
        drive_import(w, "spot_deconv.csv")
        _answer(w, True)
        _continue(w)
        assert _name(w) == "EditCellTypesWindow"
        assert w.session.use_spatial_data is True

    def test_no_asks_cluster_column_then_spatial_query(self, make_widget, drive_import):
        w, _ = make_widget()
        drive_import(w, "spot_deconv.csv")
        _answer(w, False)
        _continue(w)
        assert _name(w) == "ClusterColumnWindow"
        _continue(w)
        assert _name(w) == "SpatialQueryWindow"

    def test_no_then_yes_reaches_edit_cell_types(self, make_widget, drive_import):
        """The minimal form of the reported crash — no Back needed.

        Toggling twice marks futures stale, so advance() invalidates downstream
        state; before the fix that wiped the cell types and the column this very
        step had just derived, and EditCellTypes died on ``obs[None]``.
        """
        w, _ = make_widget()
        drive_import(w, "spot_deconv.csv")
        _answer(w, False)
        _answer(w, True)
        _continue(w)
        assert _name(w) == "EditCellTypesWindow"
        assert w.session.cell_types_list_original == ["Macrophage", "T_cell", "Tumor"]
        assert w.session.current_column is None

    def test_no_back_yes_never_shows_the_spatial_query(self, make_widget, drive_import):
        """The reported repro: No → Continue → Back → Yes → Continue."""
        w, _ = make_widget()
        drive_import(w, "spot_deconv.csv")
        _answer(w, False)
        _continue(w)
        assert _name(w) == "ClusterColumnWindow"

        w.go_back_to_prev_window()
        assert _name(w) == "SpotDeconvolutionQueryWindow"
        _answer(w, True)
        _continue(w)

        # Deconvolution implies spatial, so the question is never asked...
        assert _name(w) == "EditCellTypesWindow"
        # ...and the state the step derived survived the invalidation.
        assert w.session.use_spatial_data is True
        assert w.session.cell_prob_feature_dicts is not None
        assert w.session.spatial_data is not None

    def test_yes_back_no_asks_the_spatial_query_again(self, make_widget, drive_import):
        w, _ = make_widget()
        drive_import(w, "spot_deconv.csv")
        _answer(w, True)
        _continue(w)
        w.go_back_to_prev_window()
        _answer(w, False)
        _continue(w)

        assert _name(w) == "ClusterColumnWindow"
        s = w.session
        assert s.spatial_query_answer is None      # will be asked
        # Declining must not leave the deconvolution artifacts behind.
        assert s.cell_types_max is None
        assert s.cell_prob_feature_dicts is None


class TestNonDeconvolutionPaths:
    def test_spatial_without_probability_columns_skips_the_query(
        self, make_widget, drive_import
    ):
        w, _ = make_widget()
        drive_import(w, "spatial.csv")
        assert not w.session.data.probability_columns
        # The default cell-type column hint is "type", which spatial.csv has, so
        # ClusterColumn auto-continues on the next event loop turn.
        assert _name(w) in {"ClusterColumnWindow", "SpatialQueryWindow"}

    def test_cluster_column_auto_continues_when_the_hint_matches(
        self, make_widget, drive_import, qapp
    ):
        w, _ = make_widget()
        drive_import(w, "spatial.csv")
        qapp.processEvents()          # let the auto-continue QTimer fire
        assert _name(w) == "SpatialQueryWindow"
        assert any(
            type(win).__name__ == "ClusterColumnWindow" for win in w.window_history
        )

    def test_changing_the_column_rebuilds_the_spatial_query(
        self, make_widget, drive_import, qapp
    ):
        w, _ = make_widget()
        drive_import(w, "spatial.csv")
        qapp.processEvents()
        first = w.window
        assert _name(w) == "SpatialQueryWindow"

        w.go_back_to_prev_window()
        combo = w.window.column_combobox
        combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())
        _continue(w)

        assert _name(w) == "SpatialQueryWindow"
        assert w.window is not first               # rebuilt, not reused
        assert w.session.spatial_query_answer is True

    def test_back_without_changes_reuses_the_cached_window(
        self, make_widget, drive_import, qapp
    ):
        w, _ = make_widget()
        drive_import(w, "spatial.csv")
        qapp.processEvents()
        spatial_win = w.window

        w.go_back_to_prev_window()
        assert w.window_future[0] is spatial_win
        _continue(w)
        assert w.window is spatial_win

    def test_nonspatial_data_never_leaves_use_spatial_data_unset(
        self, make_widget, drive_import, qapp
    ):
        """Regression guard for the deleted no-spatial special case.

        ``use_spatial_data`` used to be a tri-state that invalidation could reset
        to None, which Qt then rejected (``setChecked(None)``).
        """
        w, _ = make_widget()
        drive_import(w, "nonspatial.csv")
        qapp.processEvents()
        seen = []
        for _ in range(4):
            seen.append(w.session.use_spatial_data)
            if _name(w) in {"PositionsWindow", "LoadCellParametersWindow"}:
                break
            _continue(w)
            qapp.processEvents()
        # Assert the walk happened: a loop that never advanced would collect
        # [False, False, ...] and pass without exercising the invalidation.
        assert len(seen) > 1
        assert seen == [False] * len(seen)


class TestHostInputResolution:
    """When BIWT reads host context, and what it guarantees about it afterwards.

    The motivating case: a host builds the widget as a tab at application startup
    and the user edits the domain in another tab before ever running BIWT. A host
    that passes a static ``BiwtInput`` is frozen at build time — Studio's is a
    local variable, so it cannot even be re-pointed — which is why the parameter
    also accepts a callable.
    """

    @staticmethod
    def _provider(box):
        """A host provider reading a one-element list, so a test can change it."""
        from biwt.types import BiwtInput, DomainSpec

        def provide():
            xmax, names = box[0]
            return BiwtInput(
                preferred_domain=DomainSpec(xmin=-xmax, xmax=xmax,
                                            ymin=-xmax, ymax=xmax),
                host_cell_type_names=list(names),
                host_name="Studio",
            )

        return provide

    def test_a_host_edit_before_import_is_picked_up(self, make_widget, drive_import):
        """The reported concern, end to end."""
        box = [(500.0, ["tumor"])]
        w, _ = make_widget(_source=self._provider(box))

        # The host's domain changes after the widget exists — a user typing in
        # another tab — and nothing tells BIWT.
        box[0] = (2000.0, ["tumor", "macrophage"])
        drive_import(w, "spatial.csv")

        assert w.session.preferred_domain.xmax == 2000.0
        assert w.session.biwt_input.host_cell_type_names == ["tumor", "macrophage"]

    def test_the_context_is_frozen_for_the_run(self, make_widget, drive_import):
        box = [(500.0, [])]
        w, _ = make_widget(_source=self._provider(box))
        drive_import(w, "spatial.csv")

        box[0] = (9999.0, [])              # host edit mid-walkthrough
        assert w.session.preferred_domain.xmax == 500.0
        assert w.session.effective_domain.xmax == 500.0

    def test_each_import_starts_a_new_run(self, make_widget, drive_import):
        calls = []
        box = [(500.0, [])]
        provide = self._provider(box)

        def counting():
            calls.append(box[0][0])
            return provide()

        w, _ = make_widget(_source=counting)
        assert calls == [500.0]            # construction

        drive_import(w, "spatial.csv")
        box[0] = (1500.0, [])
        drive_import(w, "spatial.csv")
        assert calls == [500.0, 500.0, 1500.0]
        assert w.session.preferred_domain.xmax == 1500.0

    def test_effective_domain_is_the_host_domain_object(self, make_widget, drive_import):
        """No second latched copy — see TestEffectiveDomain in test_session.py."""
        w, _ = make_widget()
        drive_import(w, "spatial.csv")
        assert w.session.effective_domain is w.session.preferred_domain

    def test_a_static_input_is_snapshotted(self, make_widget, drive_import):
        """A host that mutates the instance it handed over cannot reach the run.

        In-place mutation of the host's own ``DomainSpec`` used to rewrite
        ``domain_used`` after the coordinates had been computed, so the result
        asserted that domain and coordinates agreed when they did not.
        """
        from biwt.types import DomainSpec

        host_domain = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)
        w, _ = make_widget(preferred_domain=host_domain)
        drive_import(w, "spatial.csv")

        host_domain.xmax = 9999.0
        assert w.session.effective_domain.xmax == 500.0

    def test_a_provider_that_raises_keeps_the_last_good_context(
        self, make_widget, drive_import
    ):
        from biwt.types import BiwtInput, DomainSpec

        state = {"fail": False}

        def flaky():
            if state["fail"]:
                raise RuntimeError("host is mid-teardown")
            return BiwtInput(
                preferred_domain=DomainSpec(xmin=-700, xmax=700, ymin=-700, ymax=700)
            )

        w, _ = make_widget(_source=flaky)
        state["fail"] = True
        drive_import(w, "spatial.csv")      # must not raise

        assert _name(w) in {"ClusterColumnWindow", "SpatialQueryWindow"}
        assert w.session.preferred_domain.xmax == 700.0

    def test_a_provider_returning_the_wrong_type_keeps_the_last_good_context(
        self, make_widget, drive_import
    ):
        """"Refused" has to mean the previous context survived, not just "no crash".

        A provider that is wrong from the start makes the fallback and a fresh
        `BiwtInput()` indistinguishable, so the assertion has to be made against a
        context that differs from the default.
        """
        from biwt.types import BiwtInput, DomainSpec

        state = {"good": True}

        def flaky():
            if not state["good"]:
                return {"preferred_domain": "nope"}
            return BiwtInput(
                preferred_domain=DomainSpec(xmin=-700, xmax=700, ymin=-700, ymax=700),
                host_cell_type_names=["tumor"],
            )

        w, _ = make_widget(_source=flaky)
        state["good"] = False
        drive_import(w, "spatial.csv")

        assert _name(w) in {"ClusterColumnWindow", "SpatialQueryWindow"}
        assert w.session.preferred_domain.xmax == 700.0
        assert w.session.biwt_input.host_cell_type_names == ["tumor"]

    def test_neither_an_input_nor_a_callable_is_a_TypeError(self, qapp):
        from biwt.gui.walkthrough import create_biwt_widget

        with pytest.raises(TypeError, match="BiwtInput or a callable"):
            create_biwt_widget({"preferred_domain": None})

    def test_domain_accepted_from_a_later_resolution_is_ignored(
        self, make_widget, drive_import
    ):
        """The checkbox is on screen by then, and it is the documented authority."""
        from biwt.types import BiwtInput

        box = [False]
        w, _ = make_widget(_source=lambda: BiwtInput(domain_accepted=box[0]))
        assert w._domain_accepted_cb.isChecked() is False

        box[0] = True
        drive_import(w, "spatial.csv")
        assert w.session.domain_accepted is False


class TestPositionsDomainAutoShow:
    """The one step no other test builds, because it can open a modal dialog.

    That exemption is how a ``NameError`` in ``_maybe_show_domain_editor`` reached
    a live Studio run: 473 tests passed without executing the line. Suppressing
    the modal costs one monkeypatch, so the path is now walked for real.
    """

    @staticmethod
    def _walk_to_positions(widget, qapp) -> None:
        for _ in range(8):
            qapp.processEvents()
            if _name(widget) == "PositionsWindow":
                return
            _continue(widget)
        raise AssertionError(f"never reached Positions (stuck on {_name(widget)})")

    def test_the_auto_shown_editor_prefills_the_data_extent(
        self, make_widget, drive_import, qapp, monkeypatch
    ):
        from PyQt5.QtWidgets import QDialog

        from biwt.gui.walkthrough import DomainEditorDialog
        from biwt.types import DomainSource, DomainSpec

        opened = []
        monkeypatch.setattr(
            DomainEditorDialog, "exec_",
            lambda self: (opened.append(self), QDialog.Rejected)[1],
        )

        # spatial.csv spans x ∈ [-200, 200]; a ±50 host domain cannot hold it, so
        # the mismatch dialog is due.
        w, _ = make_widget(
            preferred_domain=DomainSpec(xmin=-50, xmax=50, ymin=-50, ymax=50),
            host_name="Studio",
        )
        drive_import(w, "spatial.csv")
        self._walk_to_positions(w, qapp)

        assert len(opened) == 1
        domain, _factor, _apply = opened[0].result()
        assert (domain.xmin, domain.xmax) == (-200.0, 200.0)
        assert domain.source == DomainSource.DATA
        assert w.session.domain_accepted        # asked once, never re-asked

    def test_no_editor_when_the_data_matches_the_host_domain(
        self, make_widget, drive_import, qapp, monkeypatch
    ):
        from biwt.gui.walkthrough import DomainEditorDialog
        from biwt.types import DomainSpec

        def _fail(self):
            raise AssertionError("domain editor opened for a domain that fits")

        monkeypatch.setattr(DomainEditorDialog, "exec_", _fail)

        # Snug around x ∈ [-200, 200], y ∈ [-200, 250]: the data neither escapes
        # the box nor under-fills it, which are the only two mismatches worth a
        # dialog. The default ±500 would be flagged "small" — 400 µm of cells in
        # 1000 µm of domain is sparse, not fitting.
        w, _ = make_widget(
            preferred_domain=DomainSpec(xmin=-250, xmax=250, ymin=-275, ymax=275)
        )
        drive_import(w, "spatial.csv")
        self._walk_to_positions(w, qapp)
        assert w.session.domain_accepted


class TestCompletionCallback:
    def test_closing_without_finishing_never_calls_back(self, make_widget, drive_import):
        """The docs promised `on_complete(None)` on cancel; nothing ever sent it.

        A host that cleared a "BIWT running" flag in that branch would have waited
        forever. Documented as "called once, when the user finishes" instead — this
        pins that, so the claim cannot drift back.
        """
        w, completed = make_widget()
        drive_import(w, "nonspatial.csv")
        w.close()
        assert completed == []


class TestManualDomainEditor:
    """The **Domain Settings…** button, which chooses its own pre-fill.

    Non-spatial data has no real extent — `infer_domain` finds no coordinates, so
    `data_domain` is BIWT's ±500 fallback. Pre-filling *that* would offer the user
    a box nobody chose in place of the host's, and pressing OK would stamp it
    `data`. Untested, the branch that avoids it could be deleted with the suite
    still green.
    """

    def test_a_nonspatial_run_prefills_the_host_domain(
        self, make_widget, drive_import, qapp, monkeypatch
    ):
        from PyQt5.QtWidgets import QDialog

        from biwt.gui.walkthrough import DomainEditorDialog
        from biwt.types import DomainSource, DomainSpec

        opened = []
        monkeypatch.setattr(
            DomainEditorDialog, "exec_",
            lambda self: (opened.append(self), QDialog.Rejected)[1],
        )
        w, _ = make_widget(
            preferred_domain=DomainSpec(xmin=-2000, xmax=2000, ymin=-2000, ymax=2000)
        )
        drive_import(w, "nonspatial.csv")
        for _ in range(6):
            qapp.processEvents()
            if _name(w) == "PositionsWindow":
                break
            _continue(w)
        assert _name(w) == "PositionsWindow"
        assert not opened                     # nothing auto-opens without coordinates

        w.window.domain_settings_button.click()
        assert len(opened) == 1
        domain, _factor, _apply = opened[0].result()
        assert (domain.xmin, domain.xmax) == (-2000.0, 2000.0)
        assert domain.source == DomainSource.HOST


class TestPositionsLegend:
    """The legend is its own top-level window, so it needs telling to follow.

    It used to be closed by two explicit calls — Continue, and the Go back
    *button*'s pre-hook — which left it floating over the next step whenever the
    user left by any other route: the controller's own `go_back_to_prev_window`,
    a stale cached window being discarded, or a re-import.
    """

    @staticmethod
    def _at_positions_with_legend(make_widget, drive_import, qapp, monkeypatch):
        from PyQt5.QtWidgets import QDialog

        from biwt.gui.walkthrough import DomainEditorDialog

        monkeypatch.setattr(DomainEditorDialog, "exec_",
                            lambda self: QDialog.Rejected)
        w, _ = make_widget()
        drive_import(w, "spatial.csv")
        for _ in range(6):
            qapp.processEvents()
            if _name(w) == "PositionsWindow":
                break
            _continue(w)
        assert _name(w) == "PositionsWindow"
        pos = w.window
        pos.show()
        qapp.processEvents()
        pos._show_legend_cb()
        qapp.processEvents()
        assert pos.legend_window.isVisible()
        return w, pos

    def test_continue_takes_the_legend_with_it(
        self, make_widget, drive_import, qapp, monkeypatch
    ):
        w, pos = self._at_positions_with_legend(make_widget, drive_import, qapp, monkeypatch)
        pos.process_window()
        qapp.processEvents()
        assert not pos.legend_window.isVisible()

    def test_going_back_takes_the_legend_with_it(
        self, make_widget, drive_import, qapp, monkeypatch
    ):
        """Through the controller, not the button — the button is one caller."""
        w, pos = self._at_positions_with_legend(make_widget, drive_import, qapp, monkeypatch)
        w.go_back_to_prev_window()
        qapp.processEvents()
        assert not pos.legend_window.isVisible()

    def test_discarding_the_window_takes_the_legend_with_it(
        self, make_widget, drive_import, qapp, monkeypatch
    ):
        w, pos = self._at_positions_with_legend(make_widget, drive_import, qapp, monkeypatch)
        w.go_back_to_prev_window()
        qapp.processEvents()
        w.stale_futures = True              # the user changes something upstream
        w.window.process_window()
        qapp.processEvents()
        assert not pos.legend_window.isVisible()

    def test_reimport_takes_the_legend_with_it(
        self, make_widget, drive_import, qapp, monkeypatch
    ):
        w, pos = self._at_positions_with_legend(make_widget, drive_import, qapp, monkeypatch)
        drive_import(w, "spatial.csv")
        qapp.processEvents()
        assert not pos.legend_window.isVisible()

    def test_it_returns_with_the_window_it_describes(
        self, make_widget, drive_import, qapp, monkeypatch
    ):
        """Back-then-forward reuses the window and its plot; the legend is that
        plot's key, so it comes back too."""
        w, pos = self._at_positions_with_legend(make_widget, drive_import, qapp, monkeypatch)
        w.go_back_to_prev_window()
        qapp.processEvents()
        w.window.process_window()
        qapp.processEvents()
        assert w.window is pos
        assert pos.legend_window.isVisible()


class TestReimport:
    def test_reimport_drops_every_window_of_the_previous_run(
        self, make_widget, drive_import, qapp
    ):
        """No window built against the old session may survive a re-import.

        One did: ``_start_walkthrough`` cleared the stacks but left
        ``self.window`` set, so ``advance()`` pushed that dead window onto the
        fresh history and Go back would show it reading the new session.
        """
        w, _ = make_widget()
        drive_import(w, "spatial.csv")
        qapp.processEvents()
        _continue(w)                              # advance a couple of steps
        assert w.window_history
        # Keep real references, not ids: the old widgets are dropped on
        # re-import and CPython happily reuses their addresses.
        stale = [*w.window_history, *w.window_future, w.window]

        drive_import(w, "nonspatial.csv")
        qapp.processEvents()
        live = [*w.window_history, *w.window_future, w.window]
        assert not [win for win in live if any(win is old for old in stale)]

    def test_reimport_starts_from_the_new_data(self, make_widget, drive_import, qapp):
        w, _ = make_widget()
        drive_import(w, "spot_deconv.csv")
        _answer(w, True)
        _continue(w)

        drive_import(w, "nonspatial.csv")
        qapp.processEvents()
        assert not w.session.perform_spot_deconvolution
        assert w.session.data.n_cells == 6


# ---------------------------------------------------------------------------
# Field ownership — the class-level guard
# ---------------------------------------------------------------------------

# Session fields no step owns: they are set at import, derived by
# reseed_derived_state(), or written by the domain editor.  Listing them here is
# the documentation of that fact.
_UNOWNED_FIELDS = {
    "biwt_input", "data", "user_domain", "data_domain",
    "domain_accepted", "scale_factor", "apply_scale", "spatial_data",
    "cell_types_max", "cell_prob_feature_dicts",
    # Loading a template library is an action, not an answer to a step, so no
    # step owns it and no invalidation may clear it.
    "template_library_paths",
}

_FIELD_OWNER = {
    field: step
    for step, fields in _STEP_FIELDS.items()
    for field in fields
}


def _snapshot(session) -> dict:
    return {
        f.name: copy.deepcopy(getattr(session, f.name))
        for f in dataclasses.fields(session)
        if f.name != "data"                   # the loaded frame never changes
    }


def _changed(before: dict, after: dict) -> set:
    import numpy as np

    changed = set()
    for name, old in before.items():
        new = after[name]
        if isinstance(old, np.ndarray) or isinstance(new, np.ndarray):
            same = (
                isinstance(old, np.ndarray)
                and isinstance(new, np.ndarray)
                and np.array_equal(old, new)
            )
        else:
            same = old is new or old == new
        if not same:
            changed.add(name)
    return changed


class TestStepFieldOwnership:
    """A step may only commit fields owned by itself or by an earlier step.

    Committing a *later* step's field is what caused the reported crash: the
    downstream invalidation inside ``advance()`` runs after ``process_window``
    has written, so anything a step stores on a later step's behalf is wiped
    immediately.

    The comparison window is deliberately narrow — from just before
    ``process_window`` to the moment ``advance()`` is entered.  That is exactly
    the step's own commit, and it excludes the *next* window's constructor,
    which legitimately initializes its own fields after the invalidation (as
    ``PositionsWindow`` does with ``coords_by_type``).
    """

    @pytest.mark.parametrize(
        "fixture,answers",
        [
            ("spot_deconv.csv", [True]),
            ("spot_deconv.csv", [False]),
            ("nonspatial.csv", []),
        ],
    )
    def test_no_step_commits_a_downstream_field(
        self, make_widget, drive_import, qapp, fixture, answers
    ):
        # Skip domain validation: reaching the positions step otherwise raises
        # the modal domain editor, which a headless run cannot dismiss.
        w, _ = make_widget(domain_accepted=True)
        drive_import(w, fixture)
        qapp.processEvents()
        answers = list(answers)

        committed: dict = {}
        real_advance = w.advance

        def spy_advance():
            # Entry to advance() = the leaving step has committed, and nothing
            # else has run yet.
            committed["state"] = _snapshot(w.session)
            real_advance()

        w.advance = spy_advance

        for _ in range(8):
            if w.window is None:
                break
            label = getattr(w.window, "_step_label", None)
            # Stop at Positions: continuing from it can raise a modal dialog
            # about out-of-domain cells, which would block a headless run.
            if label is None or label in {"Positions", "LoadCellParameters"}:
                break
            if answers and hasattr(w.window, "yes_rb"):
                _answer(w, answers.pop(0))

            before = _snapshot(w.session)
            committed.clear()
            _continue(w)
            qapp.processEvents()
            if "state" not in committed:
                break                    # the step blocked instead of advancing

            allowed_upto = _STEP_ORDER.index(label)
            for field in _changed(before, committed["state"]):
                if field in _UNOWNED_FIELDS:
                    continue
                owner = _FIELD_OWNER.get(field)
                assert owner is not None, f"{label} committed unowned field {field!r}"
                assert _STEP_ORDER.index(owner) <= allowed_upto, (
                    f"{label} committed {field!r}, which belongs to the later "
                    f"step {owner!r} — the invalidation in advance() wipes it"
                )
