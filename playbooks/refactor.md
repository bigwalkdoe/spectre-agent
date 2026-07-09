# Refactor a Module

## Steps

1. Read the full module — understand all inputs, outputs, side effects
2. Identify the goal — why are we refactoring? (improve readability, reduce duplication, extract responsibility, prepare for new feature)
3. Extract pure functions from mixed impure/pure code
4. Split large functions into smaller focused ones
5. Rename variables/functions for clarity (follow existing conventions)
6. Move code to appropriate files/modules
7. Update imports across the codebase
8. Run lint, typecheck, and full test suite
9. Verify no behavior changed
