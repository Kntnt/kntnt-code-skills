## WordPress

This section extends the PHP rules with rules specific to WordPress plugins and themes. It applies in addition to (and in places overrides) the PHP rules.

### Surface style — WordPress flavour (overrides PSR-12)

WordPress code follows the WordPress Coding Standards rather than PSR-12:

| Question | Convention |
|---|---|
| Indentation | Tabs (display as 4 cols) |
| Inside `(` / `)` | Padded: `if ( $x === null )`, `foo( $a, $b )` |
| Variables / properties | `$snake_case` |
| Methods / functions | `snake_case` |
| Classes / interfaces / enums / traits | `Pascal_Snake_Case` (e.g. `User_Repository`) |
| Class constants | `SCREAMING_SNAKE_CASE` |
| Namespace segments | `Pascal_Snake_Case` |

The `Pascal_Snake_Case` class form (`User_Repository`) is the WordPress flavour: the underscore-flavoured readability of WordPress identifiers combined with a valid PSR-4 class name. The corresponding file is `classes/User_Repository.php` — exact match, case-sensitive.

### Deliberate deviations from WP-CS — do not "fix" these

WordPress conventions otherwise apply, but the following four points deliberately depart from WP-CS because the alternative is clearly superior. They are not oversights. Do not "correct" them toward upstream WP-CS in code reviews, refactors, or new files:

- **`[ ... ]` over `array(...)`** — modern PHP.
- **PSR-4 filenames over `class-classname.php`** — the autoloader maps `User_Repository` to `User_Repository.php`, not `class-user-repository.php`.
- **Namespaces over global function prefixes** — PHP code lives inside `\Kntnt\<Project>` rather than under a `kntnt_` function-name prefix. The prefix is still used for identifiers that live in a global registry — see *Naming and prefixes* in the universal rules.
- **Yoda is not required** — natural order by default, Yoda only when it genuinely improves readability (see the PHP rules).

### File layout in WordPress projects

WordPress plugins use `classes/` rather than `src/` as the PSR-4 source directory:

```
\Kntnt\<Project>\Click_Handler              →  classes/Click_Handler.php
\Kntnt\<Project>\Conversion\Reporter        →  classes/Conversion/Reporter.php
```

Otherwise the PSR-4 rules from the PHP section apply.

### Security and i18n

- All SQL via `$wpdb->prepare()`. No raw interpolation.
- All admin URLs via `admin_url()` / `wp_nonce_url()`.
- Sanitise every superglobal access. No bare `$_GET['foo']`.
- All user-facing strings translatable: `__()`, `_e()`, `esc_html__()`, `esc_attr_e()` with the correct text domain.
- Output is escaped at the point of output: `esc_html`, `esc_attr`, `esc_url`, `wp_kses_post`.
- Errors are silent toward visitors. Diagnostics go to a plugin-managed log file or `error_log()`.
- Capabilities, not roles, gate admin actions.

### WordPress plugin project structure

```
kntnt-<name>/
├── kntnt-<name>.php          ← Main plugin file: header, PHP version
│                                guard, autoloader, Plugin::get_instance()
├── autoloader.php            ← PSR-4 autoloader for the plugin namespace
├── install.php               ← Activation: capabilities, migrator, cron,
│                                rewrite flush. Not autoloaded.
├── uninstall.php             ← Complete data removal. Runs without
│                                autoloader; uses fully qualified calls.
├── README.md                 ← Human-facing documentation
├── CLAUDE.md                 ← AI agent guidance (imports AGENTS.md,
│                                docs/*.md as needed)
├── AGENTS.md                 ← Universal AI agent instructions
├── classes/                  ← PSR-4: <Class_Name>.php
│   ├── Plugin.php            ← Singleton, component wiring, hooks
│   ├── Migrator.php
│   ├── Settings.php
│   ├── Logger.php
│   └── …
├── migrations/               ← Version-based migrations: <X.Y.Z>.php,
│                                each returns function(\wpdb): void
├── js/                       ← Plain ES2022 scripts, no build
├── css/
├── languages/                ← .pot, .po, generated .mo
├── docs/                     ← Specs the AI and humans both read
│   ├── architecture.md
│   ├── coding-standards.md   ← Project-specific overrides (rare)
│   ├── file-structure.md
│   ├── security.md
│   ├── testing-strategy.md
│   └── …
└── tests/
    ├── Unit/                 ← Pest + Brain Monkey + Mockery
    ├── JS/                   ← Vitest + happy-dom (or jsdom)
    └── Integration/          ← Bash + WordPress Playground / DDEV
```

The bootstrap path is fixed: `kntnt-<name>.php` → guard PHP version → require `autoloader.php` → register activation/deactivation hooks → call `Plugin::get_instance()`. The `Plugin` constructor instantiates all components in dependency order and registers their WordPress hooks.

### WordPress-specific tooling

These tools complement the general PHP tooling.

- **Brain Monkey** + **Mockery** for mocking WordPress functions and collaborator dependencies in unit tests.
- **`szepeviktor/phpstan-wordpress`** as the PHPStan extension that teaches static analysis about WordPress core.
- **WordPress Playground** (WASM PHP + SQLite) for end-to-end integration tests. The whole stack spins up in 1–2 seconds without a server, which keeps CI fast and the local feedback loop tight. Playground is the default. Use it whenever it suffices — which is the great majority of cases.

  Only fall back to **DDEV-based** integration tests when Playground genuinely cannot exercise the behaviour under test: MySQL-specific SQL, database-level concurrency, transaction or locking semantics, missing PHP extensions, or multi-process scenarios such as cron jobs and queue workers. DDEV-based tests are the exception, are scoped narrowly to the case that requires them, and stay out of the fast PR-time test suite. Run Playground from the command line via `@wp-playground/cli`.
