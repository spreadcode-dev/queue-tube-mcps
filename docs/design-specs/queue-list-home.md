# Design Spec — Queue List Home

**Screen:** Queue List Home  
**Type:** New Screen  
**Platforms:** Desktop Web, Mobile Web  

---

## Description

The Queue List Home is the first screen a user sees after logging in.
It displays all of their named video queues as browsable cards, and gives
them a fast path to open, create, or manage a queue.

---

## UI Elements

### Header (sticky)
- Left: QueueTube logo (wordmark)
- Right: search icon + user avatar (tapping avatar opens account dropdown)

### Body
- Section heading: "My Queues"
- **Queue Card Grid** — 2 columns on desktop ≥1280px, 1 column on mobile
  - Each card contains:
    - Thumbnail (16:9, auto-generated gradient if no custom image)
    - Queue name (bold, 16px)
    - Video count badge (e.g. "12 videos")
    - Last played timestamp (muted, 12px, e.g. "Played 2 hours ago")
    - Three-dot overflow menu icon (visible on hover/focus)

### Empty State (no queues yet)
- Centred illustration (abstract play-button motif in accent colour)
- Heading: "No queues yet"
- Subtext: "Create a queue to start organising your videos."
- Primary CTA button: "Create Queue"

### Floating Action Button (FAB)
- "+" icon
- Accent colour (#E94560)
- Fixed: bottom-right, 24px margin
- Tooltip on hover: "New Queue"

---

## Interactions & States

| Trigger | Result |
|---|---|
| Click Queue Card | Navigate to Queue Detail screen |
| Hover Queue Card | Elevation shadow + scale(1.02) |
| Click Three-dot menu | Context menu: Rename · Duplicate · Delete |
| Click FAB | Open "Create Queue" modal |
| Loading | Skeleton cards (same grid layout) |
| Empty state CTA click | Open "Create Queue" modal |

---

## References

- Similar pattern: YouTube playlist overview screen
- Design token reference: `docs/DESIGN_PIPELINE.md#queuestube-design-tokens`

---

## Acceptance Criteria

- [ ] Desktop layout shows 2-column card grid
- [ ] Mobile layout shows 1-column card grid
- [ ] Empty state visible when queue list returns 0 items
- [ ] FAB visible on both breakpoints
- [ ] Figma component for `QueueCard` published to shared library
- [ ] All interactive states (hover, loading, empty, overflow menu) documented
