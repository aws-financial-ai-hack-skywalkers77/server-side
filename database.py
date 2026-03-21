import json
import psycopg2
from psycopg2.extras import RealDictCursor
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
                        text TEXT,
                        summary TEXT,
                        vector vector({vector_dim}),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                
                # Ensure invoices table has compliance tracking columns
                cur.execute("""
                    ALTER TABLE invoices
                    ADD COLUMN IF NOT EXISTS last_compliance_run_at TIMESTAMP,
                    ADD COLUMN IF NOT EXISTS compliance_status VARCHAR(50);
                """)

                # Create invoice line items table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS invoice_line_items (
                        id SERIAL PRIMARY KEY,
                        invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
                        line_id VARCHAR(255),
                        description TEXT,
                        service_code VARCHAR(255),
                        quantity DECIMAL(18, 4),
                        unit_price DECIMAL(18, 4),
                        total_price DECIMAL(18, 4),
                        metadata JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS invoice_line_items_invoice_id_idx
                    ON invoice_line_items(invoice_id);
                """)

                # Create compliance reports table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS compliance_reports (
                        id SERIAL PRIMARY KEY,
                        invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
                        invoice_number VARCHAR(255),
                        status VARCHAR(50),
                        violations JSONB,
                        pricing_rules JSONB,
                        llm_metadata JSONB,
                        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        next_run_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS compliance_reports_invoice_id_idx
                    ON compliance_reports(invoice_id);
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

    def get_invoice_line_items(self, invoice_db_id):
        """Retrieve line items for a specific invoice"""
        self.connect()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT id, invoice_id, line_id, description, service_code,
                           quantity, unit_price, total_price, metadata,
                           created_at, updated_at
                    FROM invoice_line_items
                    WHERE invoice_id = %s
                    ORDER BY COALESCE(line_id, '') ASC, id ASC;
                """
                cur.execute(query, (invoice_db_id,))
                results = cur.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error retrieving invoice line items: {e}")
            raise

    def get_invoice_with_line_items(self, invoice_identifier):
        """
        Fetch an invoice and its line items by invoice_id (external identifier).
        """
        invoice = self.get_invoice_by_id(invoice_identifier)
        if not invoice:
            return None
        line_items = self.get_invoice_line_items(invoice.get('id'))
        invoice['line_items'] = line_items
        return invoice

    def update_invoice_compliance_metadata(self, invoice_db_id, status):
        """Update invoice record with compliance run timestamp and status"""
        self.connect()
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE invoices
                    SET last_compliance_run_at = CURRENT_TIMESTAMP,
                        compliance_status = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                    """,
                    (status, invoice_db_id)
                )
                self.conn.commit()
        except Exception as e:
            logger.error(f"Error updating invoice compliance metadata: {e}")
            self.conn.rollback()
            raise

    def save_compliance_report(self, invoice_db_id, invoice_number, status, violations, pricing_rules, llm_metadata=None, next_run_at=None):
        """Persist compliance evaluation results"""
        self.connect()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                insert_query = """
                    INSERT INTO compliance_reports (
                        invoice_id,
                        invoice_number,
                        status,
                        violations,
                        pricing_rules,
                        llm_metadata,
                        processed_at,
                        next_run_at
                    ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, CURRENT_TIMESTAMP, %s)
                    RETURNING id, processed_at;
                """
                violations_json = json.dumps(violations or [])
                pricing_rules_json = json.dumps(pricing_rules or {})
                metadata_json = json.dumps(llm_metadata or {})
                cur.execute(
                    insert_query,
                    (
                        invoice_db_id,
                        invoice_number,
                        status,
                        violations_json,
                        pricing_rules_json,
                        metadata_json,
                        next_run_at
                    )
                )
                result = cur.fetchone()
                self.conn.commit()
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"Error saving compliance report: {e}")
            self.conn.rollback()
            raise

    def get_latest_compliance_report(self, invoice_db_id):
        """Retrieve the most recent compliance report for an invoice"""
        self.connect()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT id, invoice_id, invoice_number, status, violations,
                           pricing_rules, llm_metadata, processed_at, next_run_at
                    FROM compliance_reports
                    WHERE invoice_id = %s
                    ORDER BY processed_at DESC
                    LIMIT 1;
                """
                cur.execute(query, (invoice_db_id,))
                result = cur.fetchone()
                if result:
                    return dict(result)
                return None
        except Exception as e:
            logger.error(f"Error retrieving latest compliance report: {e}")
            raise

    def get_invoices_pending_compliance(self, limit=100):
        """
        Return invoices that require compliance evaluation.
        Conditions:
            - Never processed (last_compliance_run_at IS NULL)
            - Updated after the last compliance run
        """
        self.connect()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT id, invoice_id, seller_name, seller_address, summary,
                           updated_at, last_compliance_run_at
                    FROM invoices
                    WHERE last_compliance_run_at IS NULL
                       OR updated_at IS NULL
                       OR updated_at > last_compliance_run_at
                    ORDER BY COALESCE(last_compliance_run_at, to_timestamp(0)) ASC
                    LIMIT %s;
                """
                cur.execute(query, (limit,))
                results = cur.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error retrieving invoices pending compliance: {e}")
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
                        contract_id, summary, text, vector
                    ) VALUES (%s, %s, %s, %s::vector)
                    RETURNING id, contract_id, summary, text, created_at;
                """
                cur.execute(insert_query, (
                    metadata.get('contract_id'),
                    metadata.get('summary'),
                    metadata.get('text'),
                    vector_str
                ))
                result = cur.fetchone()
                self.conn.commit()
                return dict(result)
        except Exception as e:
            logger.error(f"Error inserting contract: {e}")
            self.conn.rollback()
            raise
    
    def get_contract_by_db_id(self, db_id):
        """Get contract by database ID"""
        self.connect()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT id, contract_id, summary, text, created_at, updated_at
                    FROM contracts
                    WHERE id = %s
                    LIMIT 1;
                """
                cur.execute(query, (db_id,))
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
                    SELECT id, contract_id, summary, text, created_at, updated_at
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

    def search_contracts_by_similarity(self, query_vector, limit=10, similarity_threshold=0.0, contract_id=None):
        """Perform vector similarity search over contracts"""
        self.connect()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                vector_str = '[' + ','.join(map(str, query_vector)) + ']'
                base_query = """
                    SELECT
                        id,
                        contract_id,
                        summary,
                        text,
                        1 - (vector <=> %s::vector) AS similarity
                    FROM contracts
                """
                params = [vector_str]
                where_clauses = []
                if contract_id is not None:
                    where_clauses.append("id = %s")
                    params.append(contract_id)

                if where_clauses:
                    base_query += " WHERE " + " AND ".join(where_clauses)

                base_query += " ORDER BY vector <=> %s::vector LIMIT %s;"
                params.extend([vector_str, limit])

                cur.execute(base_query, params)
                results = cur.fetchall()
                filtered = []
                for row in results:
                    record = dict(row)
                    if similarity_threshold and similarity_threshold > 0:
                        if record['similarity'] is None or record['similarity'] < similarity_threshold:
                            continue
                    filtered.append(record)
                return filtered
        except Exception as e:
            logger.error(f"Error searching contracts by similarity: {e}")
            raise
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

