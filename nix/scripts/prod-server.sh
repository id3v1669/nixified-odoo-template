# shellcheck shell=bash
# SSH into the production server using the project-local SSH config.
if [ -z "${!PROJECT_DIR_VAR}" ]; then printf -v "$PROJECT_DIR_VAR" '%s' "$(pwd)"; fi
echo "Connecting to production server..."
if [ -n "$PROD_WEB_URL" ]; then
    echo "URL: $PROD_WEB_URL"
fi
ssh -F "${!PROJECT_DIR_VAR}/.ssh/config" prod
