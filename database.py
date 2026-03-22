import json
import psycopg2
from psycopg2.extras import RealDictCursor
from config import Config
import logging
from decimal import Decimal

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
                        vendor_name VARCHAR(500),
                        effective_date VARCHAR(50),
                        start_date VARCHAR(50),
                        end_date VARCHAR(50),
                        pricing_sections TEXT,
                        service_types JSONB,
                        text TEXT,
                        summary TEXT,
                        clauses JSONB,
                        vector vector({vector_dim}),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                
                # Add new columns to existing contracts table if they don't exist (for migrations)
                cur.execute("""
                    ALTER TABLE contracts
                    ADD COLUMN IF NOT EXISTS vendor_name VARCHAR(500),
                    ADD COLUMN IF NOT EXISTS effective_date VARCHAR(50),
                    ADD COLUMN IF NOT EXISTS start_date VARCHAR(50),
                    ADD COLUMN IF NOT EXISTS end_date VARCHAR(50),
                    ADD COLUMN IF NOT EXISTS pricing_sections TEXT,
                    ADD COLUMN IF NOT EXISTS service_types JSONB,
                    ADD COLUMN IF NOT EXISTS clauses JSONB;
                """)
                
                # Ensure invoices table has compliance tracking columns
                cur.execute("""
                    ALTER TABLE invoices
                    ADD COLUMN IF NOT EXISTS last_compliance_run_at TIMESTAMP,
                    ADD COLUMN IF NOT EXISTS compliance_status VARCHAR(50),
                    ADD COLUMN IF NOT EXISTS risk_assessment_score DECIMAL(10, 4);
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
                        risk_assessment_score DECIMAL(10, 4),
                        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        next_run_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                
                # Add risk_assessment_score column to existing compliance_reports table if it doesn't exist
                cur.execute("""
                    ALTER TABLE compliance_reports
                    ADD COLUMN IF NOT EXISTS risk_assessment_score DECIMAL(10, 4);
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

    def insert_invoice_line_items(self, invoice_db_id, line_items):
        """Insert line items for an invoice"""
        self.connect()
        if not line_items:
            return []
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                inserted = []
                for item in line_items:
                    metadata = item.get('metadata', {})
                    metadata_json = json.dumps(metadata)
                    logger.debug(f"Inserting line item '{item.get('description', '')[:50]}' with metadata: {metadata_json}")
                    
                    insert_query = """
                        INSERT INTO invoice_line_items (
                            invoice_id, line_id, description, service_code,
                            quantity, unit_price, total_price, metadata
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        RETURNING id, line_id, description, service_code,
                                  quantity, unit_price, total_price;
                    """
                    cur.execute(insert_query, (
                        invoice_db_id,
                        item.get('line_id'),
                        item.get('description', ''),
                        item.get('service_code'),
                        item.get('quantity'),
                        item.get('unit_price'),
                        item.get('total_price'),
                        metadata_json
                    ))
                    result = cur.fetchone()
                    if result:
                        inserted.append(dict(result))
                self.conn.commit()
                logger.info(f"Inserted {len(inserted)} line items for invoice ID {invoice_db_id}")
                return inserted
        except Exception as e:
            logger.error(f"Error inserting invoice line items: {e}")
            self.conn.rollback()
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

    def get_invoice_with_line_items(self, invoice_identifier, identifier_is_db_id=False):
        """
        Fetch an invoice and its line items.
        Args:
            invoice_identifier: invoice_id (string) or database id (int based on identifier_is_db_id flag)
            identifier_is_db_id: when True, treat invoice_identifier as invoices.id
        """
        if identifier_is_db_id:
            invoice = self.get_invoice_by_db_id(invoice_identifier)
        else:
            invoice = self.get_invoice_by_id(invoice_identifier)
        if not invoice:
            return None
        line_items = self.get_invoice_line_items(invoice.get('id'))
        invoice['line_items'] = line_items
        return invoice

    def update_invoice_compliance_metadata(self, invoice_db_id, status, risk_assessment_score=None):
        """Update invoice record with compliance run timestamp, status, and risk assessment score"""
        self.connect()
        try:
            with self.conn.cursor() as cur:
                if risk_assessment_score is not None:
                    cur.execute(
                        """
                        UPDATE invoices
                        SET last_compliance_run_at = CURRENT_TIMESTAMP,
                            compliance_status = %s,
                            risk_assessment_score = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s;
                        """,
                        (status, risk_assessment_score, invoice_db_id)
                    )
                else:
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

    def _convert_decimals_to_float(self, obj):
        """
        Recursively convert Decimal objects to float for JSON serialization.
        """
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {key: self._convert_decimals_to_float(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_decimals_to_float(item) for item in obj]
        else:
            return obj

    def save_compliance_report(self, invoice_db_id, invoice_number, status, violations, pricing_rules, llm_metadata=None, next_run_at=None, risk_assessment_score=None):
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
                        risk_assessment_score,
                        processed_at,
                        next_run_at
                    ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, CURRENT_TIMESTAMP, %s)
                    RETURNING id, processed_at;
                """
                # Convert Decimal to float before JSON serialization
                violations_clean = self._convert_decimals_to_float(violations or [])
                pricing_rules_clean = self._convert_decimals_to_float(pricing_rules or {})
                metadata_clean = self._convert_decimals_to_float(llm_metadata or {})
                
                violations_json = json.dumps(violations_clean)
                pricing_rules_json = json.dumps(pricing_rules_clean)
                metadata_json = json.dumps(metadata_clean)
                cur.execute(
                    insert_query,
                    (
                        invoice_db_id,
                        invoice_number,
                        status,
                        violations_json,
                        pricing_rules_json,
                        metadata_json,
                        risk_assessment_score,
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
                           pricing_rules, llm_metadata, risk_assessment_score,
                           processed_at, next_run_at
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
                
                # Convert service_types and clauses to JSONB format
                service_types_json = json.dumps(metadata.get('service_types', []))
                clauses_json = json.dumps(metadata.get('clauses', []))
                
                insert_query = """
                    INSERT INTO contracts (
                        contract_id, vendor_name, effective_date, start_date, end_date,
                        pricing_sections, service_types, summary, text, clauses, vector
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s::vector)
                    RETURNING id, contract_id, vendor_name, effective_date, start_date, end_date,
                              pricing_sections, service_types, summary, text, clauses, created_at;
                """
                cur.execute(insert_query, (
                    metadata.get('contract_id'),
                    metadata.get('vendor_name'),
                    metadata.get('effective_date'),
                    metadata.get('start_date'),
                    metadata.get('end_date'),
                    metadata.get('pricing_sections'),
                    service_types_json,
                    metadata.get('summary'),
                    metadata.get('text'),
                    clauses_json,
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

    def search_contracts_by_similarity(self, query_vector, limit=10, similarity_threshold=0.0, contract_id=None, vendor_name=None):
        """
        Perform vector similarity search over contracts.
        
        Args:
            query_vector: Vector embedding for similarity search
            limit: Maximum number of results
            similarity_threshold: Minimum similarity score (0.0-1.0)
            contract_id: Optional specific contract ID to filter
            vendor_name: Optional vendor/seller name - only contracts containing this name will be returned
        """
        self.connect()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                vector_str = '[' + ','.join(map(str, query_vector)) + ']'
                base_query = """
                    SELECT
                        id,
                        contract_id,
                        vendor_name,
                        effective_date,
                        start_date,
                        end_date,
                        pricing_sections,
                        service_types,
                        summary,
                        text,
                        clauses,
                        1 - (vector <=> %s::vector) AS similarity
                    FROM contracts
                """
                params = [vector_str]
                where_clauses = []
                
                if contract_id is not None:
                    where_clauses.append("id = %s")
                    params.append(contract_id)
                
                # Hard filter: only include contracts that mention the vendor name
                if vendor_name:
                    # Normalize vendor name for matching (remove common business suffixes)
                    vendor_normalized = vendor_name.strip()
                    # Remove common business entity suffixes for better matching
                    for suffix in [' Inc.', ' Inc', '. Inc', ' LLC', ' Ltd.', ' Ltd', ' Corporation', ' Corp.', ' Corp']:
                        if vendor_normalized.endswith(suffix):
                            vendor_normalized = vendor_normalized[:-len(suffix)].strip()
                    
                    # First check vendor_name field (most reliable), then fallback to text/summary/contract_id
                    where_clauses.append(
                        "(LOWER(vendor_name) LIKE %s OR LOWER(text) LIKE %s OR LOWER(summary) LIKE %s OR LOWER(contract_id) LIKE %s)"
                    )
                    vendor_pattern = f"%{vendor_normalized.lower()}%"
                    params.extend([vendor_pattern, vendor_pattern, vendor_pattern, vendor_pattern])
                    logger.info(f"Filtering contracts by vendor name: '{vendor_name}' (normalized: '{vendor_normalized}')")

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
                
                if vendor_name and len(filtered) == 0:
                    logger.warning(
                        f"No contracts found matching vendor '{vendor_name}' even after similarity search. "
                        "This may indicate the contract doesn't exist for this vendor, or vendor name doesn't match."
                    )
                
                return filtered
        except Exception as e:
            logger.error(f"Error searching contracts by similarity: {e}")
            raise
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

