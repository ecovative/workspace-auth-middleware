#!/bin/bash
#
# Quick check to see if your Google Cloud credentials are properly configured
#

echo "======================================================================"
echo "Google Cloud Credentials Check"
echo "======================================================================"
echo ""

# Check environment variables
echo "Environment Variables:"
echo "----------------------"
if [ -n "$GOOGLE_CLIENT_ID" ]; then
    echo "✓ GOOGLE_CLIENT_ID:              ${GOOGLE_CLIENT_ID:0:30}..."
else
    echo "✗ GOOGLE_CLIENT_ID:              <not set>"
fi

if [ -n "$GOOGLE_WORKSPACE_DOMAIN" ]; then
    echo "✓ GOOGLE_WORKSPACE_DOMAIN:       $GOOGLE_WORKSPACE_DOMAIN"
else
    echo "✗ GOOGLE_WORKSPACE_DOMAIN:       <not set>"
fi

if [ -n "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    echo "✓ GOOGLE_APPLICATION_CREDENTIALS: $GOOGLE_APPLICATION_CREDENTIALS"

    # Check if file exists
    if [ -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
        echo "  ✓ File exists"
    else
        echo "  ✗ File not found!"
    fi
else
    echo "  GOOGLE_APPLICATION_CREDENTIALS: <not set>"
fi

if [ -n "$GOOGLE_DELEGATED_ADMIN" ]; then
    echo "✓ GOOGLE_DELEGATED_ADMIN:        $GOOGLE_DELEGATED_ADMIN"
else
    echo "  GOOGLE_DELEGATED_ADMIN:        <not set> (optional)"
fi

if [ -n "$TEST_USER_EMAIL" ]; then
    echo "✓ TEST_USER_EMAIL:               $TEST_USER_EMAIL"
else
    echo "  TEST_USER_EMAIL:               <not set> (optional)"
fi

echo ""
echo "Google Cloud SDK:"
echo "-----------------"

# Check if gcloud is installed
if command -v gcloud &> /dev/null; then
    echo "✓ gcloud CLI is installed"

    # Check current account
    CURRENT_ACCOUNT=$(gcloud config get-value account 2>/dev/null)
    if [ -n "$CURRENT_ACCOUNT" ]; then
        echo "✓ Logged in as: $CURRENT_ACCOUNT"
    else
        echo "✗ Not logged in (run: gcloud auth login)"
    fi

    # Check ADC
    if gcloud auth application-default print-access-token &>/dev/null; then
        echo "✓ Application Default Credentials are available"
        ADC_ACCOUNT=$(gcloud auth application-default print-access-token --quiet 2>&1 | head -1)
    else
        echo "✗ Application Default Credentials not available"
        echo "  Run: gcloud auth application-default login"
    fi
else
    echo "✗ gcloud CLI is not installed"
    echo "  Install from: https://cloud.google.com/sdk/docs/install"
fi

echo ""
echo "Python Environment:"
echo "-------------------"

# Check if poetry is available
if command -v poetry &> /dev/null; then
    echo "✓ Poetry is installed"

    # Check if dependencies are installed
    if poetry run python -c "import workspace_auth_middleware" 2>/dev/null; then
        echo "✓ workspace_auth_middleware is installed"
    else
        echo "✗ workspace_auth_middleware not installed"
        echo "  Run: poetry install"
    fi

    # Check for google-api-python-client
    if poetry run python -c "import googleapiclient" 2>/dev/null; then
        echo "✓ google-api-python-client is installed"
    else
        echo "✗ google-api-python-client not installed"
        echo "  Run: poetry install"
    fi
else
    echo "✗ Poetry is not installed"
fi

echo ""
echo "======================================================================"
echo "Summary"
echo "======================================================================"
echo ""

# Determine what can be tested
CAN_TEST_TOKEN=false
CAN_TEST_GROUPS=false

if [ -n "$GOOGLE_CLIENT_ID" ]; then
    CAN_TEST_TOKEN=true
fi

if [ -n "$GOOGLE_APPLICATION_CREDENTIALS" ] || gcloud auth application-default print-access-token &>/dev/null; then
    if [ -n "$GOOGLE_DELEGATED_ADMIN" ]; then
        CAN_TEST_GROUPS=true
    fi
fi

if [ "$CAN_TEST_TOKEN" = true ]; then
    echo "✓ You can test: Token verification"
else
    echo "✗ Cannot test token verification (GOOGLE_CLIENT_ID not set)"
fi

if [ "$CAN_TEST_GROUPS" = true ]; then
    echo "✓ You can test: Group fetching"
else
    echo "✗ Cannot test group fetching (missing credentials or GOOGLE_DELEGATED_ADMIN)"
fi

echo ""

if [ "$CAN_TEST_TOKEN" = true ] && [ "$CAN_TEST_GROUPS" = true ]; then
    echo "🎉 Ready to run all integration tests!"
    echo ""
    echo "Run: ./run_integration_tests.sh"
elif [ "$CAN_TEST_TOKEN" = true ]; then
    echo "⚠️  Ready for basic testing (token verification only)"
    echo ""
    echo "For group testing, set:"
    echo "  export GOOGLE_APPLICATION_CREDENTIALS='/path/to/key.json'"
    echo "  export GOOGLE_DELEGATED_ADMIN='admin@yourdomain.com'"
    echo ""
    echo "Or run: cd examples && ./setup_env.sh"
else
    echo "❌ Missing required configuration"
    echo ""
    echo "To get started, run:"
    echo "  cd examples && ./setup_env.sh"
    echo ""
    echo "Or set manually:"
    echo "  export GOOGLE_CLIENT_ID='your-client-id.apps.googleusercontent.com'"
    echo "  export GOOGLE_WORKSPACE_DOMAIN='yourdomain.com'"
fi

echo ""
echo "======================================================================"
