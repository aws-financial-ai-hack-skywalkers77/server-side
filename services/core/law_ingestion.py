# services/core/law_ingestion.py

import logging
import psycopg2.extras
from typing import Dict, List, Optional
from datetime import datetime
try:
    import PyPDF2
except ImportError:
    PyPDF2 = None
import io
import re

logger = logging.getLogger(__name__)

class LawIngestionService:
    """
    Service for ingesting tax law documents into the knowledge base.
    Handles PDF parsing, chunking, and vectorization.
    """
    
    def __init__(self, db_connection, vectorizer, chunk_size: int = 1000):
        """
        Initialize law ingestion service
        
        Args:
            db_connection: PostgreSQL database connection
            vectorizer: Vectorizer instance for generating embeddings
            chunk_size: Size of text chunks for embedding (default: 1000 chars)
        """
        self.db = db_connection
        self.vectorizer = vectorizer
        self.chunk_size = chunk_size
    
    async def ingest_from_pdf(
        self,
        pdf_path: str,
        jurisdiction: str,
        law_category: str,
        document_title: Optional[str] = None,
        document_source: Optional[str] = None,
        effective_date: Optional[str] = None
    ) -> Dict:
        """
        Ingest a tax law PDF document into the knowledge base
        
        Args:
            pdf_path: Path to PDF file
            jurisdiction: Jurisdiction code (e.g., 'US-NY', 'EU-DE')
            law_category: Category of law (e.g., 'income_tax', 'corporate_tax')
            document_title: Title of the document
            document_source: Source URL or reference
            effective_date: When the law became effective (YYYY-MM-DD)
            
        Returns:
            Dictionary with ingestion results
        """
        try:
            logger.info(f"Ingesting law document: {pdf_path}")
            
            # Extract text from PDF
            text_chunks = await self._extract_text_from_pdf(pdf_path)
            
            if not text_chunks:
                raise ValueError("No text extracted from PDF")
            
            logger.info(f"Extracted {len(text_chunks)} chunks from PDF")
            
            # Process and store each chunk
            stored_chunks = []
            cursor = self.db.cursor()
            
            for idx, chunk in enumerate(text_chunks):
                chunk_text = chunk['text']
                section_ref = chunk.get('section_reference', f"Section {idx + 1}")
                
                # Generate embedding
                embedding = await self.vectorizer.embed_document(chunk_text)
                
                # Convert to pgvector format
                embedding_str = '[' + ','.join(map(str, embedding)) + ']'
                
                # Store in database
                cursor.execute("""
                    INSERT INTO tax_laws (
                        jurisdiction, law_category, document_title,
                        document_source, effective_date, chunk_text,
                        chunk_index, section_reference, embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                    RETURNING id
                """, (
                    jurisdiction,
                    law_category,
                    document_title or f"Tax Law Document",
                    document_source,
                    effective_date,
                    chunk_text,
                    idx,
                    section_ref,
                    embedding_str
                ))
                
                chunk_id = cursor.fetchone()[0]
                stored_chunks.append({
                    'id': chunk_id,
                    'chunk_index': idx,
                    'section_reference': section_ref
                })
            
            self.db.commit()
            cursor.close()
            
            logger.info(f"Successfully ingested {len(stored_chunks)} chunks")
            
            return {
                'success': True,
                'chunks_ingested': len(stored_chunks),
                'jurisdiction': jurisdiction,
                'law_category': law_category,
                'document_title': document_title
            }
            
        except Exception as e:
            logger.error(f"Error ingesting law document: {e}", exc_info=True)
            if self.db:
                self.db.rollback()
            raise
    
    async def _extract_text_from_pdf(self, pdf_path: str) -> List[Dict]:
        """
        Extract text from PDF and chunk it
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of text chunks with metadata
        """
        chunks = []
        
        try:
            if PyPDF2 is None:
                raise ImportError("PyPDF2 is required for PDF processing. Install it with: pip install PyPDF2")
            
            # Read PDF
            if pdf_path.startswith('http'):
                import requests
                response = requests.get(pdf_path)
                pdf_file = io.BytesIO(response.content)
            else:
                with open(pdf_path, 'rb') as f:
                    pdf_file = io.BytesIO(f.read())
            
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            current_chunk = ""
            current_section = None
            chunk_index = 0
            
            for page_num, page in enumerate(pdf_reader.pages, 1):
                page_text = page.extract_text()
                
                # Try to identify section headers
                lines = page_text.split('\n')
                for line in lines:
                    # Check if line looks like a section header
                    if self._is_section_header(line):
                        # Save current chunk if it exists
                        if current_chunk.strip():
                            chunks.append({
                                'text': current_chunk.strip(),
                                'section_reference': current_section or f"Page {page_num}",
                                'chunk_index': chunk_index
                            })
                            chunk_index += 1
                            current_chunk = ""
                        
                        current_section = line.strip()
                    
                    current_chunk += line + "\n"
                    
                    # If chunk is large enough, save it
                    if len(current_chunk) >= self.chunk_size:
                        chunks.append({
                            'text': current_chunk.strip(),
                            'section_reference': current_section or f"Page {page_num}",
                            'chunk_index': chunk_index
                        })
                        chunk_index += 1
                        current_chunk = ""
                        current_section = None
            
            # Save remaining chunk
            if current_chunk.strip():
                chunks.append({
                    'text': current_chunk.strip(),
                    'section_reference': current_section or "Final Section",
                    'chunk_index': chunk_index
                })
            
            return chunks
            
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
            raise
    
    def _is_section_header(self, line: str) -> bool:
        """
        Heuristic to identify section headers
        """
        line = line.strip()
        
        # Common patterns for section headers
        patterns = [
            r'^Section \d+',
            r'^§\s*\d+',
            r'^Article \d+',
            r'^Chapter \d+',
            r'^\d+\.\s+[A-Z]',  # Numbered sections like "1. Introduction"
            r'^[A-Z][A-Z\s]{10,}',  # All caps lines (likely headers)
        ]
        
        for pattern in patterns:
            if re.match(pattern, line):
                return True
        
        # Check if line is short and all caps (likely header)
        if len(line) < 100 and line.isupper() and len(line.split()) <= 10:
            return True
        
        return False

