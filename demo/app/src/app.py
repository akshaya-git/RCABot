"""
Demo Inventory Application
A simple Flask app that queries a PostgreSQL database for product inventory.
Used to demonstrate the Proactive Monitoring Bot.
"""

import os
import time
import psycopg2
from psycopg2 import pool
from flask import Flask, render_template, jsonify, request

app = Flask(__name__, template_folder='../templates')

# Database configuration from environment
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432'),
    'database': os.getenv('DB_NAME', 'inventory'),
    'user': os.getenv('DB_USER', 'demo'),
    'password': os.getenv('DB_PASSWORD', 'demo123'),
}

# Connection pool
db_pool = None


def get_db_pool():
    """Get or create database connection pool."""
    global db_pool
    if db_pool is None:
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=20,
            **DB_CONFIG
        )
    return db_pool


def get_db_connection():
    """Get a connection from the pool."""
    return get_db_pool().getconn()


def release_db_connection(conn):
    """Release connection back to pool."""
    get_db_pool().putconn(conn)


@app.route('/')
def index():
    """Home page showing inventory."""
    return render_template('index.html')


@app.route('/health')
def health():
    """Health check endpoint."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT 1')
        cur.close()
        release_db_connection(conn)
        return jsonify({'status': 'healthy', 'database': 'connected'})
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500


@app.route('/api/products')
def get_products():
    """Get all products."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, name, category, price, quantity, description
            FROM products
            ORDER BY category, name
        ''')
        rows = cur.fetchall()
        cur.close()
        release_db_connection(conn)

        products = []
        for row in rows:
            products.append({
                'id': row[0],
                'name': row[1],
                'category': row[2],
                'price': float(row[3]),
                'quantity': row[4],
                'description': row[5],
            })

        return jsonify({'products': products, 'count': len(products)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/products/search')
def search_products():
    """Search products by name or category."""
    query = request.args.get('q', '')

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, name, category, price, quantity, description
            FROM products
            WHERE name ILIKE %s OR category ILIKE %s
            ORDER BY name
        ''', (f'%{query}%', f'%{query}%'))
        rows = cur.fetchall()
        cur.close()
        release_db_connection(conn)

        products = []
        for row in rows:
            products.append({
                'id': row[0],
                'name': row[1],
                'category': row[2],
                'price': float(row[3]),
                'quantity': row[4],
                'description': row[5],
            })

        return jsonify({'products': products, 'count': len(products), 'query': query})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/products/<int:product_id>')
def get_product(product_id):
    """Get a specific product by ID."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, name, category, price, quantity, description
            FROM products
            WHERE id = %s
        ''', (product_id,))
        row = cur.fetchone()
        cur.close()
        release_db_connection(conn)

        if row:
            return jsonify({
                'id': row[0],
                'name': row[1],
                'category': row[2],
                'price': float(row[3]),
                'quantity': row[4],
                'description': row[5],
            })
        else:
            return jsonify({'error': 'Product not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats')
def get_stats():
    """Get inventory statistics."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Total products
        cur.execute('SELECT COUNT(*) FROM products')
        total_products = cur.fetchone()[0]

        # Total value
        cur.execute('SELECT SUM(price * quantity) FROM products')
        total_value = cur.fetchone()[0] or 0

        # By category
        cur.execute('''
            SELECT category, COUNT(*), SUM(quantity)
            FROM products
            GROUP BY category
        ''')
        categories = []
        for row in cur.fetchall():
            categories.append({
                'category': row[0],
                'product_count': row[1],
                'total_quantity': row[2],
            })

        # Low stock (quantity < 10)
        cur.execute('SELECT COUNT(*) FROM products WHERE quantity < 10')
        low_stock = cur.fetchone()[0]

        cur.close()
        release_db_connection(conn)

        return jsonify({
            'total_products': total_products,
            'total_value': float(total_value),
            'categories': categories,
            'low_stock_count': low_stock,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# Endpoints for demo/testing anomalies
# ============================================================================

@app.route('/api/stress/cpu')
def stress_cpu():
    """Endpoint to simulate CPU stress (for demo)."""
    duration = int(request.args.get('duration', 30))

    # CPU intensive operation
    end_time = time.time() + duration
    result = 0
    while time.time() < end_time:
        result += sum(i * i for i in range(10000))

    return jsonify({'status': 'completed', 'duration': duration})


@app.route('/api/stress/memory')
def stress_memory():
    """Endpoint to simulate memory pressure (for demo)."""
    size_mb = int(request.args.get('size', 100))

    # Allocate memory
    data = []
    for _ in range(size_mb):
        data.append('x' * (1024 * 1024))  # 1MB chunks

    time.sleep(30)  # Hold memory for 30 seconds

    return jsonify({'status': 'completed', 'allocated_mb': size_mb})


@app.route('/api/stress/db')
def stress_db():
    """Endpoint to simulate database connection flood (for demo)."""
    connections = int(request.args.get('connections', 50))

    # Open many connections
    conns = []
    try:
        for _ in range(connections):
            conn = psycopg2.connect(**DB_CONFIG)
            conns.append(conn)

        time.sleep(30)  # Hold connections

        return jsonify({'status': 'completed', 'connections_opened': len(conns)})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e), 'connections_opened': len(conns)})
    finally:
        for conn in conns:
            try:
                conn.close()
            except:
                pass


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=os.getenv('DEBUG', 'false').lower() == 'true')
