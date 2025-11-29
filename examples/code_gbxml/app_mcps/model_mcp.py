# examples/gbxml/app_mcps/model_mcp.py
import argparse
import json
import logging
from pathlib import Path
from typing import Dict, List, Union

from lxml import etree
import xgbxml

from mcp.server import FastMCP
from mcp.server.fastmcp.utilities.logging import get_logger
# --- Simple local registry  ---
REGISTERED_TOOLS: list[str] = []
# -------- Logging: console + file --------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("gbxml_mcp_server.log", mode="w", encoding="utf-8"),
    ],
)
logger = get_logger(__name__)

# -------- Paths --------
SCRIPT_DIR = Path(__file__).parent
REQUESTS_DIR = SCRIPT_DIR / "requests"
REQUESTS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_GBXML = SCRIPT_DIR.parent / "gbxml_file" / "SF_model_Output_OS.xml"

# -------- gbXML helpers (no type hints that confuse JSON schema) --------
def _parser():
    return xgbxml.get_parser("0.37")

def _load_root(gbxml_path: Union[str, Path]):
    p = Path(gbxml_path)
    if not p.exists():
        raise FileNotFoundError(f"gbXML not found: {p}")
    tree = etree.parse(str(p), _parser())
    return tree.getroot()

def _ns(root):
    return {"gb": root.nsmap.get(None) or root.nsmap.get("gb")}

def _surface_list(root) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for s in getattr(root.Campus, "Surfaces", []):
        try:
            surf_type = getattr(s, "surfaceType", None) or s.get("surfaceType", "")
            az = getattr(s, "Azimuth", None)
            try:
                area_val = s.get_area()
            except Exception:
                area_val = ""
            items.append(
                {
                    "id": getattr(s, "id", "unknown"),
                    "type": str(surf_type),
                    "has_geometry": "yes" if hasattr(s, "RectangularGeometry") else "no",
                    "azimuth": str(az.value if hasattr(az, "value") else ""),
                    "area_m2_hint": str(area_val),
                }
            )
        except Exception:
            items.append({"id": getattr(s, "id", "unknown"), "type": "unknown"})
    return items

def _surface_by_id(root, surface_id: str):
    return next(
        (s for s in getattr(root.Campus, "Surfaces", []) if getattr(s, "id", "") == surface_id),
        None,
    )

def _construction_by_id(root, cid: str):
    return next((c for c in getattr(root, "Constructions", []) if getattr(c, "id", "") == cid), None)

def _material_by_id(root, mid: str):
    return next((m for m in getattr(root, "Materials", []) if getattr(m, "id", "") == mid), None)

def _layer_R_value(root, layer_id: str) -> float:
    layer = next((l for l in getattr(root, "Layers", []) if getattr(l, "id", "") == layer_id), None)
    if not layer:
        return 0.0
    try:
        mid = layer.get_child("MaterialId").get("materialIdRef", "")
    except Exception:
        return 0.0
    material = _material_by_id(root, mid)
    if not material:
        return 0.0
    try:
        thickness = float(material.get_child("Thickness").value)
        conductivity = float(material.get_child("Conductivity").value)
        return thickness / conductivity if conductivity > 0 else 0.0
    except Exception:
        return 0.0

def _construction_R_value(root, construction_id: str) -> float:
    cons = _construction_by_id(root, construction_id)
    if not cons:
        return 0.0
    try:
        layer_ids = [li.get("layerIdRef", "") for li in getattr(cons, "LayerIds", [])]
    except Exception:
        layer_ids = []
    Rs = [_layer_R_value(root, lid) for lid in layer_ids if lid]
    return sum(Rs) if Rs and all(r > 0 for r in Rs) else 0.0

def _surface_tilt_deg(root, surface) -> str:
    try:
        node = surface.findtext("gb:RectangularGeometry/gb:Tilt", "", namespaces=_ns(root))
        return node or ""
    except Exception:
        return ""

# -------- Pure compute (no Optional in signatures) --------
def compute_list_surfaces(gbxml_path: str, save_response_as: str) -> str:
    try:
        if not gbxml_path:
            gbxml_path = str(DEFAULT_GBXML)
        root = _load_root(gbxml_path)
        text = json.dumps({"surfaces": _surface_list(root)}, indent=2)
        if save_response_as:
            (REQUESTS_DIR / save_response_as).write_text(text, encoding="utf-8")
        return text
    except Exception as e:
        logger.exception("list_surfaces failed")
        return json.dumps({"error": str(e)})

def compute_list_constructions(gbxml_path: str, save_response_as: str) -> str:
    try:
        if not gbxml_path:
            gbxml_path = str(DEFAULT_GBXML)
        root = _load_root(gbxml_path)
        rows = [{"id": getattr(c, "id", "unknown")} for c in getattr(root, "Constructions", [])]
        text = json.dumps({"constructions": rows}, indent=2)
        if save_response_as:
            (REQUESTS_DIR / save_response_as).write_text(text, encoding="utf-8")
        return text
    except Exception as e:
        logger.exception("list_constructions failed")
        return json.dumps({"error": str(e)})

def compute_surface_area(gbxml_path: str, surface_id: str, save_response_as: str) -> str:
    try:
        if not gbxml_path:
            gbxml_path = str(DEFAULT_GBXML)
        root = _load_root(gbxml_path)
        s = _surface_by_id(root, surface_id)
        if not s:
            return json.dumps({"error": f"Surface {surface_id} not found."})
        try:
            area = s.get_area()
        except Exception:
            area = ""
        res = {"surface_id": surface_id, "area_m2": area}
        if save_response_as:
            (REQUESTS_DIR / save_response_as).write_text(json.dumps(res, indent=2), encoding="utf-8")
        return json.dumps(res, indent=2)
    except Exception as e:
        logger.exception("get_surface_area failed")
        return json.dumps({"error": str(e)})

def compute_surface_tilt(gbxml_path: str, surface_id: str, save_response_as: str) -> str:
    try:
        if not gbxml_path:
            gbxml_path = str(DEFAULT_GBXML)
        root = _load_root(gbxml_path)
        s = _surface_by_id(root, surface_id)
        if not s:
            return json.dumps({"error": f"Surface {surface_id} not found."})
        tilt = _surface_tilt_deg(root, s)
        res = {"surface_id": surface_id, "tilt_degrees": tilt}
        if save_response_as:
            (REQUESTS_DIR / save_response_as).write_text(json.dumps(res, indent=2), encoding="utf-8")
        return json.dumps(res, indent=2)
    except Exception as e:
        logger.exception("get_surface_tilt failed")
        return json.dumps({"error": str(e)})

def compute_surface_insulation(gbxml_path: str, surface_id: str, save_response_as: str) -> str:
    try:
        if not gbxml_path:
            gbxml_path = str(DEFAULT_GBXML)
        root = _load_root(gbxml_path)
        s = _surface_by_id(root, surface_id)
        if not s:
            return json.dumps({"error": f"Surface {surface_id} not found."})
        cons_id = getattr(s, "constructionIdRef", None) or s.get("constructionIdRef", "")
        if not cons_id:
            return json.dumps({"error": f"Surface {surface_id} has no construction assigned."})
        R = _construction_R_value(root, cons_id)
        res = {"surface_id": surface_id, "construction_id": cons_id, "R_m2K_per_W": R}
        if save_response_as:
            (REQUESTS_DIR / save_response_as).write_text(json.dumps(res, indent=2), encoding="utf-8")
        return json.dumps(res, indent=2)
    except Exception as e:
        logger.exception("get_surface_insulation failed")
        return json.dumps({"error": str(e)})

# -------- FastMCP server --------
def serve(host: str, port: int, transport: str):
    logger.info("=== Starting gbXML MCP Server on %s:%s (%s) ===", host, port, transport)
    mcp = FastMCP("agent-cards", host=host, port=port)

    @mcp.tool(name="ping", description="Connectivity test.")
    def ping() -> str:
        return "pong"
    REGISTERED_TOOLS.append("ping"); logger.info("Registered tool: ping")

    @mcp.tool(name="debug_list_tools", description="Return server tool names for debugging.")
    def debug_list_tools() -> str:
        return json.dumps({"tools": REGISTERED_TOOLS}, indent=2)
    REGISTERED_TOOLS.append("debug_list_tools"); logger.info("Registered tool: debug_list_tools")

    @mcp.tool(name="list_surfaces", description="List surfaces with ids and basic properties.")
    def list_surfaces(gbxml_path: str = "", save_response_as: str = "") -> str:
        return compute_list_surfaces(gbxml_path, save_response_as)
    REGISTERED_TOOLS.append("list_surfaces"); logger.info("Registered tool: list_surfaces")

    @mcp.tool(name="list_constructions", description="List construction IDs present in the file.")
    def list_constructions(gbxml_path: str = "", save_response_as: str = "") -> str:
        return compute_list_constructions(gbxml_path, save_response_as)
    REGISTERED_TOOLS.append("list_constructions"); logger.info("Registered tool: list_constructions")

    @mcp.tool(name="get_surface_area", description="Return area (m²) of a surface by id.")
    def get_surface_area(gbxml_path: str, surface_id: str, save_response_as: str = "") -> str:
        return compute_surface_area(gbxml_path, surface_id, save_response_as)
    REGISTERED_TOOLS.append("get_surface_area"); logger.info("Registered tool: get_surface_area")

    @mcp.tool(name="get_surface_tilt", description="Return tilt (degrees) of a surface by id.")
    def get_surface_tilt(gbxml_path: str, surface_id: str, save_response_as: str = "") -> str:
        return compute_surface_tilt(gbxml_path, surface_id, save_response_as)
    REGISTERED_TOOLS.append("get_surface_tilt"); logger.info("Registered tool: get_surface_tilt")

    @mcp.tool(name="get_surface_insulation", description="Return insulation R-value (m²·K/W) for a surface by id.")
    def get_surface_insulation(gbxml_path: str, surface_id: str, save_response_as: str = "") -> str:
        return compute_surface_insulation(gbxml_path, surface_id, save_response_as)
    REGISTERED_TOOLS.append("get_surface_insulation"); logger.info("Registered tool: get_surface_insulation")

    # Final banner with our own registry list (no private attributes)
    logger.info("Registered tools (local): %s", REGISTERED_TOOLS)

    mcp.run(transport=transport)

# -------- CLI --------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="gbXML MCP")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_srv = sub.add_parser("serve", help="Run the MCP server")
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=10160)
    p_srv.add_argument("--transport", choices=["stdio", "sse"], default="sse")

    p_ls = sub.add_parser("ls", help="List surfaces")
    p_ls.add_argument("--gbxml-path", default=str(DEFAULT_GBXML))
    p_ls.add_argument("--save-response-as", default="")

    p_lc = sub.add_parser("lc", help="List constructions")
    p_lc.add_argument("--gbxml-path", default=str(DEFAULT_GBXML))
    p_lc.add_argument("--save-response-as", default="")

    p_area = sub.add_parser("area", help="Surface area (m²)")
    p_area.add_argument("--gbxml-path", default=str(DEFAULT_GBXML))
    p_area.add_argument("--surface-id", required=True)
    p_area.add_argument("--save-response-as", default="")

    p_tilt = sub.add_parser("tilt", help="Surface tilt (deg)")
    p_tilt.add_argument("--gbxml-path", default=str(DEFAULT_GBXML))
    p_tilt.add_argument("--surface-id", required=True)
    p_tilt.add_argument("--save-response-as", default="")

    p_r = sub.add_parser("rvalue", help="Surface insulation R (m²·K/W)")
    p_r.add_argument("--gbxml-path", default=str(DEFAULT_GBXML))
    p_r.add_argument("--surface-id", required=True)
    p_r.add_argument("--save-response-as", default="")

    args = parser.parse_args()
    if args.cmd == "serve":
        serve(args.host, args.port, args.transport)
    elif args.cmd == "ls":
        print(compute_list_surfaces(args.gbxml_path, args.save_response_as))
    elif args.cmd == "lc":
        print(compute_list_constructions(args.gbxml_path, args.save_response_as))
    elif args.cmd == "area":
        print(compute_surface_area(args.gbxml_path, args.surface_id, args.save_response_as))
    elif args.cmd == "tilt":
        print(compute_surface_tilt(args.gbxml_path, args.surface_id, args.save_response_as))
    elif args.cmd == "rvalue":
        print(compute_surface_insulation(args.gbxml_path, args.surface_id, args.save_response_as))
