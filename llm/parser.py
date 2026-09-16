import json
import re

def clean_llm_output(output: str) -> str:
    # Remove markdown code blocks like ```json ... ```
    output = re.sub(r"```json\s*", "", output)
    output = re.sub(r"```", "", output)

    # Trim whitespace
    return output.strip()

def parse_llm_output(output: str):
    try:
        cleaned_out = clean_llm_output(output)
        # print(json.loads(cleaned_out))
        return json.loads(cleaned_out)
    except Exception as e:
        # print(json.loads(output))
        raise ValueError(f"Invalid JSON from LLM: {output}")
    # return json.loads(output)