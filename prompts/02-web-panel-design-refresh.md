PART B — MBGA Web Panel professional design refresh

Run this only AFTER Part A (stabilization and verification) has finished and all of its quality gates pass.
Part A says "do not redesign screens". That rule applies to Part A only. In Part B you may change the visual design, but you still must not add features, change business behaviour, or change backend code.

Project:

C:\Users\GauravSinghPal\Desktop\mbga-backend\frontend

The panel already works against the real backend. The problem is that it looks generic and unfinished. Make it look like a polished, trustworthy commercial LPG operations product that a business owner would be proud to use every day.

1. Do not break anything

- Do not add screens, features, API calls, fields, charts or data.
- Do not show fake numbers, fake trends, demo records or decorative "analytics".
- Do not change routes, permission checks, API modules, query keys, auth/session logic or error mapping.
- Keep every accessible name, button label, heading text and field label that tests rely on, unless you update the tests in the same change and explain why.
- Keep all existing tests passing. Do not delete tests to make them pass.
- Do not commit.

2. Review the current design first

Before changing anything:

- Start the app and capture screenshots of every screen at 1440px, 820px and 390px:
  sign in (both steps), Admin dashboard, merchants list, add merchant (form, review, success), merchant detail and staff tab, users, user detail (roles, access), roles, role detail (permissions, panel access, people), permissions, audit logs and drawer, my account, Merchant dashboard, delivery team list, add team member (driver and helper), team member detail, every "not available" page, not found, access denied, service unavailable.
- Save them under frontend/docs/design/before/.
- Write a short design critique (frontend/docs/design/CRITIQUE.md): what looks unprofessional and why. Be specific, for example: weak brand mark, plain login side panel, flat stat cards, weak visual hierarchy, too much empty space, inconsistent spacing, cramped or oversized filter bars, table readability, header feels empty, system font instead of a deliberate typeface.

Use the local development accounts documented in frontend/docs/LOCAL_TEST_ACCOUNTS.md (created in Part A) and the local OTP 1234.

3. Design direction

Brand feel: reliable, operational, calm, modern, Indian LPG distribution business. Not a generic admin template, not a startup landing page.

Colour:
- Deep navy as the primary brand colour (navigation, primary actions, headings).
- Warm LPG orange as the accent, used sparingly: the main call to action on a page, the active navigation indicator, brand mark, key highlights.
- Soft cool-neutral page background with white surfaces.
- Semantic colours only for meaning: green = active/approved/success, amber = pending/warning, red = blocked/error/destructive, blue = information/links.
- All text and meaningful UI must meet WCAG 2.1 AA contrast. Status must never rely on colour alone.

Typography:
- Use a deliberate professional typeface (Inter or a similar humanist sans). Self-host it (for example @fontsource, or font files in src/assets) instead of loading from a third-party CDN, with a system-font fallback and font-display: swap. Explain the choice and the bundle cost.
- Clear type scale: page title, section title, card title, body, label, helper, table text, small metadata.
- Tabular numbers for counts and dates.

Layout and density:
- An 8px spacing grid used consistently.
- Comfortable but efficient density for daily operational use. Tables should show more rows without feeling cramped.
- Consistent page structure: breadcrumb, title, one-line description, primary action on the right, then content.
- Sensible max content width on very wide screens.

Shape and depth:
- Consistent corner radius scale.
- Subtle borders first, very light shadows second. No glassmorphism, neon, heavy gradients or large decorative blobs.
- Motion only for feedback (menus, dialogs, drawers, toasts), 150–200ms, and fully disabled with prefers-reduced-motion.

Icons:
- Keep one consistent line-icon style (the existing inline SVG set may be refined). No emoji as icons. Every icon-only button keeps an accessible name.

4. Brand mark

- There is no official MBGA logo in the repository. Do not invent a logo that could be mistaken for an official trademark.
- Replace the current cramped "MBGA" text box with a clean, neutral wordmark treatment (for example a simple flame or cylinder-inspired geometric mark plus the "MBGA" wordmark) that is clearly a placeholder.
- Put it in one component so the official logo can be dropped in later. Document where to replace it.
- Update the favicon to match.

5. Screen-by-screen improvements

Sign in:
- Make the brand side panel look premium and purposeful (subtle pattern or illustration built with CSS/SVG, short value statements, trust note). No stock photos.
- A focused, well-balanced sign-in card: clear panel choice (Admin / Merchant), large readable mobile field with +91 prefix, strong primary button.
- OTP step: four large, well-spaced boxes, clear masked number, obvious "Change mobile number", clean countdown and resend area, error and loading states that look intentional.
- Excellent on phones.

App shell:
- Refined dark navy sidebar: better section spacing, clearer active state, hover and focus states, collapsed mode with tooltips, "Soon" tags that are visible but quiet.
- Header: page context on the left (or breadcrumb), panel label and user menu on the right. The user menu shows name, role and panel. Remove the feeling of empty space.
- Phone: proper drawer with overlay, close button and focus handling.

Dashboards (Admin and Merchant):
- Better stat cards: clear label, large number, short supporting text, subtle icon, clear link. Only real numbers from existing API calls.
- Clear sections with good hierarchy. "Needs attention" should stand out when it has items and be calm when empty.
- Recent activity as a readable timeline.
- No charts unless the existing data genuinely supports one; do not add charts in this task.

Lists (merchants, users, roles, delivery team, audit logs):
- Tidy filter bar that aligns on one row on desktop and stacks cleanly on smaller screens.
- Readable tables: clear header row, comfortable row height, hover state, aligned status badges, avatars/initials, secondary text in muted style, visible row action menu.
- Clean pagination footer.
- Phone: well-designed record cards, not squeezed tables.

Forms (add merchant, add team member, edit dialogs):
- Clear sections with titles and short descriptions, aligned two-column grid on desktop, single column on phones.
- Consistent label, hint, error and required-marker styling.
- Error summary that looks deliberate. Sticky action bar that looks clean.
- Review and success screens that feel like a real confirmation (clear summary, next step, obvious buttons).

Detail pages (merchant, user, role, team member):
- A strong header: avatar/initials, name, status badges, key metadata, actions on the right.
- Well-structured detail cards and tabs. Permission editor groups that are easy to scan.

States:
- Consistent loading skeletons that match the final layout (no layout jump).
- Friendly empty states with a simple neutral SVG illustration or icon and one clear action.
- Error, access denied, not found, service unavailable and "This feature is not available in the current backend release." pages that look designed, not like fallbacks. The unavailable pages must still show no data.

Feedback:
- Toasts, confirmation dialogs and drawers with consistent spacing, clear titles and correct button emphasis (destructive actions in red, cancel as secondary).

6. Implementation rules

- Keep the existing approach: design tokens in src/styles/tokens.css and component styles in CSS. Refactor global.css into smaller files by area if that makes it maintainable.
- Update components in src/components rather than styling pages one by one. Pages should mostly change through shared components and tokens.
- Do not add a large UI framework. If you add any package (for example a self-hosted font), explain why and its size.
- Keep keyboard access, visible focus rings, semantic headings, dialog focus trapping, Escape to close and screen-reader labels working.
- Test responsive behaviour at 1440px, 1280px, 1024px, 820px, 390px and 360px. The page body must never scroll horizontally; only tables may scroll inside their container.

7. Verification

- Capture the same screenshots again under frontend/docs/design/after/ and write frontend/docs/design/DESIGN_NOTES.md containing: the design decisions, colour and type tokens, component changes, before/after comparison for each screen, contrast checks for the main colour pairs, and where to replace the placeholder logo.
- Run a basic automated accessibility check on the main screens (for example axe with Playwright if already available, or document a manual keyboard and contrast check if not) and fix real issues.
- Run and report honestly:

  npm run typecheck
  npm run lint
  npm run test
  npm run build
  npm run test:e2e

- Re-run the real browser journey from Part A (Super Admin login → merchant list → create test merchant → logout → merchant login → create driver and helper → delivery team list → logout) and confirm it still passes with the new design.

8. Final response

Report:
- Design critique summary (before)
- Design direction and tokens chosen
- Components changed
- Screens improved
- Any new dependency and its size
- Accessibility and contrast results
- Responsive results per width
- Test, typecheck, lint, build and Playwright results (do not hide failures or warnings)
- Where the screenshots are
- Anything that could not be improved without a backend change or an official logo

Do not claim the redesign is complete unless all quality gates and the real browser journey pass. Do not commit.
