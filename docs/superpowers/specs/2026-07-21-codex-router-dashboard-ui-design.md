# Codex Router Dashboard UI Design

**Product surface:** Local operations dashboard for a Codex-only developer gateway.

**Direction:** Dark operations console — calm, dense, technical, and readable at a glance. The design follows the `ui-ux-pro-max` recommendation for an OLED-style operations dashboard, but uses bundled/system fonts so the dashboard remains offline-capable.

## Tokens

```css
:root {
  --bg: #0b1120;
  --surface: #111827;
  --surface-raised: #172033;
  --border: #2b3952;
  --text: #f8fafc;
  --muted: #a8b4c7;
  --accent: #22c55e;
  --warning: #f59e0b;
  --danger: #f87171;
  --focus: #7dd3fc;
}
```

Use system UI typography (`Inter`, `Segoe UI`, `system-ui`, sans-serif), a 4/8px spacing rhythm, 12px card radius, and 1px borders. Status colors must be paired with text labels; color alone never communicates health.

## Layout

- Top bar: product name, transport badge, and a compact security badge.
- Hero/status card: current health, Codex session state, approval policy, sandbox.
- Metric grid: total requests, active, completed, failed.
- Main grid: model catalog on the left; usage-by-model and capability card on the right.
- Footer note: local-only boundary and “secrets never displayed”.
- Breakpoints: mobile-first, 375px baseline; 768px two columns; 1024px main grid; 1440px max-width 1200px.

## Interaction and accessibility

- Dashboard is readable without JavaScript; JavaScript refresh is progressive enhancement only.
- Data refresh uses a visible “Refresh” button with a text label, minimum 44px height, focus ring, and `aria-live="polite"` status message.
- Loading state uses skeleton/“Refreshing…” feedback; errors state the recovery action.
- No emoji or icon-only controls; use simple inline SVG or text labels.
- `prefers-reduced-motion: reduce` disables transitions and pulse effects.
- Contrast target is WCAG AA for body text and visible focus against both surfaces.
- Model IDs use wrapping/scroll-safe text, never HTML or script interpolation.
