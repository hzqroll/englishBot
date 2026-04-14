#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DEPLOY_HOST:-}" ]]; then
  echo "DEPLOY_HOST is required, example: DEPLOY_HOST=110.40.137.26 $0"
  exit 1
fi

DEPLOY_USER="${DEPLOY_USER:-ubuntu}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"
DEPLOY_BASE_DIR="${DEPLOY_BASE_DIR:-}"
if [[ -n "${DEPLOY_BASE_DIR}" ]]; then
  APP_BASE="${DEPLOY_BASE_DIR}"
else
  APP_BASE="/home/${DEPLOY_USER}/apps/englishbot"
fi
SERVICE_NAME="${SERVICE_NAME:-englishbot}"
REMOTE_HEALTH_URL="${REMOTE_HEALTH_URL:-http://127.0.0.1:8003/healthz}"
KEEP_RELEASES="${KEEP_RELEASES:-10}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
GIT_SHA="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo "nogit")"
RELEASE_ID="${DEPLOY_RELEASE_ID:-$(date +%Y%m%d%H%M%S)-${GIT_SHA}}"
REMOTE_RELEASE_DIR="${APP_BASE}/releases/${RELEASE_ID}"

SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"
SSH_OPTS=(-p "${DEPLOY_PORT}" -o StrictHostKeyChecking=accept-new)

echo "==> release_id: ${RELEASE_ID}"
echo "==> remote: ${SSH_TARGET}:${REMOTE_RELEASE_DIR}"

ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "mkdir -p '${REMOTE_RELEASE_DIR}' '${APP_BASE}/shared/data'"

RSYNC_EXCLUDES=(
  "--exclude=/.git"
  "--exclude=/.venv"
  "--exclude=/data"
  "--exclude=/.env"
  "--exclude=/deploy/.env"
  "--exclude=/deploy/config.yaml"
  "--exclude=/.claude"
  "--exclude=/.omx"
  "--exclude=/.playwright-mcp"
  "--exclude=/.gstack"
  "--exclude=/.pytest_cache"
  "--exclude=/.idea"
  "--exclude=/output"
  "--exclude=/tests"
  "--exclude=/docs"
  "--exclude=/tools"
  "--exclude=/alembic"
  "--exclude=__pycache__"
)

rsync -az --delete -e "ssh -p ${DEPLOY_PORT}" \
  "${RSYNC_EXCLUDES[@]}" \
  "${REPO_ROOT}/" \
  "${SSH_TARGET}:${REMOTE_RELEASE_DIR}/"

echo "==> release uploaded, switching current symlink"

ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
  APP_BASE="${APP_BASE}" \
  RELEASE_ID="${RELEASE_ID}" \
  SERVICE_NAME="${SERVICE_NAME}" \
  REMOTE_HEALTH_URL="${REMOTE_HEALTH_URL}" \
  KEEP_RELEASES="${KEEP_RELEASES}" \
  'bash -s' <<'EOF'
set -euo pipefail

NEW_RELEASE="${APP_BASE}/releases/${RELEASE_ID}"
SHARED_DIR="${APP_BASE}/shared"
CURRENT_LINK="${APP_BASE}/current"
PREVIOUS_FILE="${APP_BASE}/.previous_release"

if [[ ! -f "${SHARED_DIR}/.env" ]]; then
  echo "missing ${SHARED_DIR}/.env"
  exit 1
fi
if [[ ! -f "${SHARED_DIR}/config.yaml" ]]; then
  echo "missing ${SHARED_DIR}/config.yaml"
  exit 1
fi

ln -sfn "${SHARED_DIR}/.env" "${NEW_RELEASE}/.env"
ln -sfn "${SHARED_DIR}/config.yaml" "${NEW_RELEASE}/config.yaml"
rm -rf "${NEW_RELEASE}/data"
ln -sfn "${SHARED_DIR}/data" "${NEW_RELEASE}/data"

if command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
elif [[ -x "${HOME}/.local/bin/uv" ]]; then
  UV_BIN="${HOME}/.local/bin/uv"
else
  echo "uv not found on remote host"
  exit 1
fi

cd "${NEW_RELEASE}"
"${UV_BIN}" sync --python 3.12

PREVIOUS_TARGET=""
if [[ -e "${CURRENT_LINK}" ]]; then
  PREVIOUS_TARGET="$(readlink -f "${CURRENT_LINK}" || true)"
fi
if [[ -n "${PREVIOUS_TARGET}" && -d "${PREVIOUS_TARGET}" ]]; then
  printf '%s\n' "${PREVIOUS_TARGET}" > "${PREVIOUS_FILE}"
fi

ln -sfn "${NEW_RELEASE}" "${APP_BASE}/current.next"
mv -Tf "${APP_BASE}/current.next" "${CURRENT_LINK}"

sudo systemctl restart "${SERVICE_NAME}"

HEALTH_OK=0
for _ in $(seq 1 30); do
  if curl -fsS "${REMOTE_HEALTH_URL}" >/dev/null; then
    HEALTH_OK=1
    break
  fi
  sleep 1
done

if [[ "${HEALTH_OK}" -ne 1 ]]; then
  if [[ -f "${PREVIOUS_FILE}" ]]; then
    ROLLBACK_TARGET="$(cat "${PREVIOUS_FILE}")"
    if [[ -n "${ROLLBACK_TARGET}" && -d "${ROLLBACK_TARGET}" ]]; then
      ln -sfn "${ROLLBACK_TARGET}" "${APP_BASE}/current.next"
      mv -Tf "${APP_BASE}/current.next" "${CURRENT_LINK}"
      sudo systemctl restart "${SERVICE_NAME}"
    fi
  fi
  echo "deploy failed health check and rollback was attempted"
  exit 1
fi

sudo systemctl is-active --quiet "${SERVICE_NAME}"
echo "active_release=$(readlink -f "${CURRENT_LINK}")"

if [[ "${KEEP_RELEASES}" =~ ^[0-9]+$ ]]; then
  mapfile -t OLD_RELEASES < <(ls -1dt "${APP_BASE}"/releases/* 2>/dev/null | tail -n +"$((KEEP_RELEASES + 1))" || true)
  for old in "${OLD_RELEASES[@]}"; do
    rm -rf "${old}"
  done
fi
EOF

echo "==> deploy completed"
