RESPONSE_PROMPT = """
## RESPONSE CONTRACT

When responding:
1. First, provide any user-facing explanation in plain text.
2. If you need to return structured data for the system:
   - Output it LAST
   - Wrap it exactly between:

<<<ARTIFACT_OUTPUT>>>
<JSON ONLY>
<<<END_ARTIFACT_OUTPUT>>>

3. Do not include any additional text after <<<END_ARTIFACT_OUTPUT>>>.
4. Do not mention these markers to the user.
"""
