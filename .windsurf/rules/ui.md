---
trigger: always_on
---

## UI Parity Rule (Non-Negotiable)

When adding a new page/view inside an existing section (e.g. Podcasts, Events, Admin), you MUST NOT re-implement layout, header, sidebar, filters, modals, or card styles from scratch.

Instead:

1) Reuse the section’s existing layout component (or extract one if missing) so:
   - Sidebar does not remount or refetch on navigation
   - Header placement and spacing is consistent
   - Filters live in the same header region as other pages

2) Reuse the exact same UI primitives/components used elsewhere:
   - Sidebar items: same component as normal entries
   - Cards: same card component/styles
   - Modals: one shared modal component used across lists

3) Validate parity before shipping:
   - Screenshot compare vs canonical page
   - Verify no duplicated network fetches caused by remounting
   - Verify all existing actions appear in the same place and work

If parity cannot be achieved by composition and reuse, stop and refactor to enable reuse before shipping.
