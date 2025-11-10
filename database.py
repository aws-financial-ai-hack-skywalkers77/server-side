import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql
from config import Config
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.conn = None
    
    def connect(self):
        """Establish connection to PostgreSQL database"""
        if self.conn is not None:
            return  # Already connected
        
        try:
            self.conn = psycopg2.connect(
                host=Config.DB_HOST,
                port=Config.DB_PORT,
                database=Config.DB_NAME,
                user=Config.DB_USER,
                password=Config.DB_PASSWORD
            )
            # Enable pgvector extension
            with self.conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                self.conn.commit()
            logger.info("Database connection established")
        except Exception as e:
            logger.error(f"Error connecting to database: {e}")
            raise
    
    def create_tables(self):
        """Create necessary database tables"""
        self.connect()  # Ensure connection is established
        try:
            with self.conn.cursor() as cur:
                # Create invoices table with vector column
                # Vector dimensions depend on embedding model (768 for Gemini, 1536 for OpenAI ada-002)
                vector_dim = Config.EMBEDDING_DIMENSIONS
                
                # Drop and recreate table if vector dimension changed
                # This ensures the vector column has the correct dimensions
                
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS invoices (
                        id SERIAL PRIMARY KEY,
                        invoice_id VARCHAR(255),
                        seller_name VARCHAR(500),
                        seller_address TEXT,
                        tax_id VARCHAR(255),
                        subtotal_amount DECIMAL(15, 2),
                        tax_amount DECIMAL(15, 2),
                        summary TEXT,
                        vector vector({vector_dim}),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                
                # Create contracts table with vector column
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS contracts (
                        id SERIAL PRIMARY KEY,
                        contract_id VARCHAR(255),
                        summary TEXT,
                        vector vector({vector_dim}),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                
                # Create index on vector column for similarity search
                # Note: IVFFlat index requires at least 10 rows, so we create it but it may not be used until data is inserted
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS invoices_vector_idx 
                    ON invoices USING ivfflat (vector vector_cosine_ops)
                    WITH (lists = 100);
                """)
                
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS contracts_vector_idx 
                    ON contracts USING ivfflat (vector vector_cosine_ops)
                    WITH (lists = 100);
                """)
                
                self.conn.commit()
                logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Error creating tables: {e}")
            self.conn.rollback()
            raise
    
    def insert_invoice(self, metadata, vector):
        """Insert invoice metadata and vector into database"""
        self.connect()  # Ensure connection is established
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Convert vector list to pgvector format: '[0.1, 0.2, ...]'
                vector_str = '[' + ','.join(map(str, vector)) + ']'
                
                insert_query = """
                    INSERT INTO invoices (
                        invoice_id, seller_name, seller_address, tax_id,
                        subtotal_amount, tax_amount, summary, vector
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
                    RETURNING id, invoice_id, seller_name, seller_address, 
                              tax_id, subtotal_amount, tax_amount, summary, created_at;
                """
                cur.execute(insert_query, (
                    metadata.get('invoice_id'),
                    metadata.get('seller_name'),
                    metadata.get('seller_address'),
                    metadata.get('tax_id'),
                    metadata.get('subtotal_amount'),
                    metadata.get('tax_amount'),
                    metadata.get('summary'),
                    vector_str
                ))
                result = cur.fetchone()
                self.conn.commit()
                return dict(result)
        except Exception as e:
            logger.error(f"Error inserting invoice: {e}")
            self.conn.rollback()
            raise
    
    def get_invoice_by_id(self, invoice_id):
        """Get invoice by invoice_id"""
        self.connect()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT id, invoice_id, seller_name, seller_address, tax_id,
                           subtotal_amount, tax_amount, summary, created_at, updated_at
                    FROM invoices
                    WHERE invoice_id = %s
                    LIMIT 1;
                """
                cur.execute(query, (invoice_id,))
                result = cur.fetchone()
                if result:
                    return dict(result)
                return None
        except Exception as e:
            logger.error(f"Error retrieving invoice by invoice_id: {e}")
            raise
    
    def get_invoice_by_db_id(self, db_id):
        """Get invoice by database ID"""
        self.connect()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT id, invoice_id, seller_name, seller_address, tax_id,
                           subtotal_amount, tax_amount, summary, created_at, updated_at
                    FROM invoices
                    WHERE id = %s
                    LIMIT 1;
                """
                cur.execute(query, (db_id,))
                result = cur.fetchone()
                if result:
                    return dict(result)
                return None
        except Exception as e:
            logger.error(f"Error retrieving invoice by ID: {e}")
            raise
    
    def get_all_invoices(self, limit=100, offset=0):
        """Get all invoices with pagination"""
        self.connect()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT id, invoice_id, seller_name, seller_address, tax_id,
                           subtotal_amount, tax_amount, summary, created_at, updated_at
                    FROM invoices
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s;
                """
                cur.execute(query, (limit, offset))
                results = cur.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error retrieving all invoices: {e}")
            raise
    
    def get_invoices_count(self):
        """Get total count of invoices"""
        self.connect()
        try:
            with self.conn.cursor() as cur:
                query = "SELECT COUNT(*) as count FROM invoices;"
                cur.execute(query)
                result = cur.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"Error getting invoices count: {e}")
            raise
    
    def insert_contract(self, metadata, vector):
        """Insert contract metadata and vector into database"""
        self.connect()  # Ensure connection is established
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Convert vector list to pgvector format: '[0.1, 0.2, ...]'
                vector_str = '[' + ','.join(map(str, vector)) + ']'
                
                insert_query = """
                    INSERT INTO contracts (
                        contract_id, summary, vector
                    ) VALUES (%s, %s, %s::vector)
                    RETURNING id, contract_id, summary, created_at;
                """
                cur.execute(insert_query, (
                    metadata.get('contract_id'),
                    metadata.get('summary'),
                    vector_str
                ))
                result = cur.fetchone()
                self.conn.commit()
                return dict(result)
        except Exception as e:
            logger.error(f"Error inserting contract: {e}")
            self.conn.rollback()
            raise
    
    def get_contract_by_id(self, contract_id):
        """Get contract by contract_id"""
        self.connect()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT id, contract_id, summary, created_at, updated_at
                    FROM contracts
                    WHERE contract_id = %s
                    LIMIT 1;
                """
                cur.execute(query, (contract_id,))
                result = cur.fetchone()
                if result:
                    return dict(result)
                return None
        except Exception as e:
            logger.error(f"Error retrieving contract by contract_id: {e}")
            raise
    
    def get_all_contracts(self, limit=100, offset=0):
        """Get all contracts with pagination"""
        self.connect()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT id, contract_id, summary, created_at, updated_at
                    FROM contracts
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s;
                """
                cur.execute(query, (limit, offset))
                results = cur.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error retrieving all contracts: {e}")
            raise
    
    def get_contracts_count(self):
        """Get total count of contracts"""
        self.connect()
        try:
            with self.conn.cursor() as cur:
                query = "SELECT COUNT(*) as count FROM contracts;"
                cur.execute(query)
                result = cur.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"Error getting contracts count: {e}")
            raise
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

