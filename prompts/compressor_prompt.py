TERMINAL_CHUNK_COMPRESSOR_PROMPT = """
Reasoning budget: LOW.
You are summarizing terminal output.

Goal:
{goal}

Command:
{command}

Output Chunk:
{chunk}

Rules:

1. Preserve important information.
2. Preserve filenames.
3. Preserve paths.
4. Preserve errors.
5. Remove noise.
6. Keep summary under 200 characters.

Return JSON:

{{
    "summary": "..."
}}
"""

TERMINAL_REDUCER_PROMPT = """
Reasoning budget: LOW.
You are combining summaries of terminal output.

Goal:
{goal}

Summaries:

{summaries}

Rules:

1. Merge important information.
2. Remove duplicates.
3. Preserve errors.
4. Keep under 500 characters.

Return JSON:

{{
    "summary": "..."
}}
"""