#!/bin/bash
#
# Run integration tests with real Google Cloud credentials
#
# This script checks for required environment variables and runs the
# integration tests that verify the middleware works with real Google APIs.
#

set -e

echo "======================================================================"
echo "Workspace Auth Middleware - Integration Tests"
echo "======================================================================"
echo ""

# Check for required environment variables
MISSING_VARS=()

if [ -z "$GOOGLE_CLIENT_ID" ]; then
    MISSING_VARS+=("GOOGLE_CLIENT_ID")
fi

if [ -z "$GOOGLE_WORKSPACE_DOMAIN" ]; then
    MISSING_VARS+=("GOOGLE_WORKSPACE_DOMAIN")
fi

# Check for credentials (either file or ADC)
if [ -z "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    echo "Warning: GOOGLE_APPLICATION_CREDENTIALS not set"
    echo "Checking if gcloud ADC is available..."

    if ! gcloud auth application-default print-access-token &>/dev/null; then
        echo ""
        echo "No credentials found. You can either:"
        echo "  1. Set GOOGLE_APPLICATION_CREDENTIALS to your service account key:"
        echo "     export GOOGLE_APPLICATION_CREDENTIALS='/path/to/key.json'"
        echo ""
        echo "  2. Use gcloud user credentials:"
        echo "     gcloud auth application-default login"
        echo ""
        MISSING_VARS+=("GOOGLE_APPLICATION_CREDENTIALS or gcloud ADC")
    else
        echo "✓ gcloud ADC is available"
    fi
fi

# If there are missing variables, show help and exit
if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo ""
    echo "❌ Missing required environment variables:"
    for var in "${MISSING_VARS[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "Quick setup:"
    echo "  1. Run the interactive setup:"
    echo "     cd examples && ./setup_env.sh"
    echo ""
    echo "  2. Load the environment:"
    echo "     source .env"
    echo ""
    echo "  3. Run this script again:"
    echo "     ./run_integration_tests.sh"
    echo ""
    echo "Or set them manually:"
    echo "  export GOOGLE_CLIENT_ID='your-client-id.apps.googleusercontent.com'"
    echo "  export GOOGLE_WORKSPACE_DOMAIN='example.com'"
    echo "  export GOOGLE_APPLICATION_CREDENTIALS='/path/to/key.json'"
    echo "  export GOOGLE_DELEGATED_ADMIN='admin@example.com'"
    echo "  export TEST_USER_EMAIL='testuser@example.com'"
    echo ""
    exit 1
fi

echo "Configuration:"
echo "  GOOGLE_CLIENT_ID:              ${GOOGLE_CLIENT_ID:0:30}..."
echo "  GOOGLE_WORKSPACE_DOMAIN:       $GOOGLE_WORKSPACE_DOMAIN"
echo "  GOOGLE_APPLICATION_CREDENTIALS: ${GOOGLE_APPLICATION_CREDENTIALS:-<using gcloud ADC>}"
echo "  GOOGLE_DELEGATED_ADMIN:        ${GOOGLE_DELEGATED_ADMIN:-<not set>}"
echo "  TEST_USER_EMAIL:               ${TEST_USER_EMAIL:-<not set>}"
echo ""

# Ask for confirmation unless --yes flag is passed
if [ "$1" != "--yes" ] && [ "$1" != "-y" ]; then
    read -p "Run integration tests with these settings? [Y/n]: " confirm
    confirm="${confirm:-y}"

    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

echo ""
echo "======================================================================"
echo "Running Integration Tests"
echo "======================================================================"
echo ""

# Enable integration tests
export RUN_INTEGRATION_TESTS=true

# Run the tests
if [ -n "$1" ] && [ "$1" != "--yes" ] && [ "$1" != "-y" ]; then
    # Run specific test if provided
    echo "Running specific test: $1"
    poetry run pytest "tests/test_integration_adc.py::$1" -v -s
else
    # Run all integration tests
    poetry run pytest tests/test_integration_adc.py -v -s
fi

echo ""
echo "======================================================================"
echo "Integration Tests Complete"
echo "======================================================================"
