/**
 * Engine for the `doctor` skill: the heavy, judgement-laden half of the
 * project health check. The cheap deterministic checks live in
 * `scripts/doctor.py`; this workflow runs the analyses that need a model reading
 * real prose and real code. It returns STRUCTURED findings only — it applies no
 * fixes; the skill consolidates, prompts, and fixes.
 *
 * Launch it through the Workflow tool:
 *
 *   Workflow({
 *     scriptPath: "${CLAUDE_PLUGIN_ROOT}/skills/doctor/doctor.workflow.js",
 *     args: {
 *       projectDir: "/abs/path",          // project root the agents read
 *       inventory: {                       // which files are present
 *         agentsMd, claudeMd, readme, changelog, contributing, notice  // booleans
 *       },
 *       agentsDExtra: ["agents.d/releasing.md", ...],  // non-standard agents.d/* files
 *     },
 *   })
 *
 * Two passes:
 *   1. Structural (Sonnet, batched) — does each file match its expected shape?
 *   2. Reality (Opus, xhigh, per file) — does each claim still hold against the
 *      actual code / git state?
 *
 * Returns { findings: [...] } where each finding is
 * { category, severity, message, file?, remedy? }.
 */
export const meta = {
  name: 'doctor',
  description: 'Heavy read-only project analysis: structural shape + reality against code',
  phases: [{ title: 'Structural', model: 'sonnet' }, { title: 'Reality' }],
}

// What every finder returns: a list of findings, or an empty list when clean.
const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['findings'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['category', 'severity', 'message'],
        properties: {
          category: { type: 'string', description: 'e.g. agents-md, readme, changelog, notice' },
          severity: { type: 'string', enum: ['low', 'medium', 'high'] },
          message: { type: 'string' },
          file: { type: 'string' },
          remedy: { type: 'string' },
        },
      },
    },
  },
}

const config = args ?? {}
const projectDir = config.projectDir || '.'
const inventory = config.inventory || {}
const agentsDExtra = Array.isArray(config.agentsDExtra) ? config.agentsDExtra : []

// The canonical shapes the structural pass checks against, inlined so the agents
// do not have to cross into another plugin to learn them.
const AGENTS_SHAPE =
  'CLAUDE.md must be exactly `@AGENTS.md`. AGENTS.md is the always-loaded canon: a `# <project>` title, an optional authoritative Ground rules block, and a `## References` index with one `- \`path\` — read when …` line per agents.d/ file. Every file in agents.d/ must have a matching References line, a one-line "read when…" top line, and carry one concern. Flag bloat, missing bridge, orphaned agents.d/ files, and References pointing at absent files.'
const DOCS_SHAPE =
  'README follows the audience-layered order (badges → Description with Key features/The problem/How this helps → Requirements → Installation → Usage → optional FAQ → Questions, bugs, and feature requests → Development → How you can contribute → License → Changelog); the "Questions, bugs, and feature requests" body and the Keep-a-Changelog/SemVer line are fixed boilerplate. CHANGELOG follows Keep a Changelog with an `## [Unreleased]` section and SemVer. CONTRIBUTING carries a contribution-scope table, an inbound-licensing paragraph, a behaviour line, and how-to-contribute steps. NOTICE (Apache) carries project, copyright, and attribution.'

// --- Pass 1: structural (Sonnet, batched) ------------------------------------

const structuralFinders = []

structuralFinders.push(() =>
  agent(
    `Read the context-file layer of the project at ${projectDir}: ` +
      `${inventory.claudeMd ? 'CLAUDE.md, ' : ''}${inventory.agentsMd ? 'AGENTS.md, ' : ''}` +
      `and the non-standard agents.d/ files [${agentsDExtra.join(', ') || 'none'}] (ignore agents.d/coding-standard/, which scaffold.py owns). ` +
      `Check them against this shape: ${AGENTS_SHAPE} ` +
      `Report only real structural deviations as findings; an absent AGENTS.md/CLAUDE.md is not itself a finding.`,
    { label: 'structural:agents-md', phase: 'Structural', model: 'sonnet', schema: FINDINGS_SCHEMA },
  ),
)

structuralFinders.push(() =>
  agent(
    `Read the project docs at ${projectDir}: ` +
      `${inventory.readme ? 'README.md, ' : ''}${inventory.changelog ? 'CHANGELOG.md, ' : ''}` +
      `${inventory.contributing ? 'CONTRIBUTING.md, ' : ''}${inventory.notice ? 'NOTICE' : ''}. ` +
      `Check each present file against this shape: ${DOCS_SHAPE} ` +
      `Report only real structural deviations (missing required section, boilerplate paraphrased, wrong order). An absent optional file is not a finding.`,
    { label: 'structural:docs', phase: 'Structural', model: 'sonnet', schema: FINDINGS_SCHEMA },
  ),
)

// --- Pass 2: reality (Opus, xhigh, per file) ---------------------------------

const realityFinders = []

if (inventory.agentsMd) {
  realityFinders.push(() =>
    agent(
      `Verify AGENTS.md at ${projectDir} against reality. Read the actual code, config, and file tree, then check every load-bearing claim in AGENTS.md still holds (commands run, paths exist, named files/symbols are real, stated invariants are true). Report each stale or wrong claim as a finding; do not rewrite anything.`,
      { label: 'reality:agents-md', phase: 'Reality', effort: 'xhigh', schema: FINDINGS_SCHEMA },
    ),
  )
}

for (const file of agentsDExtra) {
  realityFinders.push(() =>
    agent(
      `Verify ${file} at ${projectDir} against reality. Read the code it describes and check every claim still holds. Report stale or wrong claims as findings; do not rewrite anything.`,
      { label: `reality:${file}`, phase: 'Reality', effort: 'xhigh', schema: FINDINGS_SCHEMA },
    ),
  )
}

if (inventory.readme) {
  realityFinders.push(() =>
    agent(
      `Verify README.md at ${projectDir} against reality. Read the actual code, install/usage steps, requirements, and any feature list, and check the README still describes what the project really does and how to install/use it. Report stale, missing, or wrong claims as findings; do not rewrite anything.`,
      { label: 'reality:readme', phase: 'Reality', effort: 'xhigh', schema: FINDINGS_SCHEMA },
    ),
  )
}

if (inventory.changelog) {
  realityFinders.push(() =>
    agent(
      `Verify CHANGELOG.md at ${projectDir} against reality, the way lib/changelog.md reconciles it: is the \`## [Unreleased]\` section in sync with the commits and working-tree changes since the last release tag? Run \`git -C ${projectDir} log\` / \`git -C ${projectDir} status --porcelain\` to compare. Report missing or inaccurate Unreleased entries as findings; do not edit the changelog.`,
      { label: 'reality:changelog', phase: 'Reality', effort: 'xhigh', schema: FINDINGS_SCHEMA },
    ),
  )
}

if (inventory.notice) {
  realityFinders.push(() =>
    agent(
      `Light attribution check of NOTICE at ${projectDir}: does it name the project, a copyright line, and the real attribution? Flag only clear omissions (vendored third-party code with no attribution, wrong project name). Report findings; do not rewrite.`,
      { label: 'reality:notice', phase: 'Reality', effort: 'xhigh', schema: FINDINGS_SCHEMA },
    ),
  )
}

// Run both passes concurrently; each finder is independent, so there is no
// cross-item dependency that would justify a barrier between them.
const results = await parallel([...structuralFinders, ...realityFinders])

const findings = results
  .filter(Boolean)
  .flatMap((result) => (Array.isArray(result.findings) ? result.findings : []))

return { findings }
