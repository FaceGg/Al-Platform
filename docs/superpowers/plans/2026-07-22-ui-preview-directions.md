# UI Preview Directions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone, selectable preview of three product-shell visual directions without modifying the production frontend.

**Architecture:** A self-contained HTML file owns its mock data, rendering markup, responsive CSS, and tiny theme-switching script. It lives outside `src/` so it cannot affect existing Vite routes or runtime behavior.

**Tech Stack:** HTML, CSS custom properties, vanilla JavaScript.

---

### Task 1: Build isolated preview shell

**Files:**
- Create: `ml-platform/frontend/ui-previews/index.html`

- [ ] **Step 1: Define theme tokens and stable dashboard markup**

Create a `preview-shell` containing sidebar, top bar, four metrics, charts, execution items, and projects. Use `body[data-direction]` CSS variable overrides for `industrial`, `laboratory`, and `cobalt`.

- [ ] **Step 2: Add comparison controls and narrow responsive layout**

Add buttons with `data-direction` plus a narrow-layout button. Set `aria-pressed` on the active controls. Use a CSS media query and `.is-compact` to reduce the layout to one column while preserving the same data.

- [ ] **Step 3: Verify browser behavior**

Open the file through a local static server and confirm all three directions and compact mode render without overflow.

### Task 2: Record preview-only scope

**Files:**
- Create: `docs/superpowers/specs/2026-07-22-ui-preview-directions-design.md`
- Modify: `DEVELOPMENT_PLAN.md`

- [ ] **Step 1: Record direction intent and non-interference contract**

Describe the shared content model, visual directions, controls, and verification method in the design document.

- [ ] **Step 2: Append project plan record**

Document the preview task as a non-production, selection-stage deliverable and retain the current weekly implementation status.
