#!/bin/bash
# =============================================================================
# Demo Anomaly Generator
# Generates various anomalies to trigger CloudWatch alarms and test the
# Proactive Monitoring Bot
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the app endpoint
APP_ENDPOINT="${APP_ENDPOINT:-}"

print_header() {
    echo -e "\n${BLUE}============================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}============================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# Check if app endpoint is set
check_endpoint() {
    if [ -z "$APP_ENDPOINT" ]; then
        print_header "Finding Demo App Endpoint"

        # Try to get from kubectl
        if command -v kubectl &> /dev/null; then
            APP_ENDPOINT=$(kubectl get svc demo-inventory -n demo-app -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
        fi

        if [ -z "$APP_ENDPOINT" ]; then
            print_error "Could not find demo app endpoint."
            echo "Please set APP_ENDPOINT environment variable:"
            echo "  export APP_ENDPOINT=<your-load-balancer-hostname>"
            exit 1
        fi
    fi

    print_info "Using endpoint: http://$APP_ENDPOINT"
}

# Test connectivity
test_connectivity() {
    print_header "Testing Connectivity"

    response=$(curl -s -o /dev/null -w "%{http_code}" "http://$APP_ENDPOINT/health" || echo "000")

    if [ "$response" = "200" ]; then
        print_success "Application is reachable"
    else
        print_error "Cannot reach application (HTTP $response)"
        exit 1
    fi
}

# Generate CPU stress
generate_cpu_stress() {
    local duration=${1:-60}

    print_header "Generating CPU Stress"
    print_info "Duration: ${duration} seconds"
    print_warning "This will spike CPU utilization in the application pod"

    echo ""
    read -p "Press Enter to continue or Ctrl+C to cancel..."

    print_info "Triggering CPU stress..."

    response=$(curl -s "http://$APP_ENDPOINT/api/stress/cpu?duration=$duration")
    echo "$response" | jq . 2>/dev/null || echo "$response"

    print_success "CPU stress test initiated"
    print_info "Monitor CloudWatch alarm: demo-app-demo-rds-cpu-high"
}

# Generate memory pressure
generate_memory_stress() {
    local size_mb=${1:-200}

    print_header "Generating Memory Pressure"
    print_info "Memory allocation: ${size_mb}MB"
    print_warning "This will increase memory usage in the application pod"

    echo ""
    read -p "Press Enter to continue or Ctrl+C to cancel..."

    print_info "Triggering memory stress..."

    response=$(curl -s "http://$APP_ENDPOINT/api/stress/memory?size=$size_mb")
    echo "$response" | jq . 2>/dev/null || echo "$response"

    print_success "Memory stress test initiated"
    print_info "Monitor pod memory metrics in CloudWatch Container Insights"
}

# Generate database connection flood
generate_db_connection_flood() {
    local connections=${1:-100}

    print_header "Generating Database Connection Flood"
    print_info "Connections to open: $connections"
    print_warning "This will trigger the RDS connection alarm"

    echo ""
    read -p "Press Enter to continue or Ctrl+C to cancel..."

    print_info "Triggering database connection flood..."

    response=$(curl -s "http://$APP_ENDPOINT/api/stress/db?connections=$connections")
    echo "$response" | jq . 2>/dev/null || echo "$response"

    print_success "Database connection flood initiated"
    print_info "Monitor CloudWatch alarm: demo-app-demo-rds-connections-high"
}

# Generate rapid API calls (potential latency issues)
generate_traffic_spike() {
    local requests=${1:-500}
    local concurrent=${2:-10}

    print_header "Generating Traffic Spike"
    print_info "Total requests: $requests"
    print_info "Concurrent requests: $concurrent"
    print_warning "This may increase response latency"

    echo ""
    read -p "Press Enter to continue or Ctrl+C to cancel..."

    if ! command -v ab &> /dev/null; then
        print_warning "Apache Bench (ab) not found. Using curl instead."

        for i in $(seq 1 $requests); do
            curl -s "http://$APP_ENDPOINT/api/products" > /dev/null &
            if [ $((i % concurrent)) -eq 0 ]; then
                wait
                echo -ne "\r[INFO] Requests sent: $i / $requests"
            fi
        done
        wait
        echo ""
    else
        ab -n $requests -c $concurrent "http://$APP_ENDPOINT/api/products"
    fi

    print_success "Traffic spike completed"
    print_info "Monitor CloudWatch alarm: demo-app-demo-rds-read-latency-high"
}

# Generate application errors
generate_app_errors() {
    local count=${1:-20}

    print_header "Generating Application Errors"
    print_info "Error count: $count"
    print_warning "This will trigger the application error alarm"

    echo ""
    read -p "Press Enter to continue or Ctrl+C to cancel..."

    print_info "Generating errors by requesting non-existent resources..."

    for i in $(seq 1 $count); do
        curl -s "http://$APP_ENDPOINT/api/products/99999$i" > /dev/null
        echo -ne "\r[INFO] Errors generated: $i / $count"
    done
    echo ""

    print_success "Application errors generated"
    print_info "Monitor CloudWatch alarm: demo-app-demo-application-errors"
}

# Show menu
show_menu() {
    print_header "Demo Anomaly Generator"

    echo "Select an anomaly to generate:"
    echo ""
    echo "  1) CPU Stress          - Spike CPU utilization"
    echo "  2) Memory Pressure     - Increase memory usage"
    echo "  3) DB Connection Flood - Open many database connections"
    echo "  4) Traffic Spike       - Generate high request volume"
    echo "  5) Application Errors  - Generate 404 errors"
    echo "  6) All of the above    - Run all tests sequentially"
    echo "  7) Exit"
    echo ""
    read -p "Enter your choice [1-7]: " choice

    case $choice in
        1) generate_cpu_stress ;;
        2) generate_memory_stress ;;
        3) generate_db_connection_flood ;;
        4) generate_traffic_spike ;;
        5) generate_app_errors ;;
        6)
            generate_cpu_stress 30
            sleep 5
            generate_memory_stress 100
            sleep 5
            generate_db_connection_flood 50
            sleep 5
            generate_traffic_spike 200 5
            sleep 5
            generate_app_errors 15
            ;;
        7)
            print_info "Exiting..."
            exit 0
            ;;
        *)
            print_error "Invalid choice"
            exit 1
            ;;
    esac
}

# Main
main() {
    check_endpoint
    test_connectivity

    if [ $# -eq 0 ]; then
        show_menu
    else
        case "$1" in
            cpu)
                generate_cpu_stress "${2:-60}"
                ;;
            memory)
                generate_memory_stress "${2:-200}"
                ;;
            db)
                generate_db_connection_flood "${2:-100}"
                ;;
            traffic)
                generate_traffic_spike "${2:-500}" "${3:-10}"
                ;;
            errors)
                generate_app_errors "${2:-20}"
                ;;
            all)
                generate_cpu_stress 30
                generate_memory_stress 100
                generate_db_connection_flood 50
                generate_traffic_spike 200 5
                generate_app_errors 15
                ;;
            *)
                echo "Usage: $0 [cpu|memory|db|traffic|errors|all] [parameters...]"
                echo ""
                echo "Examples:"
                echo "  $0                    # Interactive menu"
                echo "  $0 cpu 60             # CPU stress for 60 seconds"
                echo "  $0 memory 200         # Allocate 200MB"
                echo "  $0 db 100             # Open 100 DB connections"
                echo "  $0 traffic 500 10     # 500 requests, 10 concurrent"
                echo "  $0 errors 20          # Generate 20 errors"
                echo "  $0 all                # Run all tests"
                exit 1
                ;;
        esac
    fi
}

main "$@"
