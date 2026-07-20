# coder

## NAME

`coder` — apply Kntnt's coding standard to any code-shaped task

## SYNOPSIS

```
/kntnt-code-skills:coder
/kntnt-code-skills:coder (help | --help | -h)
```

## DESCRIPTION

`coder` applies Kntnt's coding standard — PHP, JavaScript, TypeScript, Python, Bash, WordPress, Gutenberg blocks, Laravel, Svelte, SvelteKit, and any framework added later — to any code-shaped task: writing, refactoring, reviewing, debugging, or designing code, in any language. It auto-triggers on a code-related prompt; explicit invocation is available for a project or session where auto-triggering is disabled.

It is a **lazy bootstrap**: at trigger it loads only the standard's router (`lib/coding-standard/_index.md`), then pulls in each topic module the moment the working context proves a language or framework axis applies — never the whole standard up front — and keeps pulling more as new axes surface through the session. When a project has already scaffolded the standard into `agents.d/coding-standard/` (via `coding-standard`), it loads nothing from the plugin at all and defers to the project's own on-demand `AGENTS.md` References instead — the deliberate snapshot the harness already follows on its own.

`coder` is read-only on the project: it never writes the standard's files into a project — that is the sibling `coding-standard` skill's job.

## OPTIONS

| Option | Description |
|---|---|
| `help`, `--help`, `-h` | Print this manual page and stop. |

## EXAMPLES

Trigger automatically by asking for code work:

```
Refactor this function to use early returns.
```

Invoke explicitly, for a project or session with auto-triggering disabled:

```
/kntnt-code-skills:coder
```

## FILES

| File | Purpose |
|---|---|
| `lib/coding-standard/_index.md` | The router: module table, detection signals, canonical order. Loaded once per trigger. |
| `lib/coding-standard/<module>.md` | Loaded lazily, one per language/framework axis the working context proves applies. |
| `agents.d/coding-standard/` | When present, the project's own scaffolded snapshot of the standard — loaded instead of `lib/`. |
