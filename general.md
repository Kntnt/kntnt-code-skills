# Coding Standards

This document defines the project's coding standard. The general rules
below apply to all code in the project. Language- and framework-specific
rules follow in their own sections (PHP, WordPress, TypeScript, plain
JavaScript). Only the sections that match the project's actual shape
are included.

## Priority order

When two rules conflict, the higher-priority rule wins:

1. **This document and its companion modules.** Together they are the
   project's coding standard.
2. **The recommended coding standard for the language** — PSR-12 for
   PHP, the WordPress Coding Standards for WordPress projects, the
   TypeScript handbook style, MDN's JavaScript style, etc.
3. **Best practice** — well-reasoned community advice (Airbnb JS,
   Clean Code, the WordPress Plugin Handbook, etc.).
4. **Widely accepted conventions** — what most code in the wild looks
   like.

## Design philosophy

These principles often conflict. The task is to find the design that
best honours all of them — not to apply each mechanically in sequence.
When in doubt, start with YAGNI and work down the list.

**YAGNI** — Implement only what the current requirement demands. Do
not create abstractions until more than one concrete implementation
exists.

**KISS** — Prefer the simpler solution. Complexity must justify itself
through a concrete, present requirement.

**DRY** — Each piece of knowledge has one authoritative source.
Extract duplication only when two things represent the same concept —
not merely similar syntax.

**TDD** — Write a failing test before writing production code. Follow
Red/Green/Refactor. Structure each test as Arrange-Act-Assert with a
name that states the expected behaviour.

**Deep modules** — A module's external interface must be narrow and
simple relative to the complexity it hides. This depth creates a clean
seam for mocking and is the primary quality metric for a module
boundary. The external interface is a commitment; design it as if it
cannot be changed.

**SOLID** applies inside a module — to the internal structure of classes
and components, not to the module's external interface:

- **SRP** — one reason to change per class.
- **OCP** — extend through new code, not by modifying existing code.
- **LSP** — subtypes must fully honour the base type's contract.
- **ISP** — internal components depend only on the interface slice they
  actually use. Decompose large internal interfaces into focused ones.
- **DIP** — depend on abstractions; inject dependencies.

**Boundary rule**: ISP decomposition is an internal detail and must
never surface in the module's external interface. The external
interface stays deep.
   
## Universal rules

### Language

- All identifiers (classes, interfaces, enums, traits, functions, methods,
  variables, constants, properties, type parameters, etc.) are in **English**.
- All comments — file-level, block-level, end-of-line, PHPDoc, JSDoc, TSDoc —
  are in **English**.
- All technical documentation (`README.md`, `CLAUDE.md`, `AGENTS.md`, files
  in `docs/`) is in **English**.
- User-facing strings are translatable and may be authored in any language;
  the source string in `__()` / `gettext()` calls is English.

### Versions and targets

- Always use the latest stable major.minor of any chosen language.
- For browser-targeted code, target the most recent edition of
  ECMAScript supported by the current stable releases of Safari,
  Firefox, Chrome, and Edge. In practice this currently means **ES2022**;
  revisit the target as evergreen support for newer editions catches up.
- No polyfills, no transpiler-emitted runtime helpers for older
  targets.

Specific version requirements per language live in the language modules.

### Code is read as prose

Code is read as prose. The reader is always a senior developer fluent
in the language and the framework. Loosely:

- A file is a chapter or short essay.
- A class or function is a section.
- A *paragraph* (Swedish *stycke*) — a group of consecutive statements
  that logically belong together — is the basic unit of structure
  inside a block, with a `//` comment as its topic sentence.
- A statement is a sentence.

This shapes how blocks are paragraphed and how comments are written.
The next section is the most central rule in this whole standard:
follow it carefully.

### Paragraphs and comments

**Paragraphing inside blocks.** Inside any block — a function body, a
loop body, an `if` / `else` branch, a `try` / `catch` branch — group
consecutive statements that logically belong together into a *paragraph*
(*stycke*). A paragraph has:

- No blank line between its statements.
- A single-line `//` comment above it that names what the paragraph
  does. The comment is a topic sentence, not an explanation; it lets
  the reader skim and skip.
- A blank line above the comment and a blank line below the last
  statement — even when the paragraph is the first or last thing in
  the enclosing block, so it sits flush against the opening `{` or
  the closing `}`.

A *trivial* paragraph — a lone `return $x;`, a single `global $wpdb;`,
a one-line assignment whose intent the surrounding code makes obvious —
may stand without a `//` comment. **The blank-line rule still applies,
though**: when the other paragraphs in the same block are separated by
blank lines, the trivial one is too. The first line after `{` must not
be jammed against the brace when other paragraphs breathe; a closing
`return` must not sit immediately above `}` either. Visual consistency
across the block matters.

```php
public function dispatch( string $token ): void {

    // Reject malformed tokens — defense-in-depth in case the upstream
    // validator is bypassed.
    if ( ! $this->validator->is_valid( $token ) ) {
        $this->send_error( 400 );
    }

    // Resolve the token to a target record; 404 when missing.
    $record = $this->repository->find_by_token( $token );
    if ( ! $record ) {
        $this->send_error( 404 );
    }

    // Forward incoming query parameters to the redirect target and dispatch.
    $params = array_map( 'sanitize_text_field', $_GET );
    $target = add_query_arg( $params, get_permalink( $record->id ) );
    wp_safe_redirect( $target );
    exit;

}
```

The example is in PHP but the rule is identical in TypeScript and
plain JavaScript.

**Single-paragraph block — the introducing comment absorbs the
explanation.** When a block consists of one paragraph that needs no
explanation of its own, drop both the `//` comment and the surrounding
blank lines, and make sure the comment that introduces the **enclosing
statement** carries everything a reader needs. For a function body that
introducing comment is the PHPDoc / JSDoc; for an `if` / `else` /
`while` / `for` / `try` body it is the `//` comment that sits above the
control statement.

```php
/**
 * Registers the custom query variable so WordPress preserves it through
 * the rewrite engine.
 */
public function add_query_var( array $vars ): array {
    $vars[] = 'my_query_var';
    return $vars;
}

// Refresh the access token only when the cache misses; a hit is the
// fast path.
if ( ! $cached_token ) {
    $token = $this->oauth->refresh();
    $this->cache->set( 'access_token', $token, 3500 );
}
```

**Doc comments.** Every file, class, interface, enum, trait, function,
method, public property, and exported constant carries a doc comment
(PHPDoc / JSDoc / TSDoc). Include the why, the contract, and edge cases —
not the what. Use `@param`, `@return`, `@throws`, `@since`, `@example`
where they add real value.

**End-of-line comments.** Use sparingly, only where a reader could plausibly
miss a subtle but critical detail (a magic constant chosen for a reason, a
non-obvious off-by-one, a workaround for a known platform bug).

**Audience.** All comments are written for an experienced developer reading
the file for the first time. Do not restate what the code already shows.
Do not write tutorials, do not address juniors, do not narrate the obvious.

**Line wrapping.** Comments wrap at column 80. Code may go wider where it
improves readability — see formatter settings per language below.

### Whitespace

- **No vertical alignment of `=` or `=>`.** Do not align assignment
  operators or array arrows across multiple lines. Single-space the
  operator and move on. The realignment churn on every edit is a real
  cost and the visual benefit is negligible for a senior reader.
- **No padding inside short collections.** Short array literals stay on one
  line: `[1, 2, 3]`, not split.
- **No gratuitous line breaks** in parameter lists. Pass parameters on one
  line unless the line genuinely becomes hard to read or exceeds the
  formatter's max line width.
- **Motivated line breaks are fine.** Break an array literal across lines
  when its elements naturally form a list or a matrix — for example, lookup
  tables, observer thresholds, route definitions, fixture rows. The
  break-or-not decision is content-driven, not character-count-driven.

```php
// Motivated: the elements form a fixed list.
$thresholds = [ 0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0 ];

// Motivated: the elements form a matrix.
$routes = [
    [ 'GET',  '/clicks',      'list_clicks' ],
    [ 'POST', '/conversions', 'record_conversion' ],
    [ 'GET',  '/health',      'health_check' ],
];

// Unmotivated: do not split a short call onto multiple lines.
$user = create_user( $name, $email, $role );
```

### Modern syntax

Always prefer the modern construction over the legacy one. Use syntactic
sugar where the language offers it: nullish coalescing, null-safe operator,
spread, destructuring, arrow functions, match/switch expressions, pattern
matching, template literals. Specific examples are in the language modules.

### Identifiers

- Names are self-documenting. Avoid abbreviations except well-established
  ones (`url`, `id`, `db`, `i` in tight loops).
- No magic strings or numbers in business logic — extract them to named
  constants or enum cases.
- Boolean variables and methods read as predicates: `isReady`, `hasConsent`,
  `should_retry()`.

### Naming and prefixes

Wherever there is a real risk of name collision in a global registry —
WordPress plugins and themes are the canonical case, but the same logic
applies to npm package names, browser globals, custom DOM events, and
similar — use a project prefix:

- **`kntnt-`** (with hyphens) where the surrounding convention requires
  hyphens: plugin/theme directory names, plugin slugs, text domains,
  REST namespaces, file paths, CSS class names, npm package names,
  custom HTML data attributes.
- **`kntnt_`** (with underscores) where the surrounding convention
  requires underscores: PHP function names, hook names, option keys,
  transient keys, post-type slugs, capability slugs, user-meta keys,
  JavaScript globals.

After the prefix comes the project's own name, then one or more words
describing the purpose:

```
kntnt-<project>                        ← plugin slug, repo name, dir name
kntnt_<project>_<purpose>              ← hook, option, post-type slug
kntnt-<project>-<purpose>              ← CSS class, REST endpoint segment
```

The project name itself does **not** start with `kntnt` — the prefix
provides that segment exactly once. A project called simply `<project>`
gets the slug `kntnt-<project>`, not `kntnt-kntnt-<project>`; its hooks
are `kntnt_<project>_<purpose>`, not `kntnt_kntnt_<project>_<purpose>`.

When the project name is long, an abbreviation may be used in
identifiers where length matters (hooks, option keys, post-type slugs).
The plugin's own `README.md` documents the abbreviation. Human-facing
places — the plugin name, the repository name, the documentation —
keep the full name.

PHP namespaces follow the same composition rule with their own casing.
The root is `\Kntnt`, then the project's name (without re-prefixing) in
`Pascal_Snake_Case`, then any sub-namespaces:

```
\Kntnt\<Project>                       ← root namespace for the project
\Kntnt\<Project>\<Sub>\<Class_Name>    ← organised further as needed
```

Never `\Kntnt\Kntnt_<Project>\…` — the `\Kntnt` segment already provides
the prefix.

**When the prefix is not needed.** The prefix exists to prevent
collisions in a global registry. Where there is no global registry —
inside a TypeScript package whose public API is a set of named
exports, inside a Laravel application's `App\` namespace, inside a
SvelteKit project's `$lib`, etc. — the package or namespace boundary
already provides the isolation, and an extra `kntnt` prefix is noise.
Apply the prefix where collisions can happen (WordPress hooks, npm
package names published to a public registry, browser globals,
custom DOM events, custom HTML data attributes); skip it where they
cannot.

## Universal tooling

The tools below apply to every project regardless of language. Tools
specific to a language live in that language's module. Substitutions
are allowed when a project has specific constraints; in that case the
substitution is documented in the project's `README.md`.

### Version control, hosting, and CI

- **Git** for local version control.
- **GitHub** for the remote, issues, pull requests, releases, and code
  review.
- **GitHub Actions** for continuous integration.

## CLAUDE.md / AGENTS.md convention

The project root contains both `CLAUDE.md` and `AGENTS.md`.

- `CLAUDE.md` is the entry point for Claude Code. It uses `@`-imports
  to pull in `AGENTS.md` and the relevant files in `docs/`, including
  this file (`docs/coding-standards.md`).
- `AGENTS.md` is the universal AI-agent file. Other tools (Copilot,
  Cursor, Codex, etc.) read it directly.

Both files reference this document so that any AI agent working on
the codebase has the coding standard in context before writing code.
