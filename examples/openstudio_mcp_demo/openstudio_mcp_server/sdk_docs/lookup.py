from __future__ import annotations

import html
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class SdkDocsUnavailableError(RuntimeError):
    """Raised when the local OpenStudio SDK documentation directory is missing."""


@dataclass(frozen=True)
class MethodRef:
    """Compact pointer to one documented C++ SDK member function."""

    name: str
    anchor: str
    href: str


@dataclass
class ClassDoc:
    """Indexed metadata for one OpenStudio SDK class documentation page."""

    class_name: str
    qualified_name: str
    html_file: str
    js_file: str | None = None
    is_detail_impl: bool = False
    methods: list[MethodRef] = field(default_factory=list)


DOMAIN_CLASS_GRAPH: dict[str, dict[str, Any]] = {
    "geometry": {
        "wiki_packs": ["sdk_geometry"],
        "keywords": [
            "azimuth",
            "cardinal",
            "centroid",
            "door",
            "exterior",
            "floor area",
            "geometry",
            "north",
            "orientation",
            "roof",
            "shading",
            "space",
            "story",
            "subsurface",
            "surface",
            "tilt",
            "wall",
            "window",
            "wwr",
        ],
        "classes": [
            "Building",
            "BuildingStory",
            "PlanarSurface",
            "ShadingSurface",
            "Space",
            "SubSurface",
            "Surface",
        ],
    },
    "spaces_zones_loads": {
        "wiki_packs": ["sdk_spaces_zones_loads"],
        "keywords": [
            "area",
            "electric equipment",
            "infiltration",
            "internal load",
            "lights",
            "load",
            "occupancy",
            "people",
            "plenum",
            "space type",
            "thermal zone",
            "ventilation",
            "zone",
        ],
        "classes": [
            "ElectricEquipment",
            "ElectricEquipmentDefinition",
            "Lights",
            "LightsDefinition",
            "People",
            "PeopleDefinition",
            "Space",
            "SpaceInfiltrationDesignFlowRate",
            "SpaceType",
            "ThermalZone",
        ],
    },
    "constructions": {
        "wiki_packs": ["sdk_constructions"],
        "keywords": [
            "absorptance",
            "c-factor",
            "construction",
            "f-factor",
            "glazing",
            "insulation",
            "layer",
            "material",
            "r-value",
            "resistance",
            "shgc",
            "u-factor",
            "visible transmittance",
        ],
        "classes": [
            "CFactorUndergroundWallConstruction",
            "Construction",
            "ConstructionBase",
            "FFactorGroundFloorConstruction",
            "MasslessOpaqueMaterial",
            "Material",
            "SimpleGlazing",
            "StandardOpaqueMaterial",
        ],
    },
    "schedules": {
        "wiki_packs": ["sdk_schedules"],
        "keywords": [
            "availability",
            "day schedule",
            "default day",
            "hourly",
            "profile",
            "rule",
            "schedule",
            "schedule ruleset",
        ],
        "classes": [
            "Schedule",
            "ScheduleConstant",
            "ScheduleDay",
            "ScheduleRule",
            "ScheduleRuleset",
            "ScheduleTypeLimits",
        ],
    },
    "daylighting": {
        "wiki_packs": ["sdk_daylighting"],
        "keywords": [
            "daylight",
            "daylighting",
            "illuminance",
            "sensor",
            "setpoint",
        ],
        "classes": [
            "DaylightingControl",
            "GlareSensor",
            "IlluminanceMap",
            "Space",
        ],
    },
    "hvac": {
        "wiki_packs": ["sdk_hvac"],
        "keywords": [
            "air loop",
            "air terminal",
            "coil",
            "controller",
            "economizer",
            "fan",
            "hvac",
            "node",
            "outdoor air",
            "plant loop",
            "setpoint manager",
            "sizing",
            "thermostat",
            "zone equipment",
        ],
        "classes": [
            "AirLoopHVAC",
            "AirLoopHVACOutdoorAirSystem",
            "ControllerMechanicalVentilation",
            "ControllerOutdoorAir",
            "Node",
            "PlantLoop",
            "SetpointManagerScheduled",
            "ThermalZone",
            "ZoneHVACEquipmentList",
        ],
    },
    "simulation_results": {
        "wiki_packs": ["sdk_simulation_results"],
        "keywords": [
            "artifact",
            "eplusout",
            "osw",
            "result",
            "run",
            "simulation",
            "sql",
        ],
        "classes": ["Model", "OutputSQLite"],
    },
}


class OpenStudioSdkDocLookup:
    """Lookup helper for local Doxygen-generated OpenStudio SDK HTML docs."""

    def __init__(self, docs_dir: str | Path | None = None) -> None:
        configured = docs_dir or os.getenv("OPENSTUDIO_SDK_DOCS_DIR")
        self.docs_dir = Path(configured).expanduser().resolve() if configured else None
        self._classes: dict[str, ClassDoc] | None = None

    @classmethod
    def from_env(cls) -> "OpenStudioSdkDocLookup":
        """Create a lookup helper using `OPENSTUDIO_SDK_DOCS_DIR`."""
        return cls()

    def available(self) -> bool:
        """Return whether the configured SDK documentation directory can be used."""
        return bool(self.docs_dir and self.docs_dir.is_dir())

    def route(self, query: str, *, limit: int = 6) -> dict[str, Any]:
        """Map a user request to likely SDK wiki packs and OpenStudio classes."""
        text = query.lower()
        scored: list[tuple[int, str, dict[str, Any]]] = []
        for domain, config in DOMAIN_CLASS_GRAPH.items():
            score = 0
            for keyword in config["keywords"]:
                if keyword in text:
                    score += 2 if " " in keyword else 1
            for class_name in config["classes"]:
                if class_name.lower() in text:
                    score += 3
            if score:
                scored.append((score, domain, config))

        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = scored[:limit]
        wiki_packs: list[str] = ["sdk_index", "sdk_core_patterns"]
        classes: list[str] = []
        for _, _, config in selected:
            wiki_packs.extend(config["wiki_packs"])
            classes.extend(config["classes"])

        return {
            "domains": [
                {
                    "name": domain,
                    "score": score,
                    "wiki_packs": config["wiki_packs"],
                    "classes": config["classes"],
                }
                for score, domain, config in selected
            ],
            "wiki_packs": _dedupe(wiki_packs),
            "classes": _dedupe(classes),
            "notes": [
                "Use sdk_docs_get_method for exact constructor/getter/setter "
                "signatures before drafting SDK code.",
                "Use Python introspection when a generated Python collection "
                "getter is not present in the C++ docs.",
            ],
        }

    def find_classes(
        self,
        query: str,
        *,
        include_detail: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Find SDK classes by exact or substring match on class names."""
        classes = self._load_classes()
        normalized_query = _normalize(query)
        results: list[tuple[int, ClassDoc]] = []
        for class_doc in classes.values():
            if class_doc.is_detail_impl and not include_detail:
                continue
            name = _normalize(class_doc.class_name)
            qualified = _normalize(class_doc.qualified_name)
            if name == normalized_query:
                score = 100
            elif name.startswith(normalized_query):
                score = 80
            elif normalized_query in name:
                score = 60
            elif normalized_query in qualified:
                score = 40
            else:
                continue
            results.append((score, class_doc))
        results.sort(key=lambda item: (-item[0], item[1].class_name))
        return [
            self._class_summary(class_doc)
            for _, class_doc in results[: max(1, min(limit, 100))]
        ]

    def list_methods(
        self,
        class_name: str,
        *,
        keyword: str | None = None,
        limit: int = 80,
    ) -> dict[str, Any]:
        """List documented member functions for a class, optionally filtered."""
        class_doc = self._resolve_class(class_name)
        normalized_keyword = _normalize(keyword) if keyword else None
        methods = [
            method
            for method in class_doc.methods
            if normalized_keyword is None or normalized_keyword in _normalize(method.name)
        ]
        return {
            **self._class_summary(class_doc),
            "methods": [asdict(method) for method in methods[: max(1, min(limit, 200))]],
            "total_matches": len(methods),
        }

    def get_method(
        self,
        class_name: str,
        method_name: str,
        *,
        anchor: str | None = None,
        signature_contains: str | None = None,
    ) -> dict[str, Any]:
        """Return exact signature and documentation for one class method.

        `anchor` and `signature_contains` disambiguate overloaded methods that
        share a C++ member name but have different parameter lists.
        """
        class_doc = self._resolve_class(class_name)
        matches = [
            method
            for method in class_doc.methods
            if _normalize(method.name) == _normalize(method_name)
        ]
        if not matches:
            matches = [
                method
                for method in class_doc.methods
                if _normalize(method_name) in _normalize(method.name)
            ]
        if not matches:
            raise KeyError(f"Method not found on {class_doc.class_name}: {method_name}")

        overloads = [
            self._method_overload_summary(class_doc, method) for method in matches
        ]
        if anchor:
            matches = [
                method
                for method in matches
                if _normalize_anchor(method.anchor) == _normalize_anchor(anchor)
            ]
        if signature_contains:
            normalized_signature_contains = signature_contains.lower()
            matches = [
                method
                for method in matches
                if normalized_signature_contains
                in self._method_signature(class_doc, method).lower()
            ]
        if not matches:
            raise KeyError(
                f"Method overload not found on {class_doc.class_name}: {method_name}"
            )

        method = matches[0]
        section = self._method_section(class_doc, method.anchor)
        signature = _extract_between(section, '<div class="memproto">', "</div>")
        docs = _extract_between(section, '<div class="memdoc">', "</div>")
        clean_signature = _clean_html(signature)
        return {
            **self._class_summary(class_doc),
            "method": method.name,
            "anchor": method.anchor,
            "href": method.href,
            "signature": clean_signature,
            "documentation": _clean_html(docs),
            "source_url": self._source_url(method.href),
            "notes": _method_notes(method.name, docs, clean_signature),
            "overloads": overloads,
        }

    def search_methods(
        self,
        keyword: str,
        *,
        class_filter: str | None = None,
        include_detail: bool = False,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """Search member names across indexed SDK classes."""
        classes = self._load_classes()
        normalized_keyword = _normalize(keyword)
        normalized_class_filter = _normalize(class_filter) if class_filter else None
        bounded_limit = max(1, min(limit, 100))
        results: list[dict[str, Any]] = []
        for class_doc in classes.values():
            if class_doc.is_detail_impl and not include_detail:
                continue
            if (
                normalized_class_filter
                and normalized_class_filter not in _normalize(class_doc.class_name)
                and normalized_class_filter not in _normalize(class_doc.qualified_name)
            ):
                continue
            for method in class_doc.methods:
                if normalized_keyword not in _normalize(method.name):
                    continue
                results.append(
                    {
                        "class_name": class_doc.class_name,
                        "qualified_name": class_doc.qualified_name,
                        "method": method.name,
                        "anchor": method.anchor,
                        "href": method.href,
                        "source_url": self._source_url(method.href),
                    }
                )
                if len(results) >= bounded_limit:
                    return results
        return results

    def build_index_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable index payload for optional offline caching."""
        classes = self._load_classes()
        return {
            "docs_dir_required": (
                "Set OPENSTUDIO_SDK_DOCS_DIR to the local OpenStudio SDK HTML "
                "directory."
            ),
            "classes": [
                {
                    **self._class_summary(class_doc),
                    "methods": [asdict(method) for method in class_doc.methods],
                }
                for class_doc in classes.values()
            ],
            "class_count": len(classes),
        }

    def _load_classes(self) -> dict[str, ClassDoc]:
        self._ensure_available()
        if self._classes is not None:
            return self._classes

        assert self.docs_dir is not None
        classes: dict[str, ClassDoc] = {}
        for html_file in sorted(self.docs_dir.glob("classopenstudio_1_1model_*.html")):
            if html_file.name.endswith("-members.html"):
                continue
            text = html_file.read_text(encoding="utf-8", errors="ignore")
            qualified_name = _extract_class_name(text)
            if not qualified_name:
                continue
            class_name = qualified_name.rsplit("::", 1)[-1]
            js_file = html_file.with_suffix(".js")
            methods = _parse_methods_from_js(js_file, html_file.name)
            key = _normalize(class_name)
            classes[key] = ClassDoc(
                class_name=class_name,
                qualified_name=qualified_name,
                html_file=html_file.name,
                js_file=js_file.name if js_file.exists() else None,
                is_detail_impl="::detail::" in qualified_name or class_name.endswith("_Impl"),
                methods=methods,
            )
        self._classes = classes
        return classes

    def _resolve_class(self, class_name: str) -> ClassDoc:
        classes = self._load_classes()
        key = _normalize(class_name)
        if key in classes:
            return classes[key]
        candidates = self.find_classes(class_name, limit=5)
        if not candidates:
            raise KeyError(f"OpenStudio SDK class not found: {class_name}")
        return classes[_normalize(candidates[0]["class_name"])]

    def _method_section(self, class_doc: ClassDoc, anchor: str) -> str:
        assert self.docs_dir is not None
        html_path = self.docs_dir / class_doc.html_file
        text = html_path.read_text(encoding="utf-8", errors="ignore")
        marker = f'<a id="{anchor}"'
        start = text.find(marker)
        if start == -1:
            raise KeyError(f"Anchor not found in {class_doc.html_file}: {anchor}")
        next_match = re.search(
            r'\n<a id="[^"]+" name="[^"]+"></a>\n<h2 class="memtitle"',
            text[start + 1 :],
        )
        end = start + 1 + next_match.start() if next_match else len(text)
        return text[start:end]

    def _method_signature(self, class_doc: ClassDoc, method: MethodRef) -> str:
        section = self._method_section(class_doc, method.anchor)
        signature = _extract_between(section, '<div class="memproto">', "</div>")
        return _clean_html(signature)

    def _method_overload_summary(
        self,
        class_doc: ClassDoc,
        method: MethodRef,
    ) -> dict[str, str]:
        return {
            "method": method.name,
            "anchor": method.anchor,
            "href": method.href,
            "signature": self._method_signature(class_doc, method),
            "source_url": self._source_url(method.href),
        }

    def _source_url(self, href: str) -> str:
        if self.docs_dir is None:
            return href
        return (self.docs_dir / href.split("#", 1)[0]).as_uri() + (
            f"#{href.split('#', 1)[1]}" if "#" in href else ""
        )

    def _class_summary(self, class_doc: ClassDoc) -> dict[str, Any]:
        return {
            "class_name": class_doc.class_name,
            "qualified_name": class_doc.qualified_name,
            "html_file": class_doc.html_file,
            "js_file": class_doc.js_file,
            "is_detail_impl": class_doc.is_detail_impl,
            "method_count": len(class_doc.methods),
        }

    def _ensure_available(self) -> None:
        if not self.available():
            raise SdkDocsUnavailableError(
                "OpenStudio SDK docs are unavailable. Set OPENSTUDIO_SDK_DOCS_DIR "
                "to the local directory containing classopenstudio_1_1model_*.html files."
            )


def write_index_file(docs_dir: str | Path, output_path: str | Path) -> Path:
    """Build a compact class/method index from local SDK HTML docs."""
    lookup = OpenStudioSdkDocLookup(docs_dir)
    payload = lookup.build_index_payload()
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output


def _extract_class_name(text: str) -> str | None:
    match = re.search(
        r'<div class="headertitle">\s*'
        r'<div class="title">(.+?) Class Reference</div>\s*</div>',
        text,
    )
    if not match:
        match = re.search(r"<title>OpenStudio: (.+?) Class Reference</title>", text)
    return _clean_html(match.group(1)) if match else None


def _parse_methods_from_js(js_file: Path, html_name: str) -> list[MethodRef]:
    if not js_file.exists():
        return []
    text = js_file.read_text(encoding="utf-8", errors="ignore")
    methods: list[MethodRef] = []
    seen: set[tuple[str, str]] = set()
    pattern = re.compile(r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*null\s*\]')
    for name, href in pattern.findall(text):
        if not href.startswith(html_name + "#"):
            continue
        anchor = href.split("#", 1)[1]
        key = (name, anchor)
        if key in seen:
            continue
        seen.add(key)
        methods.append(MethodRef(name=name, anchor=anchor, href=href))
    return methods


def _extract_between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    if start == -1:
        return ""
    start += len(start_marker)
    end = text.find(end_marker, start)
    if end == -1:
        return text[start:]
    return text[start:end]


def _clean_html(text: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</p\s*>", "\n", text)
    text = re.sub(r"<.*?>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    return text.strip()


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _normalize_anchor(value: str) -> str:
    return value[1:] if value.startswith("#") else value


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _method_notes(method_name: str, docs_html: str, signature: str = "") -> list[str]:
    docs = _clean_html(docs_html).lower()
    signature_text = signature.lower()
    haystack = f"{docs} {signature_text}"
    notes: list[str] = []
    if "radians" in haystack or "radian" in haystack:
        notes.append(
            "This method documents an angle in radians. Convert with "
            "openstudio.convert(value, 'rad', 'deg') before degree-based reporting."
        )
    if "w/m" in haystack or "m^2" in haystack or "m2" in haystack:
        notes.append(
            "The documentation references SI units. Confirm or convert "
            "user-provided IP values before calling the SDK."
        )
    if "boost::optional" in haystack or method_name.startswith(("get", "optional")):
        notes.append(
            "If the Python binding returns an OpenStudio optional, check "
            "is_initialized() before get()."
        )
    if "throws" in docs:
        notes.append(
            "The documentation states this method can throw; catch exceptions "
            "or guard preconditions in generated scripts."
        )
    return notes
