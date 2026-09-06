# shellcheck shell=bash
# SSH into the test server using the project-local SSH config.
if [ -z "${!PROJECT_DIR_VAR}" ]; then printf -v "$PROJECT_DIR_VAR" '%s' "$(pwd)"; fi
echo "Connecting to test server..."
if [ -n "$TEST_WEB_URL" ]; then
    echo "URL: $TEST_WEB_URL"
fi
ssh -F "${!PROJECT_DIR_VAR}/.ssh/config" test
