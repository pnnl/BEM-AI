import os
import re
from typing import List, Tuple, Dict, Optional

import chromadb
import yaml
from chromadb.utils import embedding_functions
from mcp.server import FastMCP
from mcp.server.fastmcp.utilities.logging import get_logger

from automa_ai.common.chunk import chunk_idd_objects

logger = get_logger(__name__)

COMMONLY_USED_EPLUS_OBJECTS = [
            "Building", "Zone", "Space", "BuildingSurface:Detailed", "Window", "Door", "Construction",
            "Material", "Material:NoMass","Schedule:Compact", "ZoneHVAC:IdealLoadsAirSystem",
            "Lights", "People", "ElectricEquipment", "GasEquipment",
            "ZoneInfiltration:DesignFlowRate", "ZoneVentilation:DesignFlowRate",
            "Sizing:Zone", "Sizing:System", "AirLoopHVAC", "BranchList",
            "AirLoopHVAC:ZoneSplitter", "AirLoopHVAC:ZoneMixer", "Fan:ConstantVolume",
            "Coil:Heating:Electric", "Coil:Cooling:DX:SingleSpeed", "Boiler:HotWater",
            "Chiller:Electric:EIR", "PlantLoop", "Pump:ConstantSpeed", "Pump:VariableSpeed",
            "SetpointManager:Scheduled", "Controller:WaterCoil", "ZoneControl:Thermostat",
            "ThermostatSetpoint:DualSetpoint", "Output:Variable", "Output:Meter"
        ]

############## These are functions to generate the chromaDB
############## Not needed unless it requires reindexing.
def clean_idd_spec(spec_text: str) -> str:
    """
    Fast, simplified cleaning of IDD spec text.
    """
    # Just remove backslash commands and limit length - much faster
    cleaned = re.sub(r'\\[a-zA-Z]+\s*', '', spec_text)
    cleaned = re.sub(r'\n\s*', ' ', cleaned)
    return cleaned.strip()[:300]  # Limit to 300 chars for speed

# Main function to load, chunk, embed, and save to ChromaDB
def process_idd_to_chromadb(idd_path: str, collection_name: str = "idd_chunks", batch_size: int = 100):
    # Load IDD content
    with open(idd_path, "r", encoding="utf-8") as f:
        idd_text = f.read()

    # Chunk into objects
    chunks = chunk_idd_objects(idd_text)

    print(f"Processing {len(chunks)} chunks...")
    # Prepare ChromaDB persistent directory
    server_dir = os.path.dirname(os.path.abspath(__file__))
    chroma_dir = os.path.join(server_dir, "mcp_resources", collection_name)
    os.makedirs(chroma_dir, exist_ok=True)

    # Initialize ChromaDB
    client = chromadb.PersistentClient(path=chroma_dir)

    # Delete existing collection if it exists
    try:
        client.delete_collection(name=collection_name)
    except:
        pass

    # Create new collection
    collection = client.create_collection(name=collection_name, embedding_function=embedding_functions.DefaultEmbeddingFunction())
    print("Created new collection")

    # Process in batches to avoid memory issues and provide progress feedback
    total_batches = (len(chunks) + batch_size - 1) // batch_size
    for batch_idx in range(0, len(chunks), batch_size):
        batch_chunks = chunks[batch_idx:batch_idx + batch_size]
        batch_num = (batch_idx // batch_size) + 1

        print(f"Processing batch {batch_num}/{total_batches} ({len(batch_chunks)} items)...")

        # Prepare data for embedding
        documents = []
        metadatas = []
        ids = []

        for i, (object_name, spec_text) in enumerate(chunks):
            actual_idx = batch_idx + i

            # Create a search-friendly document that emphasizes object name
            cleaned_spec = clean_idd_spec(spec_text)

            # Create document that starts with object name for better matching
            # Repeat object name and add cleaned spec
            search_document = f"{object_name} {object_name.replace(':', ' ')} {cleaned_spec}"

            documents.append(search_document)
            metadatas.append({
                "object_name": object_name,
                "original_spec": spec_text,
                "cleaned_spec": cleaned_spec
            })
            ids.append(f"idd_chunk_{i}")

        try:
            # Add batch to collection
            collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            print(f"  ✓ Added batch {batch_num} successfully")

        except Exception as e:
            print(f"  ✗ Error adding batch {batch_num}: {e}")
            # Continue with next batch instead of failing completely
            continue
    final_count = collection.count()
    print(f"✅ Created ChromaDB collection '{collection_name}' with {final_count} chunks")
    return collection


############## These are functions to query the idd
def query_idd_chunks(user_query: str, top_k: int = 5, collection_name: str = "idd_chunks") -> List[dict]:
    """
    Retrieve top K IDD object chunks from ChromaDB based on semantic similarity.

    :param user_query: Natural language query from user
    :param top_k: Number of top results to return
    :param collection_name: ChromaDB collection name
    :return: List of dicts with keys: 'object_name', 'text', 'id', and 'distance'
    """
    server_dir = os.path.dirname(os.path.abspath(__file__))
    chroma_dir = os.path.join(server_dir, "mcp_resources", collection_name)

    client = chromadb.PersistentClient(path=chroma_dir)
    collection = client.get_collection(name=collection_name, embedding_function=embedding_functions.DefaultEmbeddingFunction())

    # Enhanced query that emphasizes object names
    # Create variations of the query that might match object names better
    query_variations = [
        user_query,
        user_query.replace(" ", ""),  # Remove spaces
        user_query.replace(" ", ":"),  # Replace spaces with colons
        f"object {user_query}",  # Add "object" prefix
    ]

    all_results = {}
    for query_var in query_variations:
        var_results = collection.query(
            query_texts=[query_var],
            n_results=top_k
        )

        # Add results to combined results
        for i, doc_id in enumerate(var_results['ids'][0]):
            if doc_id not in all_results or var_results['distances'][0][i] < all_results[doc_id]['distance']:
                all_results[doc_id] = {
                    "id": doc_id,
                    "text": var_results["documents"][0][i],
                    "object_name": var_results["metadatas"][0][i].get("object_name", ""),
                    "cleaned_spec": var_results["metadatas"][0][i].get("cleaned_spec", ""),
                    "original_spec": var_results["metadatas"][0][i].get("original_spec", ""),
                    "distance": var_results["distances"][0][i]
                }
    # Sort by distance and return top_k
    sorted_results = sorted(all_results.values(), key=lambda x: x['distance'])[:top_k]
    return sorted_results


def fuzzy_object_name_search_from_db(user_query: str, collection_name: str = "idd_chunks", top_k: int = 5) -> List[
    Dict]:
    """
        Fallback function for direct object name matching using fuzzy string matching.
        Gets data directly from ChromaDB.
    """
    from difflib import SequenceMatcher

    def similarity(a, b):
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    server_dir = os.path.dirname(os.path.abspath(__file__))
    chroma_dir = os.path.join(server_dir, "mcp_resources", collection_name)

    client = chromadb.PersistentClient(path=chroma_dir)
    collection = client.get_collection(name=collection_name)

    # Get all items from the collection
    all_items = collection.get()

    # Score each object name against the query
    scored_objects = []
    for i, (doc_id, metadata) in enumerate(zip(all_items['ids'], all_items['metadatas'])):
        object_name = metadata.get('object_name', '')
        if object_name not in COMMONLY_USED_EPLUS_OBJECTS:
            # Skip all objects that are not in the commonly used eplus objects
            continue

        # Calculate similarity scores
        name_score = similarity(user_query, object_name)

        if user_query.lower() == object_name.lower():
            name_score = name_score * 5.0
        elif user_query.lower() in object_name.lower() or object_name.lower() in user_query.lower():
            # Boost the name_score for matching - IMPORTANT!!!! This only works with limited set of commonly used eplus objects
            name_score = name_score * 2.5

        name_parts_score = max([similarity(user_query, part) for part in object_name.split(':')] + [0])

        best_score = max(name_score, name_parts_score)

        scored_objects.append({
            "id": doc_id,
            "object_name": object_name,
            "text": all_items['documents'][i],
            "cleaned_spec": metadata.get('cleaned_spec', ''),
            "original_spec": metadata.get('original_spec', ''),
            "similarity_score": best_score,
            "distance": 1 - best_score  # Convert to distance-like metric
        })

    # Sort by similarity score and return top results
    sorted_objects = sorted(scored_objects, key=lambda x: x['similarity_score'], reverse=True)[:top_k]

    return sorted_objects


def query_idd_chunks_simple(user_query: str, top_k: int = 5, collection_name: str = "idd_chunks") -> List[Dict]:
    """
    Simplified query function that combines semantic search with fuzzy name matching.
    No external chunks parameter needed.
    """
    try:
        # Try semantic search first
        semantic_results = query_idd_chunks(user_query, top_k, collection_name)

        # If semantic search gives poor results (high distances), try fuzzy matching
        if not semantic_results or (semantic_results and semantic_results[0]['distance'] > 0.9):
            fuzzy_results = fuzzy_object_name_search_from_db(user_query, collection_name, top_k)

            # Combine and deduplicate results
            combined_results = {}

            # Add fuzzy results first (they might be more relevant for name-based queries)
            for result in fuzzy_results:
                combined_results[result['object_name']] = result

            # Add semantic results
            for result in semantic_results:
                if result['object_name'] not in combined_results:
                    combined_results[result['object_name']] = result

            return list(combined_results.values())[:top_k]

        return semantic_results

    except Exception as e:
        print(f"Semantic search failed: {e}")
        # Fallback to fuzzy matching
        return fuzzy_object_name_search_from_db(user_query, collection_name, top_k)


###########Parse the IDD data schema to yml
def parse_idd_chunk(chunk: str) -> Dict:
    lines = chunk.strip().splitlines()
    if not lines:
        return {}

    object_name_line = lines[0].strip()
    object_name = object_name_line.rstrip(",")
    fields = []
    field_index = 0

    object_metadata_patterns = {
        "memo": re.compile(r"\\memo\s+(.+)", re.IGNORECASE),
        "min_fields": re.compile(r"\\min-fields\s+(\d+)", re.IGNORECASE),
        "extensible": re.compile(r"\\extensible\s+(\d+)", re.IGNORECASE),
    }

    # Matches: "  A1, \field Some Field Name"
    field_line_regex = re.compile(r"^\s*(A|N)(\d+)\s*[,;]\s*\\field\s+(.+)")
    attr_patterns = {
        "data_type": re.compile(r"\\type\s+(\w+)"),
        "required": re.compile(r"\\required-field"),
        "default": re.compile(r"\\default\s+(.+)"),
        "units": re.compile(r"\\units\s+(.+)"),
        "minimum": re.compile(r"\\minimum\s+(.+)"),
        "minimum>": re.compile(r"\\minimum>\s+(.+)"),
        "object-list": re.compile(r"\\object-list\s+(.+)"),
        "reference": re.compile(r"\\reference\s+(.+)")
    }

    current_field = None
    metadata = {
        "memo": None,
        "min_fields": None,
        "extensible": None,
    }

    def finalize_field(f):
        if f:
            # Remove empty optional fields for cleanliness
            f = {k: v for k, v in f.items() if v not in ([], None)}
            fields.append(f)
    field_count = 0
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith("!"):
            continue

        # Parse object-level metadata
        for key, pattern in object_metadata_patterns.items():
            match = pattern.search(line)
            if match:
                metadata[key] = int(match.group(1)) if key != "memo" else match.group(1).strip()

        field_match = field_line_regex.match(line)
        if field_match:
            finalize_field(current_field)
            field_count += 1
            idf_type = f"{field_match.group(1)}{field_match.group(2)}"
            name = field_match.group(3).strip()

            field_index += 1
            current_field = {
                "idf_type": idf_type,
                "order": field_index,
                "name": name,
                "required": False,
                "data_type": None,
                "options": [],
                "object_list": [],
            }
            continue

        #if metadata["min_fields"] and field_count > metadata["min_fields"]:
            # at this point, we dont want to continue
        #    break

        if current_field:
            for attr, pattern in attr_patterns.items():
                match = pattern.search(line)
                if match:
                    if attr == "required":
                        current_field["required"] = True
                    elif match.groups():
                        value = match.group(1).strip()
                        if attr == "key":
                            current_field["options"].append(value)
                        elif attr == "object-list":
                            current_field["object_list"].append(value)
                        else:
                            current_field[attr] = value

    finalize_field(current_field)

    # Only keep min_fields number of fields if specified
    min_fields = metadata.get("min_fields")
    if min_fields is not None:
        fields = fields[:min_fields]

    return {
        "ObjectName": object_name,
        **metadata,
        "Fields": fields,
    }


def format_schema_yaml(schema_dict: Dict) -> str:
    return yaml.dump(schema_dict, sort_keys=False, width=120)


############ EnergyPlus related functions ###############

def extract_idf_objects(file_path: str, object_name: str) -> List[str]:
    """
    Extracts all instances of a given EnergyPlus object from a valid IDF file.

    Args:
        file_path (str): Path to the IDF file.
        object_name (str): Name of the object type to extract (case-insensitive match).

    Returns:
        List[str]: List of matching object strings (each ending with ';').
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File does not exist: {file_path}")

    if not file_path.lower().endswith(".idf"):
        raise ValueError("Provided file is not an .idf file")

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    objects = []
    collecting = False
    buffer = []
    object_name_lower = object_name.lower()
    semicolon_terminated = re.compile(r";\s*(?:!.*)?$")

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("!"):
            continue  # Skip comments and blank lines

        # Detect start of object
        if not collecting and stripped.lower().startswith(f"{object_name_lower},"):
            collecting = True
            buffer = [stripped]
            continue

        if collecting:
            buffer.append(stripped)
            if semicolon_terminated.search(stripped):
                objects.append("\n ".join(buffer))
                collecting = False
                buffer = []

    return objects

def serve(host, port, transport):
    """Initialize and runs the agent cards mcp_servers server.
    Args:
        host: The hostname or IP address to bind the server to.
        port: The port number to bind the server to.
        transport: The transport mechanism for the MCP server (e.g., 'stdio', 'sse')

    Raises:
        ValueError
    """
    logger.info("Starting EnergyPlus MCP Server")
    mcp = FastMCP("eplus-tools", host=host, port=port)

    @mcp.tool(
        name="find_energyplus_object_schema",
        description="Finds the most relevant EnergyPlus object schema based on a natural language query string.",
    )
    def find_energyplus_object_schema(object_type: str, top_k: int =3) -> list[dict]:
        """
        Finds the top 3 most relevant EnergyPlus object schemas.

        This function takes a user query, typically a natural language question or a task generated by an agent,
        generates its embedding, and compares it against the
        pre-computed embedding of the loaded EnergyPlus schema. It uses the multiple fuzzy logics to measure distance and identifies the objects with the lowest distance score.

        Args:
            object_type: The natural language object type string used to search for a relevant agent.
            top_k: int, indicate how many results to retrieve. Top k must be greater than 1
        Returns:
            The json representing the agent card deemed most relevant to the input query based on embedding similarity.
        """
        results = query_idd_chunks_simple(object_type, top_k=top_k)
        if results[top_k-1]["distance"] < 0.9:
            return [parse_idd_chunk(result['original_spec']) for result in results]
        else:
            return  [{"message": "Failed to find the matching object and its schema, need to refine user query"}]

    @mcp.tool(
        name="find_multiple_energyplus_object_schemas",
        description="Finds the most relevant EnergyPlus object schemas based on a list of object type query string.",
    )
    def find_multiple_energyplus_object_schemas(object_types: list[str]) -> Dict[str, dict]:
        """
        Finds the top 3 most relevant EnergyPlus object schemas.

        This function takes a user query, typically a natural language question or a task generated by an agent,
        generates its embedding, and compares it against the
        pre-computed embedding of the loaded EnergyPlus schema. It uses the multiple fuzzy logics to measure distance and identifies the objects with the lowest distance score.

        Args:
            object_type: The natural language object type string used to search for a relevant agent.
            top_k: int, indicate how many results to retrieve. Top k must be greater than 1
        Returns:
            A dictionary include the object type and its schema in a dict.
        """
        schema_dict = {}
        for t in object_types:
            results = query_idd_chunks_simple(t, top_k=1)
            if results[0]["distance"] < 0.9:
                schema_dict[results[0].get("object_name")] =  parse_idd_chunk(results[0]['original_spec'])

        if schema_dict:
            return schema_dict
        else:
            return  {"message": {"message": "Failed to find the matching object and its schema, need to refine user query"}}

    @mcp.tool(
        name="load_idf_objects_by_object_type",
        description="Load a list of EnergyPlus objects by their object type",
    )
    def load_idf_objects_by_object_type(object_type: str, file_path: str) -> List[str]:
        # results = query_idd_chunks_simple(object_name, top_k=3)
        # if results[0]["distance"] < 0.9:
        #    object_name = results[0]["object_name"]
        #else:
        #    return ["Failed to find the matching object, need to refine user query"]

        try:
            matched_object_list = extract_idf_objects(file_path, object_type)
            if matched_object_list:
                return matched_object_list
            else:
                return [f"The provided EnergyPlus file does not contain the object: {object_type}"]
        except Exception as e:
            return [f"Failed searching for object {object_type}. Please sort the EnergyPlus file."]

    @mcp.tool(
        name="fetch_object_types_by_reference",
        description="Given an EnergyPlus reference name (e.g., 'MaterialName'), return a list of object types that can be referenced by that name. This is useful for tracing inter-object dependencies, such as which objects can be used in a Construction layer or Zone equipment list."
    )
    def fetch_object_types_by_reference(reference_name: str, top_k: int = 50) -> List[str]:
        """
        Find all EnergyPlus object types whose schema contains a field that declares
        a `\\reference` tag matching the given reference name.

        Args:
            reference_name (str): The reference tag name (e.g., 'MaterialName')
            top_k (int): Number of object schemas to search. Default is 50.

        Returns:
            List[str]: A list of object names that can be referenced via this reference name.
        """
        matched_objects = []
        chunks = query_idd_chunks_simple(reference_name, top_k=top_k)

        for r in chunks:
            try:
                schema = parse_idd_chunk(r['original_spec'])
                for field in schema.get("Fields", []):
                    if field.get("reference") == reference_name:
                        matched_objects.append(schema["ObjectName"])
                        break
            except Exception as e:
                print(f"Error parsing schema: {e}")

        return matched_objects

    @mcp.tool(
        name="get_object_by_name_and_name_value",
        description="Retrieve a specific EnergyPlus object from an IDF file by the object name and the object name value. This function scans the file to locate an object whose name field matches the given object name value and returns the full IDF object as a string."
    )
    def get_object_by_name_and_name_value(
            file_path: str,
            object_name: str,
            object_name_value: str
    ) -> Optional[str]:
        """
        Given a full IDF file text, return a specific object block by type and name field.

        Parameters:
        - file_path (str): The IDF file path
        - object_type (str): The EnergyPlus object type to search for (e.g., "Material").
        - name_value (str): The name value of the object (assumed to be in A1 position).

        Returns:
        - str: The full IDF object text block as a string, or None if not found.
        """

        objects = extract_idf_objects(file_path, object_name)
        for obj in objects:
            lines = [line.strip() for line in obj.splitlines() if line.strip()]
            if not lines:
                continue

            # Extract the first data field after the object type
            if lines[0].lower().startswith(object_name.lower()):
                for line in lines[1:]:
                    stripped = line.split("!", 1)[0].strip()  # remove comment
                    if stripped.endswith(",") or stripped.endswith(";"):
                        value = stripped.rstrip(",;").strip('"')
                        if value.lower() == object_name_value.lower():
                            return obj
                        break  # only check first field

        return None

    @mcp.tool(
        name="get_commonly_used_energyplus_objects",
        description="A list of EnergyPlus object types that are commonly used for building energy modeling"
    )
    def get_commonly_used_energyplus_objects() -> List[str]:
        return COMMONLY_USED_EPLUS_OBJECTS

    @mcp.tool(
        name="filter_objects_by_value",
        description="Filter EnergyPlus object strings in a list by matching the user provided value with any of the object field."
    )
    def filter_object_list_by_value(object_list: List[str], value: str) -> List[str]:
        """
        Filters a list of IDF object strings and returns only those where any field matches the regex pattern.

        Args:
            object_list (List[str]): List of IDF object strings.
            value (str): Regex pattern to match against object fields.

        Returns:
            List[str]: Filtered list of objects where the pattern matches any field.
        """
        filtered = []
        pattern = re.compile(value, re.IGNORECASE)

        for obj in object_list:
            # Remove comments and trailing semicolons, then split by commas
            fields = [part.strip().strip(';') for part in obj.split(',') if
                      part.strip() and not part.strip().startswith('!')]
            if any(pattern.search(field) for field in fields[1:]):  # skip object type (fields[0])
                filtered.append(obj)

        return filtered

    logger.info(f"EnergyPlus Server at {host}:{port} and transport {transport}")
    mcp.run(transport=transport)

# if __name__ == "__main__":
    # process_idd_to_chromadb("mcp_resources/Energy+.idd")
    # Query examples
#    test_queries = [
#       "version"
#    ]
#    for query in test_queries:
#       results = query_idd_chunks_simple(query, top_k=3)
#       print(f"Testing query {query}")
#       for i, r in enumerate(results, 1):
#            print(f"\n--- Chunk {i}: {r['object_name']} (distance: {r['distance']:.4f}) ---")
#            print(r)
#            print(parse_idd_chunk(r['original_spec']))

#if __name__ == "__main__":
    #  results = query_idd_chunks_simple("Construction", top_k=1)
    # print(results)

#   query = ['Building', 'Zone', 'Space', 'Construction', 'Material', 'Surface']
#   for q in query:
#        print("query: ", q)
#        results = query_idd_chunks_simple(q, top_k=1)
#        print(parse_idd_chunk(results[0]["original_spec"]))

# if __name__ == "__main__":
#    test_queries = [
#        "Sizing:Zone"
#    ]
#    objects = extract_idf_objects("/Users/xuwe123/Library/CloudStorage/OneDrive-PNNL/Desktop/in.idf", "Sizing:Zone")
#    print(objects)