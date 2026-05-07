## TypeScript

This module covers TypeScript rules. It applies whenever the project
contains TypeScript code.

### Baseline

- TypeScript strict mode. Latest stable major.minor.
- Target ES2022 (revisit per the universal *Versions and targets* rule).
- Module system: ESM. `verbatimModuleSyntax` on. Include the `.js`
  extension in import specifiers (TS rewrites correctly, ESM at runtime
  needs it).
- `noUncheckedIndexedAccess`, `forceConsistentCasingInFileNames`,
  `isolatedModules` all on.

### Tooling overview

- **Biome** for both linting and formatting (replaces ESLint + Prettier).
- **Bun** as package manager, bundler, and test runner where the project
  is browser-side and standalone.
- For WordPress plugins, prefer the WordPress build pipeline
  (`@wordpress/scripts`) only when the plugin actually needs Gutenberg
  block integration; otherwise plain Bun + Biome is lighter.

### Formatter settings (Biome)

- Indentation: **2 spaces**.
- Line width: 100.
- Quotes: single.
- Semicolons: as needed (Biome's `asNeeded`).
- Trailing commas: all.

### Naming

| Element | Convention | Example |
|---|---|---|
| File | `kebab-case.ts` | `interval-set.ts`, `measurer.ts` |
| Test file (co-located) | `kebab-case.test.ts` | `timer.test.ts` |
| Class / interface / type / enum | `PascalCase` | `Measurer`, `EngagementMetrics` |
| Function / method / variable | `camelCase` | `createMeasurer`, `readingRatio` |
| Module-level constant (semantic value) | `camelCase` | `defaultConfig` |
| Compile-time / pure constant | `SCREAMING_SNAKE_CASE` | `DEFAULT_READING_SPEED` |
| Private class field | `#camelCase` (the JS private syntax) | `#remaining`, `#listeners` |

### Type rules

- Prefer `interface` over `type` for object shapes.
- Use `type` for unions, intersections, mapped types, and aliases that
  aren't purely object shapes.
- Mark properties `readonly` whenever they are not reassigned after
  construction.
- Avoid `any`. Use `unknown` when the type is genuinely unknown and
  narrow at the boundary.
- Use the `satisfies` operator to verify a literal against a type without
  widening it.
- Prefer literal/template literal types and discriminated unions over
  enum-style flags.

### Module rules

- **Named exports only.** No default exports anywhere.
- Each package has a single `index.ts` that re-exports the public API.
- Add-on packages depend on the core via `peerDependencies`, never
  `dependencies`.
- The core package has zero runtime dependencies in browser libraries
  designed for distribution.

### Class rules

- Private members use the `#` syntax, not the `private` keyword. The
  `#` form is enforced by the runtime; `private` is only enforced by the
  type checker.
- Constructor parameters typed and `readonly` where applicable.
- Getters for derived state; setters only when the class genuinely owns
  mutable state.
- Side effects in constructors are limited to what's required to
  satisfy invariants. Long-running setup goes in a separate `start()` /
  `init()` method.

### Function rules

- Pure where possible. Side effects pushed to the edges.
- Single responsibility. ~30 lines is a soft guideline, not a hard cap.
- Early returns to flatten nesting.
- More than three parameters: take an options object instead.
- DOM event listeners use `{ passive: true }` whenever applicable.

### Doc comments

Every public symbol carries a JSDoc/TSDoc block. The type system already
shows the shape — the comment explains the contract, the why, and the
non-obvious cases.

```ts
/**
 * Recalibrate the timer with a new duration, preserving current progress.
 *
 * If progress is 60% and the new duration is 10 s, remaining becomes 4 s.
 *
 * @param newDurationSeconds - New estimated reading time in seconds.
 */
recalibrate(newDurationSeconds: number): void { … }
```

### TypeScript project structure (library / monorepo)

```
project/
├── packages/
│   ├── core/                 ← Zero-dependency core package
│   │   ├── src/
│   │   │   ├── index.ts      ← Public API, re-exports only
│   │   │   ├── iife.ts       ← IIFE entry for <script src="…"> use
│   │   │   ├── <feature>.ts
│   │   │   ├── <feature>.test.ts   ← Co-located tests
│   │   │   └── types.ts      ← Shared interfaces and types
│   │   ├── package.json
│   │   └── tsconfig.json
│   └── <addon>/              ← Add-ons depend on core via peerDependencies
│       └── …
├── docs/                     ← Architecture, algorithm, conventions, …
├── tests/                    ← Cross-package and e2e (Playwright)
├── CLAUDE.md
├── AGENTS.md
├── README.md
├── biome.json
├── lefthook.yml
├── tsconfig.json
└── package.json              ← Workspaces, scripts
```

Tests are **co-located** with source (`timer.ts` + `timer.test.ts` in
the same folder). Cross-package and end-to-end tests live in `/tests`
at the repo root.

### TypeScript and JavaScript tooling

- **Bun** as package manager, bundler, test runner, and runtime.
- **TypeScript** for any non-trivial JavaScript code. Plain JavaScript
  is acceptable only where TypeScript adds friction without value
  (e.g. small WordPress admin scripts loaded via `wp_enqueue_script` —
  see the *JavaScript (browser, no TypeScript)* rules).
- **Biome** as the single linter and formatter (replaces ESLint and
  Prettier).
- **happy-dom** for DOM mocking in unit tests where Bun's runner does
  not cover the surface natively. Faster than jsdom.
- **Playwright** for end-to-end browser tests. Headless Chromium is
  the default browser.
- **Lefthook** for git hooks (format, lint, type-check on commit;
  full test suite on push to `main`).

### Tools deliberately not used

The default toolchain above replaces ESLint, Prettier, Jest, Husky,
npm, pnpm, yarn, Webpack, and Rollup. These tools are not forbidden,
but a specific project need is required to bring any of them in.
