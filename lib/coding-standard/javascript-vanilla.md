## JavaScript (browser, no TypeScript)

Plain browser-side JavaScript — scripts inside PHP or WordPress plugins (admin, public-facing) where TypeScript and a build step are not justified. For any non-trivial JavaScript, use TypeScript instead.

### Baseline

- ES2022 features, evergreen browsers only. No transpilation.
- IIFE wrapper with `'use strict'` at the top to isolate scope.
- Globals declared with a `/* global … */` comment block.
- Indentation: **4 spaces** (matches the in-plugin convention; no Biome on these files).
- Single quotes, semicolons present, trailing commas in multi-line literals.

### Style

- `const` by default, `let` only when reassignment is genuinely needed. Never `var`.
- Arrow functions for callbacks and short helpers.
- Template literals over string concatenation.
- Destructuring for objects and arrays from APIs and globals: `const { restUrl, nonce } = wpLocalizedConfig;`.
- `async` / `await` over `.then()` chains.
- Strict equality (`===` / `!==`) exclusively.
- `fetch` over `jQuery.ajax`. jQuery is used only when WordPress hands it to you (e.g. Select2 callbacks).

### Doc comments

JSDoc on every exported function and any non-trivial helper. Document parameter and return types, since TypeScript isn't.
