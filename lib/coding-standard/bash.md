## Bash

Applies whenever the project contains Bash code — standalone scripts and short orchestration glue.

### Baseline

- GNU Bash 5+ from a current source (Homebrew on macOS). Not POSIX `sh`, not Apple's frozen `/bin/bash` 3.2.
- Safety preamble at top of every script: `set -euo pipefail`.
- Shebang, when present: `#!/usr/bin/env bash`. Never `#!/bin/bash`. Packaging shape (command-style in `bin/` vs internal) follows the universal *Standalone-script packaging* rules in the general module.

### Style

- Quote every expansion: `"$var"`, `"${arr[@]}"`.
- `[[ ... ]]` for conditionals, never `[ ... ]`.
- `$( ... )` for command substitution, never backticks.
- Prefer builtins and parameter expansion over spawning external processes — `${var##*/}` over `basename "$var"`, `${var%.*}` over `sed` trimming.

### Structure

- Decompose into functions. Top-level code is the entry point; rest is named functions.
- `local` for every function-scoped variable.
- Arrays and associative arrays for collections, never space-delimited strings.
- `trap ... EXIT` for cleanup of temp files and child processes.
- Meaningful exit codes. `0` for success, distinct non-zero codes for documented failure modes.

### Doc comments

Leading `#` block at top of script: what it does, arguments, exit codes, required environment or dependencies. Function-level `#` blocks for non-trivial functions.

### When Bash is the wrong tool

Bash is for short, pure orchestration. Escalate to another language as soon as the script needs real data structures beyond what `jq` can express, persistent state, unit tests, or more than a single shellcheck-clean file.

### Bash tooling

- **shellcheck** — every script must pass `shellcheck` without suppressions. Suppress only with an inline comment naming the rule and explaining why.
- **shfmt** for formatting.
