import psycopg2
import sys

# Connection string provided by user
DATABASE_URL = "postgres://avnadmin:AVNS_0P0_AO7Q_a2EhQ2KbVK@peoplesystem-peoplesystem.j.aivencloud.com:26742/defaultdb?sslmode=require"

# Ensure protocol is correct for psycopg2 (libpq usually handles both but being explicit helps)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql" + DATABASE_URL[8:]

try:
    print(f"Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Check max connections
    cur.execute("SHOW max_connections;")
    max_conns = cur.fetchone()[0]
    print(f"Max connections allowed: {max_conns}")

    # Check current connection count
    cur.execute("SELECT count(*) FROM pg_stat_activity;")
    curr_conns_total = cur.fetchone()[0]
    print(f"Total current connections (all DBs): {curr_conns_total}")

    # Query to check active connections for this DB
    query_str = """
    SELECT 
        pid, 
        usename, 
        application_name, 
        client_addr, 
        backend_start, 
        state, 
        query 
    FROM pg_stat_activity 
    WHERE datname = 'defaultdb'
    ORDER BY state, backend_start DESC;
    """
    
    cur.execute(query_str)
    rows = cur.fetchall()
    
    print(f"\nConnections to 'defaultdb': {len(rows)}")
    print("-" * 140)
    # Format: PID | User | App Name | Client Addr | State | Query
    print(f"{'PID':<8} | {'User':<15} | {'App Name':<25} | {'Client Addr':<15} | {'State':<15} | {'Query (Snippet)':<50}")
    print("-" * 140)
    
    for row in rows:
        pid, usename, app_name, client_addr, backend_start, state, qary = row
        
        # Handle None values
        usename = usename or "unknown"
        app_name = app_name or "unknown"
        client_addr = str(client_addr) if client_addr else "local/unknown"
        state = state or "unknown"
        qary = qary or ""
        
        # Truncate query for display
        q_snippet = (qary[:47] + '...') if len(qary) > 50 else qary
        
        print(f"{pid:<8} | {usename:<15} | {app_name:<25} | {client_addr:<15} | {state:<15} | {q_snippet:<50}")

    cur.close()
    conn.close()

except Exception as e:
    print(f"Error: {e}")
