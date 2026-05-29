## JavaScript (browser, no TypeScript)

This section covers plain browser-side JavaScript — typically scripts
inside PHP or WordPress plugins (admin scripts, public-facing scripts)
where introducing TypeScript and a build step is not justified. For
any non-trivial JavaScript, use TypeScript instead.

### Baseline

- ES2022 features, evergreen browsers only. No transpilation.
- IIFE wrapper with `'use strict'` at the top to isolate scope.
- Globals declared with a `/* global … */` comment block.
- Indentation: **4 spaces** (matches the in-plugin convention; no Biome
  on these files).
- Single quotes, semicolons present, trailing commas in multi-line
  literals.

### Style

- `const` by default, `let` only when reassignment is genuinely needed.
  Never `var`.
- Arrow functions for callbacks and short helpers.
- Template literals over string concatenation.
- Destructuring for objects and arrays from APIs and globals:
  `const { restUrl, nonce } = wpLocalizedConfig;`.
- `async` / `await` over `.then()` chains.
- Strict equality (`===` / `!==`) exclusively.
- `fetch` over `jQuery.ajax`. jQuery is used only when WordPress hands it
  to you (e.g. Select2 callbacks).

### Doc comments

JSDoc on every exported function and any non-trivial helper. Use it to
document parameter and return types where TypeScript isn't doing it for
you.
