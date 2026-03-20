#!/bin/sh
# Install git hooks from .githooks/ into the local repo's .git/hooks/
# Run once on each machine after cloning: ./scripts/install-hooks.sh
REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$REPO_ROOT/.githooks"
GIT_HOOKS="$REPO_ROOT/.git/hooks"

for hook in "$HOOKS_DIR"/*; do
    name="$(basename "$hook")"
    target="$GIT_HOOKS/$name"
    cp "$hook" "$target"
    chmod +x "$target"
    echo "Installed $name → $GIT_HOOKS/"
done

# Also set hooksPath so `git` finds them automatically (Git 2.9+)
git config core.hooksPath "$HOOKS_DIR"
echo "Set core.hooksPath = $HOOKS_DIR"
echo "Done. All .sh scripts will be chmod +x after every merge/pull."
