---
name: Bug report
about: A module, the router, or the scaffolder produces the wrong outcome on a concrete input.
title: "[bug] "
labels: bug
assignees: ""
---

## Which module or component

Name the file (e.g. `skills/coder/general.md`, `skills/coder/php.md`, `skills/coder/SKILL.md`, `skills/coder/bin/scaffold`) and, where applicable, the section or rule you believe is misbehaving. If the issue spans several files, list each.

## Which language or framework

Which language or framework axis is in play (PHP, TypeScript, WordPress, Gutenberg blocks, plain JavaScript, Python, Bash, or a future axis)? If several apply at once (e.g. a WordPress block plugin is PHP + WordPress + TypeScript + WordPress-block), list them.

## Input

The exact prompt or task you gave the skill, or the exact `bin/scaffold` command line you ran. Paste it inside a fenced code block so whitespace, flags, and casing are preserved. If the input is long, attach it as a file or link to a gist.

```
your input here
```

## Observed outcome

What the plugin actually did — the code it wrote, the modules it loaded, or the scaffolder's output and exit code. Paste the relevant part.

## Expected outcome

What the module, the router flow, or the scaffolder says (or should say) the plugin should have done. Quote the rule text if you can.

## Environment

- Plugin version (from `.claude-plugin/plugin.json`):
- Client (Claude Code / Cowork) and version:
- For `bin/scaffold` issues: Bun version (`bun --version`):
- Operating system:

## Additional context

Anything else that helps reproduce the issue — the project profile, related runs, recent changes to your local copy, etc.
