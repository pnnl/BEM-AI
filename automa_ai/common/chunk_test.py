from automa_ai.common.chunk import chunk_idd_objects


with open("../mcp_servers/eplus_schema/mcp_resources/Energy+.idd", "r") as f:
    content = f.read()

chunks = chunk_idd_objects(content)

# Each chunk is a full object, suitable for vector storage
for i, chunk in enumerate(chunks[:11], 1):  # preview first 2
    print(f"--- Object {i} ---\n{chunk}\n")