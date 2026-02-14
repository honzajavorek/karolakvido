# AGENTS Notes

Project workflow rules for coding agents in this repository:

- Always add Python dependencies with `uv add ...` (do not use ad-hoc installers).
- Always run tests with `uv run pytest`.
- Generally prefer `uv` for project-related operations (environment, running tools, dependency management).
- Avoid custom command patterns when an equivalent `uv` command exists.
