# `biwt.gui`

The Qt layer. `create_biwt_widget` is the host entry point; everything else here is internal.

!!! note
    Importing this module requires PyQt5 (`pip install "biwt[gui]"`).

## The factory

::: biwt.gui.walkthrough.create_biwt_widget
    options:
      show_root_heading: true
      show_root_toc_entry: false

## Session state

`WalkthroughSession` is the pure-Python state machine behind the widget — no Qt dependency.
All the answers you give during the walkthrough accumulate here, and each step window reads
and writes it. Internal, but the clearest single place to understand what the wizard tracks.

::: biwt.gui.walkthrough.WalkthroughSession
    options:
      show_root_heading: true
      show_root_toc_entry: false
      members: true

## Step ordering

::: biwt.gui.walkthrough._step_predicates
    options:
      show_root_heading: true
      show_root_toc_entry: false

## The widget

::: biwt.gui.walkthrough.BioinformaticsWalkthrough
    options:
      show_root_heading: true
      show_root_toc_entry: false
      members:
        - closeEvent
