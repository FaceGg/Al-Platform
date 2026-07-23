# UI Preview Directions Design

**Goal:** Provide selectable visual directions for the Precision Forge product shell without changing the running application.

**Scope:** A standalone static preview includes the product sidebar, top bar, dashboard, and recent-project surface. It is intentionally disconnected from React routes, API calls, authentication, and production theme tokens.

## Shared Content Model

All directions render the same operational content: four asset metrics, one training activity chart, one quality readiness signal, recent production work, and a concise project table. Keeping content stable makes visual and interaction differences comparable.

## Directions

1. **Cold Black Industrial**: graphite surfaces, restrained weld-orange focus color, dense tooling hierarchy, and a high-contrast control-room feeling.
2. **Paper Laboratory**: light neutral ground, ink typography, acid-green focus color, and calm separated work areas for prolonged analysis.
3. **Midnight Cobalt**: near-black blue surfaces, cobalt focus color, aqua execution status, and stronger emphasis on active operational flow.

## Interaction and Responsiveness

The top selector switches direction immediately. A compact-width control constrains the preview to an application-like narrow frame and reflows the sidebar into a top navigation strip. Controls are local to the preview and do not persist or call project APIs.

## Verification

Open `ml-platform/frontend/ui-previews/index.html` in a browser. Verify each direction changes the palette and shell composition, narrow mode keeps text inside its containers, and the original `src/` tree remains unchanged.
