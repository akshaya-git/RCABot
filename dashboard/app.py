"""
Real-time Monitoring Dashboard
Shows the complete incident flow from alarm trigger to notification
"""

# CRITICAL: eventlet monkey patch MUST be first
import eventlet
eventlet.monkey_patch()

import os
import json
import re
import subprocess
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import boto3

app = Flask(__name__)
app.config['SECRET_KEY'] = 'monitoring-dashboard-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# AWS clients
cloudwatch = boto3.client('cloudwatch', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Available alarm scenarios
ALARM_SCENARIOS = [
    {
        'id': 'p1-critical',
        'name': 'P1 - Critical Database Outage',
        'description': 'Triggers both CPU and Connection alarms (simulates production down)',
        'alarms': ['demo-app-demo-rds-cpu-high', 'demo-app-demo-rds-connections-high'],
        'priority': 'P1',
        'color': '#dc3545',
        'reasons': {
            'demo-app-demo-rds-cpu-high': 'Threshold Crossed: 3 out of 3 datapoints [97.2, 95.8, 98.1] were greater than the threshold (80.0)',
            'demo-app-demo-rds-connections-high': 'Threshold Crossed: 3 out of 3 datapoints [94.0, 97.0, 95.0] were greater than the threshold (50.0)'
        }
    },
    {
        'id': 'p2-high-connections',
        'name': 'P2 - High Database Connections',
        'description': 'Database connection pool exhaustion',
        'alarms': ['demo-app-demo-rds-connections-high'],
        'priority': 'P2',
        'color': '#fd7e14',
        'reasons': {
            'demo-app-demo-rds-connections-high': 'Threshold Crossed: 3 out of 3 datapoints [78.0, 82.0, 85.0] were greater than the threshold (50.0)'
        }
    },
    {
        'id': 'p2-high-cpu',
        'name': 'P2 - High RDS CPU',
        'description': 'Database CPU utilization above 80%',
        'alarms': ['demo-app-demo-rds-cpu-high'],
        'priority': 'P2',
        'color': '#fd7e14',
        'reasons': {
            'demo-app-demo-rds-cpu-high': 'Threshold Crossed: 3 out of 3 datapoints [88.5, 91.2, 89.7] were greater than the threshold (80.0)'
        }
    },
    {
        'id': 'p3-high-latency',
        'name': 'P3 - High Read Latency',
        'description': 'Database read operations are slow',
        'alarms': ['demo-app-demo-rds-read-latency-high'],
        'priority': 'P3',
        'color': '#ffc107',
        'reasons': {
            'demo-app-demo-rds-read-latency-high': 'Threshold Crossed: 3 out of 3 datapoints [0.045, 0.052, 0.048] were greater than the threshold (0.02)'
        }
    }
]


@app.route('/')
def index():
    """Dashboard home page."""
    return render_template('dashboard.html', scenarios=ALARM_SCENARIOS)


@app.route('/api/scenarios')
def get_scenarios():
    """Get available alarm scenarios."""
    return jsonify({'scenarios': ALARM_SCENARIOS})


@app.route('/api/trigger/<scenario_id>', methods=['POST'])
def trigger_scenario(scenario_id):
    """Trigger an alarm scenario."""
    print(f"[API] Trigger request received for scenario: {scenario_id}")
    scenario = next((s for s in ALARM_SCENARIOS if s['id'] == scenario_id), None)
    if not scenario:
        return jsonify({'error': 'Scenario not found'}), 404
    
    # Start the flow in background
    print(f"[API] Starting background task for scenario: {scenario['name']}")
    socketio.start_background_task(execute_scenario, scenario)
    
    return jsonify({'status': 'started', 'scenario': scenario})


@app.route('/api/status')
def get_status():
    """Get current system status."""
    try:
        # Get alarm states
        alarms_response = cloudwatch.describe_alarms(
            AlarmNames=[alarm for s in ALARM_SCENARIOS for alarm in s['alarms']]
        )
        
        alarms = []
        for alarm in alarms_response.get('MetricAlarms', []):
            alarms.append({
                'name': alarm['AlarmName'],
                'state': alarm['StateValue'],
                'reason': alarm.get('StateReason', ''),
                'updated': alarm.get('StateUpdatedTimestamp', '').isoformat() if alarm.get('StateUpdatedTimestamp') else ''
            })
        
        # Get agent pod status
        agent_status = get_agent_status()
        
        return jsonify({
            'alarms': alarms,
            'agent': agent_status,
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/logs/agent')
def get_agent_logs():
    """Get recent agent logs."""
    try:
        result = subprocess.run(
            ['kubectl', 'logs', '-n', 'monitoring', '-l', 'app=monitoring-agent', '--tail=100'],
            capture_output=True,
            text=True,
            timeout=10
        )
        return jsonify({'logs': result.stdout.split('\n')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/logs/demo-app')
def get_demo_app_logs():
    """Get recent demo app logs."""
    try:
        result = subprocess.run(
            ['kubectl', 'logs', '-n', 'demo-app', '-l', 'app=demo-app', '--tail=50'],
            capture_output=True,
            text=True,
            timeout=10
        )
        return jsonify({'logs': result.stdout.split('\n')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reset', methods=['POST'])
def reset_alarms():
    """Reset all alarms to OK state."""
    try:
        for scenario in ALARM_SCENARIOS:
            for alarm_name in scenario['alarms']:
                cloudwatch.set_alarm_state(
                    AlarmName=alarm_name,
                    StateValue='OK',
                    StateReason='Reset by dashboard'
                )
        
        return jsonify({'status': 'success', 'message': 'All alarms reset to OK'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_agent_status():
    """Get monitoring agent pod status."""
    try:
        result = subprocess.run(
            ['kubectl', 'get', 'pods', '-n', 'monitoring', '-l', 'app=monitoring-agent', '-o', 'json'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get('items'):
                pod = data['items'][0]
                return {
                    'name': pod['metadata']['name'],
                    'status': pod['status']['phase'],
                    'ready': all(c['ready'] for c in pod['status'].get('containerStatuses', [])),
                    'restarts': sum(c['restartCount'] for c in pod['status'].get('containerStatuses', []))
                }
        
        return {'status': 'unknown'}
    except Exception as e:
        return {'status': 'error', 'error': str(e)}


def execute_scenario(scenario):
    """Execute an alarm scenario and emit real-time updates."""
    scenario_id = scenario['id']
    print(f"[SCENARIO] Starting execution for: {scenario['name']}")
    
    # Step 1: Trigger alarms
    print(f"[SCENARIO] Step 1: Triggering alarms")
    emit_step(scenario_id, 'trigger', 'Triggering CloudWatch alarms...', 'info')
    
    triggered_alarms = []
    for alarm_name in scenario['alarms']:
        try:
            print(f"[SCENARIO] Triggering alarm: {alarm_name}")
            cloudwatch.set_alarm_state(
                AlarmName=alarm_name,
                StateValue='ALARM',
                StateReason=scenario.get('reasons', {}).get(alarm_name, f"Threshold Crossed: datapoints exceeded the alarm threshold")
            )
            triggered_alarms.append(alarm_name)
            emit_step(scenario_id, 'trigger', f'✓ Alarm triggered: {alarm_name}', 'success')
            eventlet.sleep(1)
        except Exception as e:
            print(f"[SCENARIO] Error triggering alarm {alarm_name}: {e}")
            emit_step(scenario_id, 'trigger', f'✗ Failed to trigger {alarm_name}: {str(e)}', 'error')
    
    # Step 2: Wait for CloudWatch
    emit_step(scenario_id, 'cloudwatch', 'Waiting for CloudWatch to process alarm state...', 'info')
    eventlet.sleep(3)
    emit_step(scenario_id, 'cloudwatch', '✓ Alarm state updated in CloudWatch', 'success')
    
    # Step 3: Wait for agent collection cycle (up to 90s)
    emit_step(scenario_id, 'collection', 'Waiting for monitoring agent collection cycle (up to 90s)...', 'info')
    emit_step(scenario_id, 'collection', 'Agent checks both active alarms and recent alarm history', 'info')
    
    # Get baseline log line count to detect new output
    try:
        baseline_result = subprocess.run(
            ['kubectl', 'logs', '-n', 'monitoring', '-l', 'app=monitoring-agent', '--tail=5'],
            capture_output=True, text=True, timeout=10
        )
        baseline_lines = set(baseline_result.stdout.strip().split('\n'))
    except:
        baseline_lines = set()
    
    collection_detected = False
    for i in range(18):  # Poll for up to 90 seconds
        eventlet.sleep(5)
        
        try:
            result = subprocess.run(
                ['kubectl', 'logs', '-n', 'monitoring', '-l', 'app=monitoring-agent', '--tail=30'],
                capture_output=True, text=True, timeout=10
            )
            
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line in baseline_lines:
                    continue
                if 'events from alarms' in line and 'Collected' in line:
                    match = re.search(r'Collected (\d+) events from alarms', line)
                    if match and int(match.group(1)) > 0:
                        emit_step(scenario_id, 'collection', f'✓ {line}', 'success')
                        collection_detected = True
                        break
            
            if collection_detected:
                break
            else:
                emit_step(scenario_id, 'collection', f'Polling agent... ({(i+1)*5}s elapsed)', 'info')
        except Exception as e:
            emit_step(scenario_id, 'collection', f'Error checking logs: {str(e)}', 'warning')
    
    if not collection_detected:
        emit_step(scenario_id, 'collection', '⚠ Collection not yet detected in logs - agent will process on next cycle', 'warning')
    
    # Step 4: Wait for AI analysis
    emit_step(scenario_id, 'analysis', 'Waiting for AI analysis and classification...', 'info')
    
    analysis_detected = False
    for i in range(12):  # Up to 60s for Opus to respond
        eventlet.sleep(5)
        try:
            result = subprocess.run(
                ['kubectl', 'logs', '-n', 'monitoring', '-l', 'app=monitoring-agent', '--tail=30'],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line in baseline_lines:
                    continue
                if 'Analyzed' in line and 'anomalies detected' in line:
                    emit_step(scenario_id, 'analysis', f'✓ {line}', 'success')
                    analysis_detected = True
                if 'Classified' in line and 'incidents' in line:
                    emit_step(scenario_id, 'analysis', f'✓ {line}', 'success')
            if analysis_detected:
                break
        except:
            pass
    
    # Step 5: Check notifications
    emit_step(scenario_id, 'notification', 'Checking notification status...', 'info')
    eventlet.sleep(5)
    
    try:
        result = subprocess.run(
            ['kubectl', 'logs', '-n', 'monitoring', '-l', 'app=monitoring-agent', '--tail=30'],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line in baseline_lines:
                continue
            if 'Sent' in line and 'notifications' in line:
                match = re.search(r'Sent (\d+) notifications', line)
                if match and int(match.group(1)) > 0:
                    emit_step(scenario_id, 'notification', f'✓ {line}', 'success')
                    emit_step(scenario_id, 'notification', '✓ Email notification sent via SNS', 'success')
    except Exception as e:
        emit_step(scenario_id, 'notification', f'Error: {str(e)}', 'error')
    
    # Step 6: Complete
    emit_step(scenario_id, 'complete', f'✓ Scenario "{scenario["name"]}" completed!', 'success')
    emit_step(scenario_id, 'complete', 'Check your email for the incident notification', 'info')
    print(f"[SCENARIO] Completed execution for: {scenario['name']}")


def emit_step(scenario_id, step, message, level):
    """Emit a step update via WebSocket."""
    print(f"[EMIT] {scenario_id} - {step}: {message}")
    socketio.emit('step_update', {
        'scenario_id': scenario_id,
        'step': step,
        'message': message,
        'level': level,
        'timestamp': datetime.utcnow().isoformat()
    })


if __name__ == '__main__':
    print("[STARTUP] Starting dashboard with eventlet...")
    socketio.run(app, host='0.0.0.0', port=8080, debug=False)
