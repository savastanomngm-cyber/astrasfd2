#!/bin/bash
set -u
cd "$(dirname "$0")" || exit 1
export PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:/Library/Frameworks/Python.framework/Versions/3.12/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

python_bin=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        python_bin="$(command -v "$candidate")"
        break
    fi
done

if [ -z "$python_bin" ]; then
    printf '\nInstall Python 3.12 (macOS universal2 installer) from python.org, then open this launcher again.\n'
    open "https://www.python.org/downloads/macos/"
    read -r -p "Press Return to close. "
    exit 1
fi

printf '\nStarting Gamma Lab. First launch installs dependencies and needs internet.\n'
printf 'Your browser will open at http://localhost:8501. Keep this window open.\n'
printf 'To stop: press Control+C. Back up the entire data folder to preserve your research.\n\n'
"$python_bin" launch.py --server.headless=false --server.port=8501
status=$?
if [ "$status" -ne 0 ] && [ "$status" -ne 130 ]; then
    printf '\nGamma Lab could not start. Review the message above. If port 8501 is in use, close the other Gamma Lab window first.\n'
    read -r -p "Press Return to close. "
fi
exit "$status"
