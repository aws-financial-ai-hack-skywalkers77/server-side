#!/usr/bin/env python3
"""
Script to migrate tax_platform_schema.sql to Neon database.
Uses DATABASE_URL from .env file.
"""
import os
import psycopg2
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

def parse_database_url(url):
    """Parse DATABASE_URL into connection parameters"""
    parsed = urlparse(url)
    return {
        'host': parsed.hostname,
        'port': parsed.port or 5432,
        'database': parsed.path.lstrip('/').split('?')[0],
        'user': parsed.username,
        'password': parsed.password
    }

def execute_sql_file(conn, filepath):
    """Execute SQL file using psycopg2's execute with error handling"""
    with open(filepath, 'r') as f:
        sql_content = f.read()
    
    # Use psycopg2's execute which can handle multiple statements
    # But we need to handle errors per statement, so split intelligently
    import re
    
    # Split by semicolon, but preserve function definitions
    # Pattern: match semicolons that are not inside function bodies
    statements = []
    current = []
    paren_depth = 0
    in_function = False
    
    lines = sql_content.split('\n')
    for line in lines:
        stripped = line.strip().upper()
        
        # Track function boundaries
        if 'CREATE OR REPLACE FUNCTION' in stripped or 'CREATE FUNCTION' in stripped:
            in_function = True
        
        # Track parentheses for nested structures
        paren_depth += line.count('(') - line.count(')')
        
        current.append(line)
        
        # End of statement: semicolon at end of line, not in function body, balanced parens
        if (line.rstrip().endswith(';') and 
            not in_function and 
            paren_depth <= 0 and
            '$$' not in line):  # Not inside function body with $$
            stmt = '\n'.join(current).strip()
            if stmt and not stmt.startswith('--'):
                statements.append(stmt)
            current = []
            paren_depth = 0
        
        # End of function
        if in_function and '$$ LANGUAGE' in stripped:
            in_function = False
    
    # Execute each statement
    with conn.cursor() as cur:
        for i, stmt in enumerate(statements, 1):
            try:
                print(f"Executing statement {i}/{len(statements)}...")
                cur.execute(stmt)
                conn.commit()
            except Exception as e:
                error_msg = str(e)
                # Skip if table/view/extension/index already exists
                if any(phrase in error_msg.lower() for phrase in 
                       ['already exists', 'duplicate', 'does not exist']):
                    if 'does not exist' in error_msg.lower():
                        print(f"  Warning: {error_msg.split(chr(10))[0]}")
                        conn.rollback()
                        continue
                    print(f"  Skipping (already exists): {error_msg.split(chr(10))[0]}")
                    conn.rollback()
                    continue
                print(f"Error in statement {i}: {e}")
                print(f"Statement preview: {stmt[:300]}...")
                conn.rollback()
                raise

def main():
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("Error: DATABASE_URL not found in .env file")
        return
    
    params = parse_database_url(database_url)
    
    print(f"Connecting to database: {params['database']} on {params['host']}")
    conn = psycopg2.connect(**params)
    
    try:
        schema_file = 'tax_platform_schema.sql'
        if not os.path.exists(schema_file):
            print(f"Error: {schema_file} not found")
            return
        
        print(f"Executing schema from {schema_file}...")
        execute_sql_file(conn, schema_file)
        print("Schema migration completed successfully!")
        
    finally:
        conn.close()

if __name__ == '__main__':
    main()

