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
ROLLBACK_RELEASE="${ROLLBACK_RELEASE:-}"

SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"
SSH_OPTS=(-p "${DEPLOY_PORT}" -o StrictHostKeyChecking=accept-new)

echo "==> rolling back on ${SSH_TARGET}"

ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
  APP_BASE="${APP_BASE}" \
  SERVICE_NAME="${SERVICE_NAME}" \
  REMOTE_HEALTH_URL="${REMOTE_HEALTH_URL}" \
  ROLLBACK_RELEASE="${ROLLBACK_RELEASE}" \
  'bash -s' <<'EOF'
set -euo pipefail

CURRENT_LINK="${APP_BASE}/current"
PREVIOUS_FILE="${APP_BASE}/.previous_release"
TARGET=""

if [[ -n "${ROLLBACK_RELEASE}" ]]; then
  CANDIDATE="${APP_BASE}/releases/${ROLLBACK_RELEASE}"
  if [[ ! -d "${CANDIDATE}" ]]; then
    echo "rollback release does not exist: ${CANDIDATE}"
    exit 1
  fi
  TARGET="${CANDIDATE}"
elif [[ -f "${PREVIOUS_FILE}" ]]; then
  CANDIDATE="$(cat "${PREVIOUS_FILE}")"
  if [[ -n "${CANDIDATE}" && -d "${CANDIDATE}" ]]; then
    TARGET="${CANDIDATE}"
  fi
fi

if [[ -z "${TARGET}" ]]; then
  mapfile -t RELEASES < <(ls -1dt "${APP_BASE}"/releases/* 2>/dev/null || true)
  if (( ${#RELEASES[@]} < 2 )); then
    echo "no rollback target found"
    exit 1
  fi
  TARGET="${RELEASES[1]}"
fi

CURRENT_TARGET="$(readlink -f "${CURRENT_LINK}" || true)"
if [[ "${CURRENT_TARGET}" == "${TARGET}" ]]; then
  echo "already on target release: ${TARGET}"
else
  if [[ -n "${CURRENT_TARGET}" && -d "${CURRENT_TARGET}" ]]; then
    printf '%s\n' "${CURRENT_TARGET}" > "${PREVIOUS_FILE}"
  fi
  ln -sfn "${TARGET}" "${APP_BASE}/current.next"
  mv -Tf "${APP_BASE}/current.next" "${CURRENT_LINK}"
fi

sudo systemctl restart "${SERVICE_NAME}"
for _ in $(seq 1 30); do
  if curl -fsS "${REMOTE_HEALTH_URL}" >/dev/null; then
    break
  fi
  sleep 1
done
sudo systemctl is-active --quiet "${SERVICE_NAME}"
echo "active_release=$(readlink -f "${CURRENT_LINK}")"
EOF

echo "==> rollback completed"
