#!/bin/sh
# Install the pre-commit leak check. Run once after cloning: sh scripts/install_hooks.sh
# (git hooks are local config and do not travel with the repo.)
set -e
hook=.git/hooks/pre-commit
cat > "$hook" <<'HOOK'
#!/bin/sh
python3 scripts/leak_scan.py || { echo "commit blocked by leak_scan"; exit 1; }
HOOK
chmod +x "$hook"
echo "pre-commit leak check installed"
