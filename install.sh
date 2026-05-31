#!/bin/bash
# stacks installer
set -e

echo "Installing stacks..."

# Directories
mkdir -p /usr/local/lib
mkdir -p ~/.config/stacks

# Install main script
cp bin/stacks /usr/local/bin/stacks
chmod +x /usr/local/bin/stacks

# Install lib files
for f in lib/*.py; do
    cp "$f" /usr/local/lib/
done

echo "Done. Run: stacks ls"
echo "TUI:  stacks menu"
