# UI Component Development Guidelines

These guidelines define how to build and maintain a scalable, component-based front-end architecture.

For terminal user interfaces, use `dev-guides/TUI_DEVELOPMENT_GUIDELINES.md` instead of applying HTML/CSS-specific rules directly. The same product-quality expectations still apply: clear component ownership, keyboard accessibility, safe feedback, and tested interaction states.

## 1) Component-First Architecture

- Build UI features as reusable, isolated components.
- Keep each component responsible for a single UI concern.
- Avoid duplicating markup across pages; import components from shared fragment/template locations.
- Prefer composition (assembling smaller components) over large monolithic templates.

## 2) File Structure and Ownership

A component should have clear ownership of its assets:

- **Template/markup** (HTML fragment, partial, or component template).
- **Styles** (component-specific CSS when needed).
- **Behavior** (component-specific JavaScript when needed).

Recommended pattern (example):

```text
components/
  top-bar/
    top-bar.html
    top-bar.css
    top-bar.js
```

## 3) CSS Best Practices

- Use `common.css` only for true shared foundations (tokens, reset, typography scale, utility classes, spacing system).
- **Every component should have its own CSS file for integration and local styling, unless the component is fully covered by `common.css`.**
- Keep selectors scoped to the component (`.top-bar`, `.sidebar-panel`, etc.) to prevent style leaks.
- Do not override component styles globally unless required and documented.
- Prefer design tokens (colors, spacing, radius, shadows) over hard-coded values.

## 4) JavaScript Best Practices

- **Each component should have its own JavaScript file for component-specific interactions**, unless behavior is provided by:
  - shared utility libraries, or
  - common domain/application libraries.
- Keep component scripts small and focused (one responsibility per module).
- Use shared libraries only for cross-cutting concerns (formatting, API client, event bus, analytics, domain logic).
- Avoid embedding large inline scripts directly inside page templates.
- Initialize components in a predictable lifecycle (`DOMContentLoaded`, framework hooks, or HTMX events).

## 5) Integration Rules for Shared Libraries

Use common libraries when:

- A function is reused by multiple components.
- Logic belongs to an application domain (e.g., auth, notifications, case management).
- Behavior must be consistent across pages (e.g., date formatting, telemetry, feature flags).
- The feature consults user activity audit data through the shared `Audit & Logs` domain module.

Do not use common libraries when:

- Logic is specific to a single component and unlikely to be reused.

## 6) Accessibility and Semantics

- Use semantic HTML elements (`header`, `nav`, `main`, `section`, `aside`, `button`, etc.).
- Provide meaningful `aria-label`s where needed.
- Ensure keyboard accessibility for interactive elements.
- Maintain visible focus states and proper color contrast.

## 7) Performance and Maintainability

- Lazy-load or progressively load secondary components when possible.
- Keep DOM structure minimal and avoid deeply nested wrappers.
- Minimize CSS and JS payload per page by loading only what is needed.
- Remove dead code and unused selectors/scripts during refactors.

## 8) Naming and Consistency

- Use consistent naming for component folders and files.
- Keep file names aligned with component names (`right-panel.html`, `right-panel.css`, `right-panel.js`).
- Prefer explicit, domain-meaningful names over generic ones.

## 9) Testing and Validation

- Validate each component in isolation and in page integration.
- Check responsive behavior at key breakpoints.
- Verify behavior with and without optional data states.
- Add regression checks for shared libraries that impact multiple components.

## 10) Multilingual Interface Guidelines

All user-facing UI must be designed as multilingual from the start. English is the default/fallback language, with Italian and German supported through the shared HMI i18n library.

### Shared i18n Library

- Use `src/main/resources/static/js/hmi/core/i18n.js` as the single source for UI copy.
- Register user-facing strings in the dictionaries for `en`, `it`, and `de`.
- Use stable, domain-oriented keys such as `home.shell.auditTitle`, `home.navigation.auditLogs`, or `common.status.mqttIdle`.
- Do not introduce component-local translation maps unless the text is truly private and cannot be reused.
- Language preference is persisted with the `velia.language` cookie. Do not use `localStorage` or `sessionStorage` for language preference.

### Markup and Templates

For static Thymeleaf fragments or static HTML, add translation metadata directly in markup:

```html
<span data-i18n="home.topBar.missionControl">Mission Control</span>
<button
    type="button"
    aria-label="Refresh"
    data-i18n-attr="aria-label:common.actions.refresh">
    ↻
</button>
```

- Use `data-i18n` for visible text content.
- Use `data-i18n-attr` for translated attributes such as `aria-label`, `title`, `placeholder`, and `data-tooltip`.
- Always keep an English fallback text in the markup so the no-JavaScript/server-side fallback remains readable.
- After dynamically inserting a server-rendered fragment, call `window.veliaI18n?.applyTranslations?.(slot)`.

### JavaScript Renderers

For JavaScript-rendered panels, prefer explicit calls to `window.veliaI18n.t()` when creating labels, titles, button text, status text, empty states, helper text, and modal text:

```javascript
const t = (key, fallback) => window.veliaI18n?.t?.(key, {defaultValue: fallback}) || fallback;

slot.innerHTML = `
    <button type="button">${t('common.actions.refresh', 'Refresh')}</button>
`;
```

- Do not hardcode new English-only strings in renderers.
- Do not rely on phrase-based fallback for new components. Phrase fallback exists only as a bridge for legacy panels.
- Translate dynamic status messages with templates and interpolation instead of string concatenation when possible.
- Format dates/numbers using the active language where practical. If a component has local format helpers, use `window.veliaI18n?.getLanguage?.()` as the locale source.
- When a component renders after async API calls, call `window.veliaI18n?.applyTranslations?.(container)` after the render completes.

### Dynamic Content Boundaries

Translate UI chrome, labels, helper text, statuses, buttons, table headers, empty states, form placeholders, modal titles, tooltips, and ARIA labels.

Do **not** translate:

- User-entered content.
- Organization, tenant, user, document, report, or Knowledge Base names returned by APIs.
- IDs, UUIDs, technical statuses that are intentionally backend enums unless a display label layer exists.
- Raw JSON, logs, payload previews, prompts, generated reports, or document contents.

### Language Selector

- The language selector belongs in the top bar and must use the shared `data-language-selector` hook.
- Changing language must persist `velia.language` as a cookie and reload or rerender enough UI to keep server fragments and client panels consistent.
- Do not add duplicate language selectors inside individual panels unless the top bar is unavailable.

### Testing Expectations

When adding or changing UI copy:

- Add or update tests for `src/main/resources/static/js/hmi/core/i18n.js` when shared i18n behavior changes.
- Add renderer tests when a component consumes translation keys directly.
- Verify at least English and one non-English language for new panels.
- Check that navigation, click handlers, form submissions, and modals still work after translations are applied.
- Include translated attribute coverage for accessibility-critical text (`aria-label`, `title`, `placeholder`).

## 11) Documentation Requirements

For each component, document:

- Purpose and responsibilities.
- Required inputs/parameters.
- Events and interactions.
- CSS and JS dependencies.
- Example usage in a page template.

## Quick Checklist

Before merging a UI change, confirm:

- [x] Component markup is reusable and not duplicated inline.
- [x] Component styling is in its own CSS file (unless fully covered by `common.css`).
- [x] Component behavior is in its own JS file or uses approved shared libraries.
- [x] Accessibility and semantic rules are respected.
- [x] Dependencies and usage are documented.
- [x] New UI copy is wired through `veliaI18n` with English, Italian, and German entries.
- [x] Static markup uses `data-i18n` / `data-i18n-attr` where applicable.
- [x] JavaScript renderers call `veliaI18n.t()` for labels, helper text, statuses, empty states, buttons, modals, and table headers.
- [x] Dynamic render flows call `veliaI18n.applyTranslations()` after inserting fragments or async panel content.
- [x] Language preference uses the `velia.language` cookie only.
- [x] Post-login experience uses a single home shell with dynamic slot loading (`home-sidebar-slot`, `home-title-slot`, `home-main-slot`).
- [x] Profile-specific fragments are co-located in one file per area (`home-sidebar.html`, `home-title.html`, `home-main.html`).
- [x] `FragmentController` resolves profile → fragment via switch statement with `USER` as safe fallback.
- [x] Frontend `normalizeProfile()` mirrors backend `resolveProfile()` logic exactly.
- [x] Server-side `th:insert` default (USER) is present in slot elements as no-JS fallback.
- [x] UI personalization is not used as a substitute for backend authorization.
- [x] New mutating UI workflows are backed by backend audit integration when they change data, access, documents, configuration or async jobs.


## 12) Profile-Based UI Component Management

### Architecture Overview

The post-login home page uses a **single shell with dynamic fragment slots**. The profile is resolved from the authenticated user token and used to load the correct UI variant for each area.

Three areas are personalized per profile:

- **Left panel (sidebar)** — menu and actions differ significantly by role.
- **Home title** — greeting or section label varies by profile.
- **Main content** — widgets and cards differ by domain responsibilities.

Supported profiles (defined in `UserProfile.java`):

```
ADMINISTRATOR  →  full system visibility
TENANT         →  manages organizations within the tenant
ORGANIZATION   →  manages users within the organization
USER           →  base access
```

---

### Fragment File Convention

Use **one file per area**, each containing all profile variants as named Thymeleaf fragments.

```text
templates/fragments/
  home-sidebar.html    ← fragments: sidebarAdmin, sidebarTenant, sidebarOrganization, sidebarUser
  home-title.html      ← fragments: titleAdmin, titleTenant, titleOrganization, titleUser
  home-main.html       ← fragments: mainAdmin, mainTenant, mainOrganization, mainUser
```

Do **not** create one file per profile (e.g., `home-sidebar-admin.html`). Keep all variants co-located in the same file.

Each fragment is declared with `th:fragment`:

```html
<aside th:fragment="sidebarAdmin" class="sidebar-panel"> ... </aside>
<aside th:fragment="sidebarTenant" class="sidebar-panel"> ... </aside>
<aside th:fragment="sidebarOrganization" class="sidebar-panel"> ... </aside>
<aside th:fragment="sidebarUser" class="sidebar-panel"> ... </aside>
```

---

### Backend: FragmentController Pattern

Expose REST endpoints that accept a `profile` query parameter and return the correct Thymeleaf fragment reference.

```java
@GetMapping("/fragments/home/sidebar")
public String homeSidebar(@RequestParam(defaultValue = "USER") String profile) {
    return switch (resolveProfile(profile)) {
        case ADMINISTRATOR -> "fragments/home-sidebar :: sidebarAdmin";
        case TENANT        -> "fragments/home-sidebar :: sidebarTenant";
        case ORGANIZATION  -> "fragments/home-sidebar :: sidebarOrganization";
        case USER          -> "fragments/home-sidebar :: sidebarUser";
    };
}
```

Apply the same pattern for `/fragments/home/title` and `/fragments/home/main`.

**Profile resolution** must normalize input consistently:

```java
private UserProfile resolveProfile(String profile) {
    String normalized = profile.toUpperCase().replace("ROLE_", "").trim();
    return switch (normalized) {
        case "ADMIN", "ADMINISTRATOR" -> UserProfile.ADMINISTRATOR;
        case "TENANT"                 -> UserProfile.TENANT;
        case "ORGANIZATION", "ORG"   -> UserProfile.ORGANIZATION;
        default                       -> UserProfile.USER;  // safe fallback
    };
}
```

Always fall back to `UserProfile.USER` for unknown or missing profile values. Log a warning for unrecognized inputs.

---

### Frontend: Slot Loading Pattern

`home.html` defines three named slots with a server-side default (`USER` fragment), ensuring the page is functional even before JavaScript runs:

```html
<div id="home-sidebar-slot" th:insert="~{fragments/home-sidebar :: sidebarUser}"></div>
<div id="home-title-slot"   th:insert="~{fragments/home-title :: titleUser}"></div>
<div id="home-main-slot"    th:insert="~{fragments/home-main :: mainUser}"></div>
```

On `DOMContentLoaded`, JavaScript reads the authenticated user profile from storage and replaces each slot:

```javascript
const auth = JSON.parse(localStorage.getItem('velia.auth') || sessionStorage.getItem('velia.auth'));
const userProfile = normalizeProfile(auth?.profile?.profile ?? 'USER');

loadFragmentIntoSlot('home-sidebar-slot', `/fragments/home/sidebar?profile=${userProfile}`);
loadFragmentIntoSlot('home-title-slot',   `/fragments/home/title?profile=${userProfile}`);
loadFragmentIntoSlot('home-main-slot',    `/fragments/home/main?profile=${userProfile}`);
```

Profile normalization **must mirror backend logic** exactly:

```javascript
const normalizeProfile = (value) => {
    const n = value.toUpperCase().replace('ROLE_', '').trim();
    if (n === 'ADMIN' || n === 'ADMINISTRATOR') return 'ADMINISTRATOR';
    if (n === 'ORGANIZATION' || n === 'ORG')   return 'ORGANIZATION';
    if (n === 'TENANT')                         return 'TENANT';
    return 'USER';
};
```

Do **not** use `th:switch` or `th:if` inside templates for profile branching — keep that logic in the controller.

---

### Authentication Flow

```
POST /api/auth/login
  → response: { token, user: { profile: "ADMINISTRATOR|TENANT|ORGANIZATION|USER", ... } }
  → saved to localStorage/sessionStorage as "velia.auth"
  → redirect to /home?profile=<normalized>

GET /home
  → home.html renders with USER fragment defaults (server-side)
  → JavaScript reads profile from storage
  → fetches 3 fragment endpoints in parallel
  → replaces slot contents
```

The `?profile=` query parameter in the redirect is informational; the authoritative source is always the stored auth token.

---

### Security and Authorization

UI personalization **does not replace authorization**:

- `UserProfile` maps to Spring Security roles: `ADMINISTRATOR → ROLE_ADMIN`, `TENANT → ROLE_TENANT`, `ORGANIZATION → ROLE_ORGANIZATION`, `USER → ROLE_USER`.
- Role hierarchy is configured: `ROLE_ADMIN > ROLE_TENANT > ROLE_ORGANIZATION > ROLE_USER`.
- Backend APIs must enforce role-based access independently of what menu items are visible.
- Hiding menu items in the sidebar is a UX affordance, not a security control.

---

### CSS and JavaScript Ownership for Profile Areas

- **No profile-specific CSS files** — use the shared `template.css` for shell layout, sidebar, and content area styling.
- Use `common.css` only for design tokens (colors, spacing, radius, typography).
- Profile-specific visual differences should be handled via modifier classes on the fragment markup, not separate stylesheets.
- Profile-specific JavaScript behavior (if any) goes in a component-specific JS file or a shared domain library — not inline in `home.html`.

---

### When to Split vs Consolidate Fragment Variants

**Keep variants in the same file** when:
- Structure is similar and only labels, icons, or items differ.
- The fragment file stays readable with all variants co-located.

**Split into separate files** only when:
- A single fragment file becomes too large to navigate.
- A profile variant has fundamentally different structure and behavior.

---

### Testing Requirements per Profile

For each profile (`ADMINISTRATOR`, `TENANT`, `ORGANIZATION`, `USER`):

1. Log in and verify the correct sidebar variant loads.
2. Verify the correct title fragment renders.
3. Verify the correct main content widgets appear.
4. Verify top bar and right panel remain functional and unchanged.
5. Verify fallback: a USER default renders correctly when no profile is set.
6. Add regression checks when profile-to-fragment mapping changes in `FragmentController`.
