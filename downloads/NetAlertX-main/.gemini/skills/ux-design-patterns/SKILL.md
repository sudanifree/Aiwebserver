---
name: ux-design-patterns
description: Read before adding or changing any front/ UI element - a control, layout, button, or interaction pattern. Covers the don't-invent-new-UX-without-a-PRD rule and the priority order for design tradeoffs (existing behavior > intuitiveness > information density > usability > utility > uniqueness > industry practices > generic UI).
---

# UX / Frontend Design Patterns

## Core principle: reuse before inventing

Don't introduce new UX behavior or visual patterns unless a PRD explicitly calls for it. Before building any new UI element, search the existing frontend for a pattern that already solves this exact need, and reuse its markup/CSS/behavior instead of inventing a new one.

Real, recent example: a presence-page Prev/Next pager was first built with custom `<button class="btn btn-xs">` elements floated in a `.box-header`. The DataTables pagination pattern (`dataTables_wrapper` / `dataTables_paginate` / `ul.pagination` / `li.paginate_button.previous|next`) already existed elsewhere in the app and does the exact same job. The custom version looked visually broken in the actual UI and had to be reimplemented using the existing pattern once that was caught in manual testing - reusing it also picked up dark-mode theming (`front/css/dark-patch.css`'s `.pagination li > a` / `.disabled` rules) for free, which the hand-rolled version didn't have. Grep first: e.g. `grep -rn "pagination\|paginate_button" front/` before adding a "previous/next" control of your own; the same applies to modals, filter inputs, badges, tooltips, tables - anything that already has an established shape somewhere in `front/`.

## Priority order for design decisions

When several options are all locally reasonable, resolve the choice in this order - highest wins on conflict:

1. **Existing behavior** - what does this codebase already do for the same or a similar need? Copy it.
2. **Intuitiveness** - will a user already familiar with the rest of the app understand this without being told?
3. **Information density** - does it show what's needed without wasting space or hiding what matters?
4. **Usability** - is it easy and low-friction to actually use (reachability, click count, error tolerance)?
5. **Utility** - does it solve the real problem, not just resemble a solution?
6. **Uniqueness** - is this the app's own distinct answer, used only where nothing generic fits well?
7. **Industry practices** - conventions users bring in from other apps.
8. **Generic UI** - a default/framework-provided look, used only when nothing above applies.

This list exists to end debates quickly, not to be argued from the bottom up. The reason it's written down is that #1 is exactly the step that gets skipped under time pressure - checking it first is meant to be fast, not a detour.

## Practical checklist before building a new UI element

1. Grep `front/js/`, `front/css/`, `front/php/` for an existing implementation of the same interaction - a table, a pager, a filter box, a modal, a badge, a status indicator.
2. If found, reuse its markup and CSS classes directly rather than writing new ones - matching classes inherit theming (dark mode, responsive breakpoints) a new hand-rolled version won't have.
3. If nothing fits, check whether the PRD driving this change actually calls for new UX. If it doesn't, that's a signal to look harder for an existing pattern, not license to invent one.
4. If a new pattern is genuinely warranted and the PRD says so, design it using the priority order above, and record the choice and why existing patterns didn't fit in the PRD - the next change will hit the same fork and shouldn't have to re-derive the answer.
5. Verify visually in a real browser/devcontainer before calling it done. A change that "should work" per the markup isn't confirmed until it's actually rendered - matches the project's general "test the golden path in a browser" rule for frontend changes.
