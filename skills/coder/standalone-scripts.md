# Standalone scripts — choosing and packaging the language

A meta-rule the `coder` bootstrap loads on demand, and only when its language detection has found nothing — typically when Thomas asks for a standalone script in isolation, with no surrounding project context to lock the language down. The bootstrap pulls this file in at that moment; it is never loaded otherwise.

## When this applies

Both of these must hold:

1. The task is to create a standalone script — not a class, not a function in an existing file, not part of a larger codebase.
2. No language is given by the context.

When the context already pins the language, the bootstrap's normal lazy flow wins and this file does nothing:

- A WordPress or PHP codebase → PHP.
- A TypeScript or JavaScript project → TypeScript on Bun (per the TypeScript module's defaults).
- An explicit language in the prompt ("write me a Python script", "write a bash script") → that language.

In all those cases, pull in and apply the matching language module directly instead of reading this file.

## Choosing the language

When the rule fires, pick the language by this order:

1. **TypeScript on Bun** — the default.
2. **Python (uv + PEP 723)** — only when a mature library makes Python the obvious choice for the task at hand.
3. **PHP** — when the script must live long untouched or shares code with a PHP codebase.
4. **Bash** — short, pure orchestration only.

Never default to Python merely because the task is "a script". Then pull in the matching language module (`typescript.md`, `python.md`, `php.md`, or `bash.md`) and apply it the same way the bootstrap's normal flow does.

## Packaging

The packaging shape depends on the script's target directory, not on its language.

**In a directory named `bin/`** → *command-style*. The script is intended to be invoked as a unix command:

- Filename has no extension.
- First line is a shebang (see below).
- File is executable (`chmod +x`).

This applies whether or not `bin/` happens to be on `PATH`. Making a command globally available is the user's decision — never the script's. Never modify `PATH`.

**Anywhere else** → *internal*. The script is invoked by another script, a skill, or a tool, not by a human as a command:

- Filename keeps its extension (`.ts`, `.py`, `.php`, `.sh`).
- No shebang.
- Caller invokes it explicitly: `bun foo.ts`, `php foo.php`, `uv run foo.py`, `bash foo.sh`.

**Shebangs** are env-based without exception:

| Language | Shebang |
|---|---|
| Bash | `#!/usr/bin/env bash` |
| Python | `#!/usr/bin/env -S uv run --script` |
| TypeScript | `#!/usr/bin/env bun` |
| PHP | `#!/usr/bin/env php` |

Never `#!/bin/bash` — Apple's `/bin/bash` is frozen at 3.2 and `bash.md` calls for Bash 5+.

**Single-file dependencies.** When a standalone script needs third-party packages, pin them inline so the file is self-contained:

- **Bun / TypeScript** — pin an exact version in the import specifier (no `^` or `~` ranges): `import { x } from "pkg@1.2.3";`. Bun auto-installs on first run.
- **Python** — declare dependencies and `requires-python` via PEP 723 inline metadata at the top of the file (see `python.md`). `uv run` resolves the environment automatically.
