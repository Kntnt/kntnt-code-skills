## Bash

This section covers Bash rules. It applies whenever the project contains Bash code — typically standalone scripts and short orchestration glue.

### Baseline

- GNU Bash 5+, installed from a current source (Homebrew on macOS). Not POSIX `sh`, and explicitly not Apple's frozen `/bin/bash` 3.2.
- Safety preamble at the top of every script: `set -euo pipefail`.
- When the script carries a shebang, it is `#!/usr/bin/env bash`. Never `#!/bin/bash`.

### Style

- Quote every expansion: `"$var"`, `"${arr[@]}"`. Unquoted expansions are bugs waiting to happen.
- `[[ ... ]]` for conditionals, never `[ ... ]`.
- `$( ... )` for command substitution, never backticks.
- Prefer builtins and parameter expansion over spawning external processes — `${var##*/}` over `basename "$var"`, `${var%.*}` over trimming with `sed`.

### Structure

- Decompose into functions. Top-level code is the script's entry point; the rest is named functions.
- `local` for every function-scoped variable. Globals are a smell.
- Arrays and associative arrays for collections, never space-delimited strings.
- `trap ... EXIT` for cleanup of temp files and child processes.
- Meaningful, intentional exit codes. `0` for success, distinct non-zero codes for documented failure modes.

### Doc comments

A leading `#` comment block at the top of the script describes what it does, its arguments, its exit codes, and any required environment or dependencies. Function-level `#` blocks for non-trivial functions.

### When Bash is the wrong tool

Bash is for short, pure orchestration. Escalate to another language as soon as the script needs real data structures beyond what `jq` can express, persistent state, unit tests, or anything that would warrant more than a single shellcheck-clean file. Grow into another language rather than growing the Bash script.

### Bash tooling

- **shellcheck** — every script must pass `shellcheck` without suppressions. Suppress only with an inline comment that names the rule and explains why.
- **shfmt** for formatting.
