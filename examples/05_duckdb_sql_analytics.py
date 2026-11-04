"""05_duckdb_sql_analytics.py

Demonstrates running SQL queries on your agent traces via DuckDB.
"""

import duckdb
import nanotrace

if __name__ == "__main__":
    db_path = "./.traces/nanotrace.duckdb"
    conn = duckdb.connect(db_path)

    print("\n⚡️ [DuckDB SQL Analytics on NanoTrace]")

    print("\n1. Top 5 slowest spans:")
    top_slowest = conn.execute("""
        SELECT name, gen_ai_operation, duration_ms, status 
        FROM spans 
        ORDER BY duration_ms DESC 
        LIMIT 5;
    """).fetchall()
    for row in top_slowest:
        print(f"  • {row[0]} ({row[1]}): {row[2]} ms [{row[3]}]")

    print("\n2. Breakdown by Operation:")
    by_op = conn.execute("""
        SELECT 
            gen_ai_operation, 
            COUNT(*) as span_count, 
            ROUND(AVG(duration_ms), 2) as avg_ms,
            SUM(gen_ai_total_tokens) as total_tokens
        FROM spans 
        GROUP BY gen_ai_operation;
    """).fetchall()
    for row in by_op:
        print(f"  • {row[0] or 'internal'}: {row[1]} spans, avg {row[2]} ms, {row[3] or 0} tokens")

    print("\n3. Native Parquet Export:")
    conn.execute("COPY spans TO './.traces/analytics_export.parquet' (FORMAT PARQUET, COMPRESSION ZSTD);")
    print("  ✓ Exported to ./.traces/analytics_export.parquet with ZSTD compression.")
    conn.close()
