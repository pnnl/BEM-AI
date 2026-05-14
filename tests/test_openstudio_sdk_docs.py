from pathlib import Path

from examples.openstudio_mcp_demo.openstudio_mcp_server.sdk_docs.lookup import (
    OpenStudioSdkDocLookup,
)


def test_sdk_doc_lookup_extracts_class_methods_and_method_docs(tmp_path: Path):
    html_file = tmp_path / "classopenstudio_1_1model_1_1_planar_surface.html"
    html_file.write_text(
        """
<html>
<head><title>OpenStudio: openstudio::model::PlanarSurface Class Reference</title></head>
<body>
<div class="headertitle">
<div class="title">openstudio::model::PlanarSurface Class Reference</div>
</div>
<a id="a0788" name="a0788"></a>
<h2 class="memtitle"><span class="permalink"><a href="#a0788">x</a></span>azimuth()</h2>
<div class="memitem">
<div class="memproto"><table class="memname"><tr>
<td class="memname">double openstudio::model::PlanarSurface::azimuth </td>
<td>(</td><td class="paramname"></td><td>)</td><td> const</td>
</tr></table></div>
<div class="memdoc">
<p>Returns the surface's azimuth measured clockwise as angle between outward
normal and local North (radians).</p>
<p>Throws openstudio::Exception if cannot compute outward normal for this surface.</p>
</div>
</div>
</body>
</html>
""",
        encoding="utf-8",
    )
    (tmp_path / "classopenstudio_1_1model_1_1_planar_surface.js").write_text(
        """
var classopenstudio_1_1model_1_1_planar_surface =
[
    [ "azimuth", "classopenstudio_1_1model_1_1_planar_surface.html#a0788", null ]
];
""",
        encoding="utf-8",
    )

    lookup = OpenStudioSdkDocLookup(tmp_path)

    assert lookup.find_classes("PlanarSurface")[0]["class_name"] == "PlanarSurface"
    assert lookup.list_methods("PlanarSurface", keyword="azimuth")["total_matches"] == 1

    method_doc = lookup.get_method("PlanarSurface", "azimuth")

    assert "double openstudio::model::PlanarSurface::azimuth" in method_doc["signature"]
    assert "radians" in method_doc["documentation"]
    assert any("radians" in note for note in method_doc["notes"])


def test_sdk_doc_route_returns_wiki_packs_for_geometry_request(tmp_path: Path):
    # The routing graph is deterministic and does not require local SDK docs.
    lookup = OpenStudioSdkDocLookup(tmp_path)

    result = lookup.route("Compute WWR by orientation from exterior wall azimuths")

    assert "sdk_geometry" in result["wiki_packs"]
    assert "PlanarSurface" in result["classes"]
