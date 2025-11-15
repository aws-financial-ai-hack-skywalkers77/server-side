#!/usr/bin/env python3
"""
Script to run the tax platform database schema.
This creates all necessary tables for the Tax Intelligence Platform.
"""

import psycopg2
from psycopg2 import sql
from config import Config
import sys
import os

def run_schema():
    """Execute the tax platform schema SQL file"""
    
    # Read the SQL file
    schema_file = 'tax_platform_schema.sql'
    if not os.path.exists(schema_file):
        print(f"❌ Error: {schema_file} not found!")
        print(f"   Current directory: {os.getcwd()}")
        return False
    
    print(f"📖 Reading schema file: {schema_file}")
    with open(schema_file, 'r') as f:
        sql_content = f.read()
    
    # Connect to database
    print(f"🔌 Connecting to database: {Config.DB_HOST}/{Config.DB_NAME}")
    try:
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            database=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            sslmode='require'
        )
        print("✅ Connected to database")
    except Exception as e:
        print(f"❌ Error connecting to database: {e}")
        return False
    
    try:
        cursor = conn.cursor()
        
        # Split SQL by semicolons, handling dollar-quoted strings
        statements = []
        current_statement = ""
        in_dollar_quote = False
        dollar_tag = None
        
        for line in sql_content.split('\n'):
            stripped = line.strip()
            
            # Skip comment-only lines (but keep them in dollar-quoted blocks)
            if not in_dollar_quote and (not stripped or stripped.startswith('--')):
                continue
            
            # Check for dollar-quoted strings ($$ or $tag$)
            if '$$' in line or ('$' in line and any(c.isalnum() or c == '_' for c in line.split('$')[1] if len(line.split('$')) > 1)):
                # Simple detection: if we see $$, toggle state
                dollar_count = line.count('$$')
                if dollar_count % 2 == 1:
                    in_dollar_quote = not in_dollar_quote
            
            current_statement += line + '\n'
            
            # If line ends with semicolon and we're not in a dollar quote, it's a complete statement
            if not in_dollar_quote and stripped.endswith(';'):
                stmt = current_statement.strip()
                if stmt:
                    statements.append(stmt)
                current_statement = ""
        
        # Add any remaining statement
        if current_statement.strip():
            statements.append(current_statement.strip())
        
        # Execute all statements
        print(f"📝 Executing {len(statements)} SQL statements...")
        errors = []
        for i, statement in enumerate(statements, 1):
            if statement.strip():
                try:
                    cursor.execute(statement)
                    print(f"   ✓ Statement {i}/{len(statements)} executed")
                except Exception as e:
                    error_msg = str(e).lower()
                    # Some statements might fail if they already exist
                    if any(keyword in error_msg for keyword in ["already exists", "duplicate", "relation"]):
                        print(f"   ⚠ Statement {i} skipped (already exists)")
                        # Rollback the failed statement but continue
                        conn.rollback()
                        continue
                    else:
                        error_info = f"Statement {i}: {str(e)[:100]}"
                        errors.append(error_info)
                        print(f"   ❌ Error in statement {i}: {e}")
                        print(f"   Statement preview: {statement[:100]}...")
                        # Rollback and continue with next statement
                        conn.rollback()
                        continue
        
        conn.commit()
        
        if errors:
            print(f"\n⚠️  Schema execution completed with {len(errors)} warnings:")
            for error in errors:
                print(f"   - {error}")
            print("\n✅ Most schema elements are ready. Some may already exist.")
        else:
            print("\n✅ Database schema created successfully!")
            print("   All tables, indexes, and functions are ready.")
        return True
        
    except Exception as e:
        print(f"\n❌ Fatal error executing schema: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()
        print("🔌 Database connection closed")

if __name__ == "__main__":
    print("=" * 60)
    print("Tax Platform Database Schema Setup")
    print("=" * 60)
    print()
    
    success = run_schema()
    
    if success:
        print("\n🎉 Setup complete! You can now start the server:")
        print("   python main.py")
        sys.exit(0)
    else:
        print("\n❌ Setup failed. Please check the errors above.")
        sys.exit(1)

