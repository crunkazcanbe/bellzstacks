#!/usr/bin/env bash
set -e
echo "🚀 Installing Upgraded Modular Stacks Engine Layout..."

/usr/bin/mkdir -p /usr/local/bin
/usr/bin/mkdir -p /usr/local/lib

/usr/bin/sudo /usr/bin/cp ./bin/stacks /usr/local/bin/
/usr/bin/sudo /usr/bin/cp ./lib/*.py /usr/local/lib/

/usr/bin/sudo /usr/bin/chmod +x /usr/local/bin/stacks

echo "✅ Sequence Complete. Core layout successfully deployed!"
