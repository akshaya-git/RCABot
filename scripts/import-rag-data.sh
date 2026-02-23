#!/bin/bash
# =============================================================================
# Import RAG Data Script
# =============================================================================
# This script imports runbooks and case history from S3 to OpenSearch.
# It handles both structured (JSON) and unstructured (markdown, text) files.
#
# Usage:
#   ./scripts/import-rag-data.sh
#   ./scripts/import-rag-data.sh --runbooks-only
#   ./scripts/import-rag-data.sh --api-url http://localhost:8080
# =============================================================================

set -e

# Configuration
API_URL="${API_URL:-http://localhost:8080}"
RUNBOOKS_ONLY=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --runbooks-only)
            RUNBOOKS_ONLY=true
            shift
            ;;
        --api-url)
            API_URL="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "========================================"
echo "RAG Data Import"
echo "========================================"
echo "API URL: $API_URL"
echo ""

# Check if API is reachable
echo "Checking API connection..."
if ! curl -s "$API_URL/health" > /dev/null 2>&1; then
    echo ""
    echo "ERROR: Cannot connect to API at $API_URL"
    echo ""
    echo "Make sure the agent is running and port-forwarded:"
    echo "  kubectl port-forward -n monitoring svc/monitoring-agent 8080:8080"
    echo ""
    exit 1
fi
echo "✓ API is reachable"
echo ""

# Check S3 configuration
echo "Checking S3 configuration..."
S3_STATUS=$(curl -s "$API_URL/s3/status")
S3_CONFIGURED=$(echo "$S3_STATUS" | grep -o '"s3_configured":[^,}]*' | cut -d':' -f2)

if [ "$S3_CONFIGURED" != "true" ]; then
    echo ""
    echo "ERROR: S3 bucket not configured"
    echo ""
    echo "Make sure RAG_S3_BUCKET is set in your deployment."
    echo ""
    exit 1
fi

BUCKET=$(echo "$S3_STATUS" | grep -o '"bucket":"[^"]*"' | cut -d'"' -f4)
echo "✓ S3 bucket: $BUCKET"
echo ""

# Show current counts
S3_RUNBOOKS=$(echo "$S3_STATUS" | grep -o '"s3_runbooks_count":[0-9]*' | cut -d':' -f2)
S3_CASES=$(echo "$S3_STATUS" | grep -o '"s3_case_history_count":[0-9]*' | cut -d':' -f2)
echo "Files in S3:"
echo "  - Runbooks: $S3_RUNBOOKS"
echo "  - Case History: $S3_CASES"
echo ""

if [ "$S3_RUNBOOKS" = "0" ] && [ "$S3_CASES" = "0" ]; then
    echo "WARNING: No files found in S3 bucket."
    echo ""
    echo "Upload your runbooks first:"
    echo "  aws s3 sync ./your-runbooks/ s3://$BUCKET/runbooks/"
    echo ""
    exit 0
fi

# Run import
echo "========================================"
echo "Starting Import..."
echo "========================================"

if [ "$RUNBOOKS_ONLY" = true ]; then
    echo "Importing runbooks only..."
    RESULT=$(curl -s -X POST "$API_URL/s3/sync/runbooks")
else
    echo "Importing all data (runbooks + case history)..."
    RESULT=$(curl -s -X POST "$API_URL/s3/sync/all")
fi

echo ""
echo "========================================"
echo "Import Results"
echo "========================================"

# Parse results
if echo "$RESULT" | grep -q '"success":true'; then
    echo "✓ Import completed successfully!"
    echo ""

    # Extract counts
    RUNBOOKS_INDEXED=$(echo "$RESULT" | grep -o '"runbooks":{[^}]*"indexed":[0-9]*' | grep -o '"indexed":[0-9]*' | cut -d':' -f2)
    RUNBOOKS_EXTRACTED=$(echo "$RESULT" | grep -o '"runbooks":{[^}]*"extracted":[0-9]*' | grep -o '"extracted":[0-9]*' | cut -d':' -f2 2>/dev/null || echo "0")
    RUNBOOKS_FAILED=$(echo "$RESULT" | grep -o '"runbooks":{[^}]*"failed":[0-9]*' | grep -o '"failed":[0-9]*' | cut -d':' -f2)

    echo "Runbooks:"
    echo "  - Indexed: ${RUNBOOKS_INDEXED:-0}"
    echo "  - Extracted (from raw): ${RUNBOOKS_EXTRACTED:-0}"
    echo "  - Failed: ${RUNBOOKS_FAILED:-0}"

    if [ "$RUNBOOKS_ONLY" != true ]; then
        CASES_INDEXED=$(echo "$RESULT" | grep -o '"case_history":{[^}]*"indexed":[0-9]*' | grep -o '"indexed":[0-9]*' | cut -d':' -f2)
        CASES_FAILED=$(echo "$RESULT" | grep -o '"case_history":{[^}]*"failed":[0-9]*' | grep -o '"failed":[0-9]*' | cut -d':' -f2)
        echo ""
        echo "Case History:"
        echo "  - Indexed: ${CASES_INDEXED:-0}"
        echo "  - Failed: ${CASES_FAILED:-0}"
    fi
else
    echo "✗ Import failed!"
    echo ""
    echo "Response:"
    echo "$RESULT" | head -20
    exit 1
fi

echo ""
echo "========================================"
echo "Done!"
echo "========================================"
echo ""
echo "Your runbooks are now indexed. The monitoring bot will use them"
echo "for better incident analysis and recommendations."
echo ""
echo "To search runbooks:"
echo "  curl '$API_URL/runbooks/search?query=cpu'"
echo ""
