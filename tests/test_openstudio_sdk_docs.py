from pathlib import Path

from examples.openstudio_ai.openstudio_mcp_server.sdk_docs.lookup import (
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


def test_sdk_doc_lookup_notes_optional_return_from_signature(tmp_path: Path):
    html_file = tmp_path / "classopenstudio_1_1model_1_1_space.html"
    html_file.write_text(
        """
<html>
<head><title>OpenStudio: openstudio::model::Space Class Reference</title></head>
<body>
<div class="title">openstudio::model::Space Class Reference</div>
<a id="adef" name="adef"></a>
<h2 class="memtitle">defaultScheduleSet()</h2>
<div class="memproto"><table class="memname"><tr>
<td class="memname">boost::optional&lt; DefaultScheduleSet &gt; openstudio::model::Space::defaultScheduleSet </td>
<td>(</td><td class="paramname"></td><td>)</td><td> const</td>
</tr></table></div>
<div class="memdoc"><p>Returns the default schedule set.</p></div>
</body>
</html>
""",
        encoding="utf-8",
    )
    (tmp_path / "classopenstudio_1_1model_1_1_space.js").write_text(
        """
var classopenstudio_1_1model_1_1_space =
[
    [ "defaultScheduleSet", "classopenstudio_1_1model_1_1_space.html#adef", null ]
];
""",
        encoding="utf-8",
    )

    method_doc = OpenStudioSdkDocLookup(tmp_path).get_method(
        "Space",
        "defaultScheduleSet",
    )

    assert "boost::optional" in method_doc["signature"]
    assert any("is_initialized()" in note for note in method_doc["notes"])


def test_sdk_doc_lookup_can_disambiguate_overloaded_methods(tmp_path: Path):
    class_file = "classopenstudio_1_1model_1_1_controller_outdoor_air"
    html_file = tmp_path / f"{class_file}.html"
    html_file.write_text(
        """
<html>
<head><title>OpenStudio: openstudio::model::ControllerOutdoorAir Class Reference</title></head>
<body>
<div class="title">openstudio::model::ControllerOutdoorAir Class Reference</div>
<a id="aone" name="aone"></a>
<h2 class="memtitle">setEconomizerMaximumLimitDryBulbTemperature()</h2>
<div class="memproto"><table class="memname"><tr>
<td class="memname">bool openstudio::model::ControllerOutdoorAir::setEconomizerMaximumLimitDryBulbTemperature </td>
<td>(</td><td class="paramtype">double&nbsp;</td><td class="paramname">temperature</td><td>)</td>
</tr></table></div>
<div class="memdoc"><p>Sets the maximum dry bulb temperature.</p></div>
<a id="atwo" name="atwo"></a>
<h2 class="memtitle">setEconomizerMaximumLimitDryBulbTemperature()</h2>
<div class="memproto"><table class="memname"><tr>
<td class="memname">bool openstudio::model::ControllerOutdoorAir::setEconomizerMaximumLimitDryBulbTemperature </td>
<td>(</td><td class="paramtype">const Quantity &amp;&nbsp;</td><td class="paramname">temperature</td><td>)</td>
</tr></table></div>
<div class="memdoc"><p>Sets the maximum dry bulb temperature from a quantity.</p></div>
</body>
</html>
""",
        encoding="utf-8",
    )
    (tmp_path / f"{class_file}.js").write_text(
        """
var classopenstudio_1_1model_1_1_controller_outdoor_air =
[
    [ "setEconomizerMaximumLimitDryBulbTemperature", "classopenstudio_1_1model_1_1_controller_outdoor_air.html#aone", null ],
    [ "setEconomizerMaximumLimitDryBulbTemperature", "classopenstudio_1_1model_1_1_controller_outdoor_air.html#atwo", null ]
];
""",
        encoding="utf-8",
    )
    lookup = OpenStudioSdkDocLookup(tmp_path)

    first = lookup.get_method(
        "ControllerOutdoorAir",
        "setEconomizerMaximumLimitDryBulbTemperature",
    )
    by_anchor = lookup.get_method(
        "ControllerOutdoorAir",
        "setEconomizerMaximumLimitDryBulbTemperature",
        anchor="atwo",
    )
    by_signature = lookup.get_method(
        "ControllerOutdoorAir",
        "setEconomizerMaximumLimitDryBulbTemperature",
        signature_contains="Quantity",
    )

    assert len(first["overloads"]) == 2
    assert first["anchor"] == "aone"
    assert by_anchor["anchor"] == "atwo"
    assert "Quantity" in by_signature["signature"]


def test_sdk_doc_search_methods_clamps_large_limit(tmp_path: Path):
    html_file = tmp_path / "classopenstudio_1_1model_1_1_model.html"
    html_file.write_text(
        """
<html>
<head><title>OpenStudio: openstudio::model::Model Class Reference</title></head>
<body><div class="title">openstudio::model::Model Class Reference</div></body>
</html>
""",
        encoding="utf-8",
    )
    method_rows = ",\n".join(
        f'[ "method{i}", "classopenstudio_1_1model_1_1_model.html#a{i}", null ]'
        for i in range(250)
    )
    (tmp_path / "classopenstudio_1_1model_1_1_model.js").write_text(
        f"var classopenstudio_1_1model_1_1_model = [\n{method_rows}\n];",
        encoding="utf-8",
    )

    results = OpenStudioSdkDocLookup(tmp_path).search_methods("", limit=10_000)

    assert len(results) == 100
