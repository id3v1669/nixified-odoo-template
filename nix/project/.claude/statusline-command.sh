#!/usr/bin/env bash
# Claude Code statusline entry point. Logic lives in statusline.js next to this
# file; this just hands stdin to Node. stderr is dropped so a stray warning
# never leaks into the rendered line.
source "$(dirname "${BASH_SOURCE[0]}")/project-env.sh" 2>/dev/null || exit $?
exec node "$(dirname "$0")/statusline.js" 2>/dev/null
