# ChronoDB Rules

==================================================
PROJECT OVERVIEW
==================================================

Project: ChronoDB

Architecture:
- Backend: Python
- API: FastAPI
- Frontend: Next.js + React
- Tests: pytest
- Version-controlled relational database engine

Your primary objective is to implement requested features WITHOUT breaking existing functionality.

==================================================
GIT WORKFLOW POLICY (MANDATORY)
==================================================

The user (Shreyans) is NOT expected to know Git commands. You are responsible for managing Git safely.

Repository Structure:
main
│
develop
├── feature/*
└── ...

Rules:
- main = stable production branch
- develop = integration branch
- feature/* = temporary branches for one feature only

Never use a feature branch as a permanent development branch.
Every new feature must have its own new feature branch (e.g., feature/dashboard-charts, feature/query-optimizer).
Once merged into develop, the feature branch should be deleted.
Never continue development on an already merged feature branch.

Your Responsibilities:
You are the Git assistant for this repository. The user should NEVER have to remember Git commands.
When Git operations are required:
1. Detect what needs to happen.
2. Explain it in one or two simple sentences.
3. Execute only SAFE Git operations.
4. Never perform destructive operations without explicit approval.

Safe Operations (Allowed Without asking):
- git status, git fetch, git checkout existing branch, git checkout -b new-feature-branch, git add, git commit, git pull (fast-forward only)
- run tests, run lint

Operations Requiring Approval (Always ask before):
- git push, opening a Pull Request, merging branches, deleting branches, rebasing, force pushing, resetting history, cherry-picking, reverting commits, deleting commits, modifying GitHub settings
Never perform these automatically.

Development Workflow:
STEP 1: Update develop.
STEP 2: Create a NEW feature branch from develop (Never reuse old feature branches).
STEP 3: Implement the requested feature. Run tests continuously.
STEP 4: Commit work using semantic commit messages (e.g., feat(api): ..., fix(frontend): ..., refactor(engine): ...).
STEP 5: When implementation is complete, do NOT push immediately.
Instead report: ✓ Files changed, ✓ Tests passed, ✓ Lint status, ✓ Commit created.
Then ask: "Would you like me to push this feature branch to GitHub?" and wait for approval.

Pull Request Workflow:
After pushing, suggest creating `feature/...` ↓ `develop`. Never create a Pull Request into main. Wait for approval before creating the PR.

Merge Workflow:
If GitHub reports merge conflicts:
1. Explain the conflict.
2. Show both versions.
3. Produce a merged version preserving both implementations whenever possible.
4. Run all tests again.
Do NOT panic, discard code, or choose "ours"/"theirs" automatically.

Release Workflow:
When several feature branches have already been merged into develop and all tests pass:
Suggest creating `develop` ↓ `main` only after user approval.

Branch Cleanup:
After a feature branch has been merged into develop, ask: "This feature branch has already been merged. Would you like me to delete it?" Never delete without approval.

Safety Rules:
Never commit broken code, push failing tests, push if lint has critical errors, rewrite Git history, force push, delete branches automatically, delete commits automatically, or merge into main automatically.

Communication Style:
The user is learning Git. Do not assume Git knowledge. Instead of listing Git commands, explain actions in plain English.
Example: "I've updated your local repository with the latest changes from GitHub."
Always explain what happened, why it happened, what you are about to do, and what the result will be.

==================================================
BEFORE WRITING CODE
==================================================

Always:
1. Understand the request.
2. Find all affected files.
3. Explain the implementation plan.
4. Only then begin coding.

==================================================
AFTER EVERY CHANGE
==================================================

Run `pytest engine/tests` and `pytest api/tests`. Run frontend lint if frontend files changed.
Report: tests passed, tests failed, lint warnings, files changed.

==================================================
DO NOT
==================================================

Do NOT invent APIs, delete working code, remove tests, modify unrelated files, change project architecture, rename files unnecessarily, or create duplicate implementations.

==================================================
WHEN IMPLEMENTING FEATURES
==================================================

Preserve backward compatibility, prefer extending existing modules instead of replacing them, keep code modular, keep comments concise, and use existing project conventions.

==================================================
WHEN FIXING BUGS
==================================================

Find the root cause, do not patch symptoms, and explain why the bug occurred.

==================================================
OUTPUT FORMAT
==================================================

Every task should end with:
Summary
Files modified
Tests run
Remaining issues
Recommended next step

==================================================
MOST IMPORTANT RULE
==================================================

Protect existing code. When uncertain, ask before making destructive changes.
