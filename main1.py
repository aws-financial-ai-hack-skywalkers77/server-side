import fitz # PyMuPDF is imported as fitz

def highlight_with_normalized_coords(input_pdf, output_pdf, page_num, normalized_coords):
    """
    Highlights a specific area in a PDF using normalized box coordinates (0 to 1).

    Args:
        input_pdf (str): Path to the input PDF.
        output_pdf (str): Path to save the output PDF.
        page_num (int): The 0-indexed page number to highlight.
        normalized_coords (tuple): A tuple of (x0, y0, x1, y1) normalized values (0 to 1).
    """
    doc = fitz.open(input_pdf)
    if page_num >= len(doc):
        print(f"Error: Page number {page_num} is out of range.")
        doc.close()
        return

    page = doc[page_num]

    # Get the actual page dimensions in points
    page_width = page.rect.width
    page_height = page.rect.height

    # Unpack the normalized coordinates
    nx0, ny0, nx1, ny1 = normalized_coords

    # Convert normalized coordinates to actual page coordinates
    x0 = nx0 * page_width
    y0 = ny0 * page_height
    x1 = nx1 * page_width
    y1 = ny1 * page_height

    # Create a Rect object from the scaled coordinates
    highlight_area = fitz.Rect(x0, y0, x1, y1)

    # Add the highlight annotation
    page.add_highlight_annot(highlight_area)

    # Save the document
    doc.save(output_pdf, garbage=4, deflate=True, clean=True)
    doc.close()
    print(f"PDF with normalized highlight saved to {output_pdf}")

# Example usage: Highlight an area covering 25% of the page starting from the top-left
# Normalized coordinates (0, 0) top-left, (0.5, 0.5) bottom-right of a 50% section
highlight_with_normalized_coords("invoice.pdf", "output_normalized_highlighted.pdf", 0, (0.21678294241428375, 0.5876372456550598, 0.10942608118057251, 0.5520867705345154))
