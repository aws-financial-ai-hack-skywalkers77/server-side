import logging
import boto3
from botocore.exceptions import ClientError
import fitz  # PyMuPDF
from io import BytesIO
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)

class PDFHighlighter:
    """Highlights bounding boxes on PDF documents and uploads to S3"""
    
    def __init__(self):
        self.s3_client = boto3.client('s3', region_name=Config.AWS_REGION)
    
    def download_pdf_from_s3(self, s3_key: str) -> bytes:
        """
        Download PDF from S3.
        
        Args:
            s3_key: S3 object key
            
        Returns:
            PDF file content as bytes
        """
        try:
            logger.info(f"Downloading PDF from S3: {s3_key}")
            response = self.s3_client.get_object(
                Bucket=Config.S3_BUCKET_NAME,
                Key=s3_key
            )
            pdf_content = response['Body'].read()
            logger.info(f"Successfully downloaded PDF ({len(pdf_content)} bytes)")
            return pdf_content
        except ClientError as e:
            logger.error(f"Error downloading PDF from S3: {e}")
            raise Exception(f"Failed to download PDF from S3: {str(e)}")
    
    def highlight_bboxes(self, pdf_content: bytes, violations: list) -> bytes:
        """
        Highlight bounding boxes on PDF for violations.
        
        Args:
            pdf_content: Original PDF file content as bytes
            violations: List of violation dicts with pdf_location metadata
            
        Returns:
            Highlighted PDF content as bytes
        """
        try:
            # Open PDF from bytes
            pdf_document = fitz.open(stream=pdf_content, filetype="pdf")
            
            # Group violations by page number
            violations_by_page = {}
            for violation in violations:
                pdf_location = violation.get("pdf_location")
                if not pdf_location:
                    continue
                
                page_number = pdf_location.get("page_number")
                if page_number is None:
                    continue
                
                if page_number not in violations_by_page:
                    violations_by_page[page_number] = []
                violations_by_page[page_number].append(pdf_location)
            
            # Highlight each page
            for page_num, page_violations in violations_by_page.items():
                # Page numbers are 1-indexed, fitz uses 0-indexed
                page_index = page_num - 1
                if page_index < 0 or page_index >= len(pdf_document):
                    logger.warning(f"Page number {page_num} out of range, skipping")
                    continue
                
                page = pdf_document[page_index]
                page_rect = page.rect
                
                # Highlight each bounding box
                for pdf_location in page_violations:
                    bbox = pdf_location.get("bbox")
                    if not bbox:
                        continue
                    
                    # Get normalized coordinates (0-1 range)
                    left = bbox.get("left", 0)
                    top = bbox.get("top", 0)
                    right = bbox.get("right", 0)
                    bottom = bbox.get("bottom", 0)
                    
                    # Convert normalized coordinates to page coordinates
                    x0 = left * page_rect.width
                    y0 = top * page_rect.height
                    x1 = right * page_rect.width
                    y1 = bottom * page_rect.height
                    
                    # Create rectangle for highlighting
                    rect = fitz.Rect(x0, y0, x1, y1)
                    
                    # Draw red border rectangle only (no fill) so text remains fully visible
                    shape = page.new_shape()
                    shape.draw_rect(rect)
                    # Red border only, no fill - text will be completely visible
                    shape.finish(fill=None, color=(1, 0, 0), width=2)
                    shape.commit()
                    
                    logger.debug(f"Highlighted bbox on page {page_num}: ({x0:.2f}, {y0:.2f}) to ({x1:.2f}, {y1:.2f})")
            
            # Save to bytes
            output_buffer = BytesIO()
            pdf_document.save(output_buffer)
            pdf_document.close()
            
            highlighted_pdf = output_buffer.getvalue()
            logger.info(f"Successfully highlighted PDF ({len(highlighted_pdf)} bytes)")
            return highlighted_pdf
            
        except Exception as e:
            logger.error(f"Error highlighting PDF: {e}", exc_info=True)
            raise Exception(f"Failed to highlight PDF: {str(e)}")
    
    def upload_highlighted_pdf_to_s3(self, pdf_content: bytes, original_s3_key: str) -> str:
        """
        Upload highlighted PDF to S3 with a new key.
        
        Args:
            pdf_content: Highlighted PDF content as bytes
            original_s3_key: Original S3 key to derive new key from
            
        Returns:
            Presigned S3 URL of the uploaded highlighted PDF
        """
        try:
            # Generate new S3 key for highlighted PDF
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            # Extract original filename and add _highlighted suffix
            if "/" in original_s3_key:
                path_parts = original_s3_key.rsplit("/", 1)
                directory = path_parts[0]
                filename = path_parts[1]
            else:
                directory = ""
                filename = original_s3_key
            
            # Add _highlighted before file extension
            if "." in filename:
                name, ext = filename.rsplit(".", 1)
                highlighted_filename = f"{name}_highlighted.{ext}"
            else:
                highlighted_filename = f"{filename}_highlighted"
            
            if directory:
                highlighted_s3_key = f"{directory}/{highlighted_filename}"
            else:
                highlighted_s3_key = highlighted_filename
            
            logger.info(f"Uploading highlighted PDF to S3: {highlighted_s3_key}")
            
            # Upload to S3
            self.s3_client.put_object(
                Bucket=Config.S3_BUCKET_NAME,
                Key=highlighted_s3_key,
                Body=pdf_content,
                ContentType="application/pdf"
            )
            
            # Generate presigned URL (valid for 1 hour)
            presigned_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': Config.S3_BUCKET_NAME, 'Key': highlighted_s3_key},
                ExpiresIn=3600  # 1 hour
            )
            
            logger.info(f"Successfully uploaded highlighted PDF to S3: {highlighted_s3_key}")
            return presigned_url
            
        except ClientError as e:
            logger.error(f"Error uploading highlighted PDF to S3: {e}")
            raise Exception(f"Failed to upload highlighted PDF to S3: {str(e)}")
    
    def get_original_pdf_url(self, s3_key: str, expires_in: int = 3600) -> str:
        """
        Get presigned URL for the original PDF.
        
        Args:
            s3_key: Original PDF S3 key
            expires_in: Expiration time in seconds (default: 1 hour)
            
        Returns:
            Presigned S3 URL
        """
        try:
            presigned_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': Config.S3_BUCKET_NAME, 'Key': s3_key},
                ExpiresIn=expires_in
            )
            return presigned_url
        except ClientError as e:
            logger.error(f"Error generating presigned URL for original PDF: {e}")
            raise Exception(f"Failed to generate presigned URL: {str(e)}")
    
    def process_invoice_pdf(self, s3_key: str, violations: list) -> str:
        """
        Complete workflow: download PDF, highlight violations, upload to S3.
        If no violations found, returns original PDF URL.
        
        Args:
            s3_key: Original PDF S3 key
            violations: List of violation dicts with pdf_location metadata
            
        Returns:
            Presigned S3 URL of the highlighted PDF (if violations found) or original PDF (if no violations)
        """
        try:
            # Filter violations that have pdf_location
            violations_with_location = [
                v for v in violations 
                if v.get("pdf_location") and v.get("pdf_location").get("bbox")
            ]
            
            if not violations_with_location:
                logger.info("No violations with bounding box locations found, returning original PDF URL")
                # Return original PDF URL if no violations
                return self.get_original_pdf_url(s3_key)
            
            logger.info(f"Processing PDF highlighting for {len(violations_with_location)} violations")
            
            # Download PDF
            pdf_content = self.download_pdf_from_s3(s3_key)
            
            # Highlight violations
            highlighted_pdf = self.highlight_bboxes(pdf_content, violations_with_location)
            
            # Upload highlighted PDF
            highlighted_url = self.upload_highlighted_pdf_to_s3(highlighted_pdf, s3_key)
            
            return highlighted_url
            
        except Exception as e:
            logger.error(f"Error processing invoice PDF: {e}", exc_info=True)
            # If highlighting fails, try to return original PDF URL as fallback
            try:
                logger.warning("Falling back to original PDF URL due to highlighting error")
                return self.get_original_pdf_url(s3_key)
            except Exception as fallback_error:
                logger.error(f"Failed to get original PDF URL: {fallback_error}")
                return None

