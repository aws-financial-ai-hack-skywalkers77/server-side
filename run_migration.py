#!/usr/bin/env python3
"""
Migration script to change embedding dimensions from 768 to 384.
This is needed when switching to the free local embedding model (all-MiniLM-L6-v2).
"""

import psycopg2
from config import Config
import sys
import os

def run_migration():
    """Migrate database from 768 to 384 dimensions"""
    
    print("=" * 60)
    print("Database Migration: 768 → 384 dimensions")
    print("=" * 60)
    print()
    print("⚠️  WARNING: This will drop existing embeddings!")
    print("   You'll need to re-ingest documents after migration.")
    print()
    
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
        
        # Migration steps
        print("\n📝 Starting migration...")
        
        # 1. Drop indexes
        print("   1. Dropping indexes...")
        indexes = [
            'idx_tax_laws_embedding',
            'idx_form_templates_embedding',
            'idx_tax_treaties_embedding'
        ]
        for idx in indexes:
            try:
                cursor.execute(f"DROP INDEX IF EXISTS {idx};")
                print(f"      ✓ Dropped {idx}")
            except Exception as e:
                print(f"      ⚠ {idx}: {e}")
        
        # 2. Drop old function
        print("   2. Dropping old function...")
        try:
            cursor.execute("DROP FUNCTION IF EXISTS search_laws_by_similarity(vector, VARCHAR, INTEGER);")
            print("      ✓ Dropped old function")
        except Exception as e:
            print(f"      ⚠ Function drop: {e}")
        
        # 3. Alter tables - drop and recreate embedding columns
        print("   3. Updating table columns...")
        tables = [
            ('tax_laws', 'embedding'),
            ('form_templates', 'embedding'),
            ('tax_treaties', 'embedding'),
            ('tax_documents', 'embedding')
        ]
        
        for table_name, col_name in tables:
            try:
                # Check if table exists
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = %s
                    );
                """, (table_name,))
                table_exists = cursor.fetchone()[0]
                
                if table_exists:
                    # Check if column exists
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.columns 
                            WHERE table_name = %s AND column_name = %s
                        );
                    """, (table_name, col_name))
                    col_exists = cursor.fetchone()[0]
                    
                    if col_exists:
                        # Drop old column
                        cursor.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS {col_name};")
                        # Add new column with 384 dimensions
                        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} vector(384);")
                        print(f"      ✓ Updated {table_name}.{col_name}")
                    else:
                        print(f"      ⚠ {table_name}.{col_name} doesn't exist, skipping")
                else:
                    print(f"      ⚠ Table {table_name} doesn't exist, skipping")
            except Exception as e:
                print(f"      ❌ Error updating {table_name}: {e}")
                conn.rollback()
                continue
        
        # 4. Recreate indexes
        print("   4. Recreating indexes...")
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tax_laws_embedding 
                ON tax_laws USING ivfflat (embedding vector_cosine_ops);
            """)
            print("      ✓ Created idx_tax_laws_embedding")
        except Exception as e:
            print(f"      ⚠ Index creation: {e}")
        
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_form_templates_embedding 
                ON form_templates USING ivfflat (embedding vector_cosine_ops);
            """)
            print("      ✓ Created idx_form_templates_embedding")
        except Exception as e:
            print(f"      ⚠ Index creation: {e}")
        
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tax_treaties_embedding 
                ON tax_treaties USING ivfflat (embedding vector_cosine_ops);
            """)
            print("      ✓ Created idx_tax_treaties_embedding")
        except Exception as e:
            print(f"      ⚠ Index creation: {e}")
        
        # 5. Recreate function
        print("   5. Recreating function...")
        try:
            cursor.execute("""
                CREATE OR REPLACE FUNCTION search_laws_by_similarity(
                    query_embedding vector(384),
                    target_jurisdiction VARCHAR(100),
                    result_limit INTEGER DEFAULT 10
                )
                RETURNS TABLE (
                    law_id INTEGER,
                    similarity FLOAT,
                    chunk_text TEXT,
                    section_reference VARCHAR(255),
                    document_title TEXT
                ) AS $$
                BEGIN
                    RETURN QUERY
                    SELECT 
                        tl.id,
                        1 - (tl.embedding <=> query_embedding) as similarity,
                        tl.chunk_text,
                        tl.section_reference,
                        tl.document_title
                    FROM tax_laws tl
                    WHERE tl.jurisdiction = target_jurisdiction
                    ORDER BY tl.embedding <=> query_embedding
                    LIMIT result_limit;
                END;
                $$ LANGUAGE plpgsql;
            """)
            print("      ✓ Created search_laws_by_similarity function")
        except Exception as e:
            print(f"      ❌ Error creating function: {e}")
            raise
        
        conn.commit()
        print("\n✅ Migration completed successfully!")
        print("   All embedding columns are now 384 dimensions.")
        print("   You can now re-ingest documents.")
        return True
        
    except Exception as e:
        print(f"\n❌ Error during migration: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()
        print("🔌 Database connection closed")

if __name__ == "__main__":
    success = run_migration()
    
    if success:
        print("\n🎉 Migration complete! You can now:")
        print("   1. Start the server: python main.py")
        print("   2. Re-ingest documents (old embeddings were cleared)")
        sys.exit(0)
    else:
        print("\n❌ Migration failed. Please check the errors above.")
        sys.exit(1)

