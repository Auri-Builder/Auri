#!/usr/bin/env bash
# scripts/run_ui_tests.sh
# -----------------------
# Start Streamlit (if not already running) then run Playwright smoke tests.
# Usage:
#   ./scripts/run_ui_tests.sh              # headless (default)
#   ./scripts/run_ui_tests.sh --headed     # headed browser
#   ./scripts/run_ui_tests.sh -k wizard    # run only wizard tests

set -euo pipefail

PORT=8501
APP_URL="http://localhost:${PORT}"
EXTRA_ARGS=("$@")

cd "$(dirname "$0")/.."

# ── Check if Streamlit is already up ────────────────────────────────────────
if curl -sf "${APP_URL}/healthz" > /dev/null 2>&1; then
    echo "✓ Streamlit already running on :${PORT}"
    APP_PID=""
else
    echo "→ Starting Streamlit on :${PORT}…"
    streamlit run Home.py \
        --server.port "${PORT}" \
        --server.headless true \
        --server.runOnSave false \
        > /tmp/streamlit_test.log 2>&1 &
    APP_PID=$!

    # Wait up to 20 s for the app to respond
    for i in $(seq 1 20); do
        if curl -sf "${APP_URL}/healthz" > /dev/null 2>&1; then
            echo "✓ Streamlit ready (${i}s)"
            break
        fi
        sleep 1
    done

    if ! curl -sf "${APP_URL}/healthz" > /dev/null 2>&1; then
        echo "✗ Streamlit failed to start. Log:"
        cat /tmp/streamlit_test.log
        exit 1
    fi
fi

# ── Run tests ────────────────────────────────────────────────────────────────
echo ""
echo "→ Running UI smoke tests…"
pytest tests/test_ui_smoke.py \
    --base-url "${APP_URL}" \
    --browser chromium \
    -v \
    "${EXTRA_ARGS[@]}" || TEST_EXIT=$?

# ── Cleanup ──────────────────────────────────────────────────────────────────
if [ -n "${APP_PID:-}" ]; then
    echo ""
    echo "→ Stopping Streamlit (PID ${APP_PID})"
    kill "${APP_PID}" 2>/dev/null || true
fi

exit "${TEST_EXIT:-0}"
