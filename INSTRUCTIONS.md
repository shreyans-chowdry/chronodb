# ChronoDB Workflow Instructions

## Repo & Users
- **Repo**: https://github.com/shreyans-chowdry/chronodb.git
- **Member A** (Owner): shreyans-chowdry
- **Member B** (Collaborator): swapniljain2024-ai

## Branch Structure
- `main` → production-ready code
- `develop` → integration branch (merge feature branches here)
- `feature/*` → individual task branches (created from `develop`)

## Workflow for Member B (swapniljain2024-ai)

### Starting a new task:
1. `git checkout develop`
2. `git pull origin develop`
3. `git checkout -b feature/<task-name>`
4. Do the work, stage, commit
5. `git push origin feature/<task-name>`
6. Open a Pull Request on GitHub from `feature/<task-name>` → `develop`
7. Ask Member A to review and merge

### After Member A merges to develop:
1. `git checkout develop`
2. `git pull origin develop`
3. Delete local feature branch: `git branch -d feature/<task-name>`

### Final merge (end of project):
- Member A merges `develop` → `main`

## Authentication
- HTTPS with Personal Access Token (PAT)
- PAT needs `repo` scope
- Stored in Windows Credential Manager under `git:https://github.com`
