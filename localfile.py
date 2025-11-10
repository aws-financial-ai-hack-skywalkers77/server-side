from pathlib import Path
from landingai_ade import LandingAIADE
import json



schema_dict = { 
    "type": "object",
    "properties": {
        "order_id": {"type": "string", "description": "The order number or ID"},
        "summary": {"type": "string", "description": "A brief summary or description of the order"},
    },
    "required": ["order_id", "summary"]
}



client = LandingAIADE()

schema_json = json.dumps(schema_dict)
# Replace with your file path
response = client.parse(
    document=Path("/Users/hemanth/landingAI/invoice.pdf"),
    model="dpt-2-latest"
)

extraction_response = client.extract(
    schema=schema_json,
    markdown=response.markdown,
    model="extract-latest"
)
print(extraction_response.extraction)

