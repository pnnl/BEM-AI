from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

from dotenv import load_dotenv
from mcp.server import FastMCP

from examples.openstudio_mcp_demo.openstudio_mcp_server.runtime.artifact_store import ArtifactStore
from examples.openstudio_mcp_demo.openstudio_mcp_server.runtime.job_manager import JobManager
from examples.openstudio_mcp_demo.openstudio_mcp_server.runtime.measure_registry import MeasureRegistry
from examples.openstudio_mcp_demo.openstudio_mcp_server.runtime.workspace_manager import WorkspaceManager
from examples.openstudio_mcp_demo.openstudio_mcp_server.sdk_docs import OpenStudioSdkDocLookup
from examples.openstudio_mcp_demo.openstudio_mcp_server.tools.model import register_model_tools
from examples.openstudio_mcp_demo.openstudio_mcp_server.tools.results import register_results_tools
from examples.openstudio_mcp_demo.openstudio_mcp_server.tools.schemas import (
    ModelApplyMeasureArgs,
    ModelCloneArgs,
    ModelLoadArgs,
    ModelSetDesignDaysArgs,
    ModelSetWeatherArgs,
    ResultsQueryArgs,
    ResultsSummarizeArgs,
    SimArtifactsArgs,
    SimRunArgs,
    SimStatusArgs,
    error_payload,
    success_payload,
)
from examples.openstudio_mcp_demo.openstudio_mcp_server.tools.sdk_docs import register_sdk_doc_tools
from examples.openstudio_mcp_demo.openstudio_mcp_server.tools.sim import register_sim_tools

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

ANNUAL_FUEL_TYPES = [
    "Electricity",
    "Natural Gas",
    "Additional Fuel",
    "District Cooling",
    "District Heating",
    "Water",
]
ANNUAL_END_USES = [
    "Heating",
    "Cooling",
    "Interior Lighting",
    "Exterior Lighting",
    "Interior Equipment",
    "Exterior Equipment",
    "Fans",
    "Pumps",
    "Heat Rejection",
    "Humidification",
    "Heat Recovery",
    "Water Systems",
    "Refrigeration",
    "Generators",
]
DD_FUEL_TYPES = [
    "Electricity",
    "Gas",
    "Gasoline",
    "Diesel",
    "Coal",
    "FuelOilNo1",
    "FuelOilNo2",
    "Propane",
    "OtherFuel1",
    "OtherFuel2",
    "Water",
    "DistrictCooling",
    "DistrictHeatingWater",
    "DistrictHeatingSteam",
    "ElectricityPurchased",
    "ElectricitySurplusSold",
    "ElectricityNet",
]
DD_END_USES = [
    "InteriorLights",
    "ExteriorLights",
    "InteriorEquipment",
    "ExteriorEquipment",
    "Fans",
    "Pumps",
    "Heating",
    "Cooling",
    "HeatRejection",
    "Humidifier",
    "HeatRecovery",
    "DHW",
    "Cogeneration",
    "Refrigeration",
    "WaterSystems",
]


@dataclass
class OpenStudioModelState:
    model_id: str
    metadata: dict[str, Any]


class OpenStudioService:
    def __init__(self, workspace_root: str | Path):
        self.artifacts = ArtifactStore()
        self.workspace_manager = WorkspaceManager(workspace_root)
        self.job_manager = JobManager(self.workspace_manager, self.artifacts)
        self.measure_registry = MeasureRegistry(
            policy_path=BASE_DIR / "policy" / "measure_registry.yaml",
            base_dir=BASE_DIR,
        )
        self.openstudio_path = os.getenv("OPENSTUDIO_PATH", "").strip()
        self.sdk_docs = OpenStudioSdkDocLookup.from_env()
        self._sim_tasks: dict[str, asyncio.Task] = {}
        self.model_states: dict[str, OpenStudioModelState] = {}

    def _get_model_state(self, model_id: str) -> OpenStudioModelState:
        model_state = self.model_states.get(model_id)
        if not model_state:
            raise KeyError(f"Unknown model_id: {model_id}")
        return model_state

    def model_load(self, args: ModelLoadArgs) -> dict[str, Any]:
        artifact = self.artifacts.create(
            kind="osm",
            metadata={"model_uri": args.model_uri, "loaded": True},
            parent_id=None,
        )
        self.model_states[artifact.artifact_id] = OpenStudioModelState(
            model_id=artifact.artifact_id,
            metadata={
                "model_uri": args.model_uri,
                "weather": None,
            },
        )
        return success_payload(model_id=artifact.artifact_id, metadata=artifact.to_dict())

    def model_clone(self, args: ModelCloneArgs) -> dict[str, Any]:
        base = self._get_model_state(args.model_id)
        artifact = self.artifacts.create(
            kind="osm",
            parent_id=args.model_id,
            metadata={"cloned_from": args.model_id},
        )
        self.model_states[artifact.artifact_id] = OpenStudioModelState(
            model_id=artifact.artifact_id,
            metadata={**base.metadata},
        )
        return success_payload(model_id=artifact.artifact_id)

    def model_set_weather(self, args: ModelSetWeatherArgs) -> dict[str, Any]:
        model_state = self._get_model_state(args.model_id)
        model_state.metadata["weather"] = args.epw_path
        return success_payload(model_id=args.model_id)

    def model_set_design_days(self, args: ModelSetDesignDaysArgs) -> dict[str, Any]:
        model_state = self._get_model_state(args.model_id)
        if not args.ddy_id and not args.derive_from_epw:
            raise ValueError("Provide ddy_id or set derive_from_epw=true")
        if args.derive_from_epw and not model_state.metadata.get("weather"):
            raise ValueError("Cannot derive design days without weather set")
        # Design days are usually implied by the weather file/OpenStudio workflow.
        # Keep this tool for compatibility but avoid persisting design-day metadata.
        return success_payload(model_id=args.model_id)

    def model_list_measures(self) -> dict[str, Any]:
        return success_payload(measures=self.measure_registry.list_public_specs())

    def model_apply_measure(self, args: ModelApplyMeasureArgs) -> dict[str, Any]:
        # Step 1: validate base model state. Python measures prefer the
        # OpenStudio CLI's execute_python_script environment when OPENSTUDIO_PATH
        # is configured; otherwise they fall back to the current Python only
        # after verifying that it can import the OpenStudio SDK.
        model_state = self._get_model_state(args.model_id)

        # Step 2: resolve measure policy and normalize user args from schema/defaults.
        measure_spec = self.measure_registry.get(args.measure_id)
        normalized_args = self.measure_registry.normalize_args(args.measure_id, args.args)
        source_model_path = self._resolve_model_path(model_state.metadata.get("model_uri", ""))
        if not source_model_path.exists():
            raise ValueError(f"Model file does not exist: {source_model_path}")

        # Step 3: create an isolated workspace and stage input/output model paths.
        workspace_id = f"measure-{uuid4()}"
        workspace = self.workspace_manager.create_workspace(workspace_id)
        input_osm = workspace / "in.osm"
        output_osm = workspace / "out.osm"
        stdout_path = workspace / "measure.stdout.log"
        stderr_path = workspace / "measure.stderr.log"
        shutil.copy2(source_model_path, input_osm)

        # Step 4: execute the OpenStudio Python measure as a child process.
        env = os.environ.copy()
        env["OSM_INPUT_PATH"] = str(input_osm)
        env["OSM_OUTPUT_PATH"] = str(output_osm)
        env["MEASURE_ARGS_JSON"] = json.dumps(normalized_args)
        openstudio_cmd = self._openstudio_executable_or_none()
        if measure_spec.entrypoint.suffix == ".py":
            if openstudio_cmd is not None:
                cmd = [
                    openstudio_cmd,
                    "execute_python_script",
                    str(measure_spec.entrypoint),
                ]
            else:
                self._validate_python_openstudio_sdk(workspace=workspace, env=env)
                cmd = [sys.executable, str(measure_spec.entrypoint)]
        else:
            if openstudio_cmd is None:
                raise ValueError(
                    "OPENSTUDIO_PATH is not set to an executable OpenStudio path."
                )
            cmd = [openstudio_cmd, "execute_python_script", str(measure_spec.entrypoint)]

        try:
            completed = subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                check=False,
                timeout=measure_spec.timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"Measure timed out after {measure_spec.timeout_seconds}s: {args.measure_id}") from exc

        # Step 5: persist logs and verify the measure produced an output OSM.
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        if completed.returncode != 0:
            raise ValueError(
                f"Measure '{args.measure_id}' failed with return code {completed.returncode}. "
                f"See {stderr_path}."
            )
        if not output_osm.exists():
            raise ValueError(
                f"Measure '{args.measure_id}' completed without output model: {output_osm}"
            )

        # Step 6: register a new immutable model artifact/state for downstream tool calls.
        summary = self._extract_measure_summary(completed.stdout)
        output_artifact = self.artifacts.create(
            kind="osm",
            parent_id=args.model_id,
            metadata={
                "model_uri": output_osm.as_uri(),
                "measure_id": args.measure_id,
                "measure_args": normalized_args,
                "measure_stdout_path": str(stdout_path),
                "measure_stderr_path": str(stderr_path),
            },
        )
        self.model_states[output_artifact.artifact_id] = OpenStudioModelState(
            model_id=output_artifact.artifact_id,
            metadata={
                "model_uri": output_osm.as_uri(),
                "weather": model_state.metadata.get("weather"),
            },
        )
        self.workspace_manager.ensure_quota(workspace_id)

        # Step 7: return human-readable changes/warnings from measure stdout JSON summary.
        summary_changes = summary.get("changes", []) if isinstance(summary.get("changes"), list) else []
        summary_warnings = summary.get("warnings", []) if isinstance(summary.get("warnings"), list) else []
        changes = summary_changes or [f"Applied measure {args.measure_id}"]
        return success_payload(
            model_id=output_artifact.artifact_id,
            changes=changes,
            warnings=summary_warnings,
        )

    def _openstudio_executable_or_none(self) -> str | None:
        if not self.openstudio_path:
            return None
        openstudio_path = Path(self.openstudio_path)
        if openstudio_path.is_file() and os.access(openstudio_path, os.X_OK):
            return str(openstudio_path)
        return None

    def _validate_python_openstudio_sdk(
        self,
        *,
        workspace: Path,
        env: dict[str, str],
    ) -> None:
        import_check = subprocess.run(
            [sys.executable, "-c", "import openstudio"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if import_check.returncode != 0:
            raise ValueError(
                "Python measure execution requires the OpenStudio Python SDK. "
                "Configure OPENSTUDIO_PATH to the OpenStudio executable so measures "
                "run via execute_python_script, or install the openstudio module "
                "into the server's Python environment."
            )

    def model_validate(self, args: ModelCloneArgs) -> dict[str, Any]:
        model_state = self._get_model_state(args.model_id)
        issues: list[dict[str, Any]] = []
        if not model_state.metadata.get("weather"):
            issues.append({"severity": "warning", "message": "Weather not set."})
        status = "valid" if not issues else "valid_with_warnings"
        return success_payload(status=status, issues=issues)

    def sim_run(self, args: SimRunArgs) -> dict[str, Any]:
        model_state = self._get_model_state(args.model_id)
        model_path = self._resolve_model_path(model_state.metadata.get("model_uri", ""))
        if not model_path.exists():
            raise ValueError(f"Model file does not exist: {model_path}")
        if not self.openstudio_path:
            raise ValueError("OPENSTUDIO_PATH is not set in environment.")
        if not Path(self.openstudio_path).exists():
            raise ValueError(f"OPENSTUDIO_PATH is not executable path: {self.openstudio_path}")
        job = self.job_manager.create_job(
            model_id=args.model_id,
            run_mode=args.run_mode,
            options=args.options,
        )
        return success_payload(job_id=job.job_id)

    async def schedule_simulation(
        self,
        *,
        job_id: str,
        model_id: str,
        options: dict[str, Any],
    ) -> None:
        task = asyncio.create_task(self._run_simulation_async(job_id=job_id, model_id=model_id, options=options))
        self._sim_tasks[job_id] = task

    async def _run_simulation_async(
        self,
        *,
        job_id: str,
        model_id: str,
        options: dict[str, Any],
    ) -> None:
        try:
            self.job_manager.mark_running(job_id, progress=5)
            result = await asyncio.to_thread(
                self._run_openstudio_cli_sync,
                job_id,
                model_id,
                options,
            )
            self.job_manager.mark_succeeded(
                job_id,
                artifacts=result["artifacts"],
                warnings_count=result.get("warnings_count", 0),
                severe_count=result.get("severe_count", 0),
            )
        except Exception as exc:
            self.job_manager.fail(
                job_id,
                error=error_payload(
                    "simulation_error",
                    str(exc),
                    details={"job_id": job_id},
                    retryable=False,
                )["error"],
            )
        finally:
            self._sim_tasks.pop(job_id, None)

    def sim_status(self, args: SimStatusArgs) -> dict[str, Any]:
        job = self.job_manager.get(args.job_id)
        if not job:
            raise KeyError(f"Unknown job_id: {args.job_id}")
        return success_payload(
            state=job.state,
            progress=job.progress,
            warnings_count=job.warnings_count,
            severe_count=job.severe_count,
            error=job.error,
        )

    def sim_artifacts(self, args: SimArtifactsArgs) -> dict[str, Any]:
        job = self.job_manager.get(args.job_id)
        if not job:
            raise KeyError(f"Unknown job_id: {args.job_id}")
        if job.state != "SUCCEEDED":
            raise ValueError(f"Artifacts unavailable while state={job.state}")
        return success_payload(**job.artifacts)

    def results_query(self, args: ResultsQueryArgs) -> dict[str, Any]:
        artifact = self.artifacts.must_get(args.sql_id)
        if artifact.kind != "sql":
            raise KeyError(f"Artifact is not a sql artifact: {args.sql_id}")
        sql_path_raw = artifact.metadata.get("path")
        if not isinstance(sql_path_raw, str) or not sql_path_raw:
            raise ValueError(f"SQL artifact missing path metadata: {args.sql_id}")
        sql_path = Path(sql_path_raw).resolve()
        if not sql_path.exists():
            raise ValueError(f"SQL file not found: {sql_path}")

        with sqlite3.connect(str(sql_path)) as conn:
            if args.query_type == "annual_end_use_fuel":
                data = self._query_annual_end_use_by_fuel(conn)
            elif args.query_type == "design_day_end_use_fuel":
                data = self._query_design_day_end_use_by_fuel(conn)
            elif args.query_type == "annual_eui":
                data = self._query_annual_eui(conn)
            elif args.query_type == "sizing_summary":
                data = {
                    "annual_end_use_fuel_gj": self._query_annual_end_use_by_fuel(conn),
                    "design_day_end_use_fuel_j": self._query_design_day_end_use_by_fuel(conn),
                    "annual_eui": self._query_annual_eui(conn),
                }
            else:
                raise ValueError(f"Unsupported query_type: {args.query_type}")
        return success_payload(data=data)

    def results_summarize(self, args: ResultsSummarizeArgs) -> dict[str, Any]:
        if isinstance(args.data, dict):
            keys = sorted(args.data.keys())
            summary_text = f"Sizing summary generated for keys: {', '.join(keys)}"
            tables = [{"name": "top_level", "columns": ["key"], "rows": [[k] for k in keys]}]
        else:
            summary_text = "Sizing summary generated."
            tables = []
        return success_payload(summary_text=summary_text, tables=tables)

    def sdk_docs_route(self, *, query: str, limit: int = 6) -> dict[str, Any]:
        return self.sdk_docs.route(query=query, limit=limit)

    def sdk_docs_find_classes(
        self,
        *,
        query: str,
        include_detail: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self.sdk_docs.find_classes(
            query=query,
            include_detail=include_detail,
            limit=limit,
        )

    def sdk_docs_list_methods(
        self,
        *,
        class_name: str,
        keyword: str | None = None,
        limit: int = 80,
    ) -> dict[str, Any]:
        return self.sdk_docs.list_methods(
            class_name=class_name,
            keyword=keyword,
            limit=limit,
        )

    def sdk_docs_get_method(self, *, class_name: str, method_name: str) -> dict[str, Any]:
        return self.sdk_docs.get_method(class_name=class_name, method_name=method_name)

    def sdk_docs_search_methods(
        self,
        *,
        keyword: str,
        class_filter: str | None = None,
        include_detail: bool = False,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        return self.sdk_docs.search_methods(
            keyword=keyword,
            class_filter=class_filter,
            include_detail=include_detail,
            limit=limit,
        )

    def _resolve_model_path(self, model_uri: str) -> Path:
        if model_uri.startswith("file://"):
            parsed = urlparse(model_uri)
            decoded_path = unquote(parsed.path)
            return Path(decoded_path).resolve()
        return Path(model_uri).resolve()

    def _resolve_weather_path(self, model_state: OpenStudioModelState, options: dict[str, Any]) -> Path:
        weather_opt = options.get("epw_path") if isinstance(options, dict) else None
        model_path = self._resolve_model_path(model_state.metadata.get("model_uri", ""))
        weather_candidate = weather_opt or model_state.metadata.get("weather")
        if not weather_candidate:
            weather_candidate = self._extract_weather_path_from_osm(model_path)
        if not weather_candidate:
            raise ValueError(
                "Weather file is required. Use model_set_weather, pass options.epw_path, "
                "or include OS:WeatherFile path in the model."
            )
        weather_path = self._resolve_path_with_model_context(str(weather_candidate), model_path)
        if not weather_path.exists():
            raise ValueError(f"Weather file does not exist: {weather_path}")
        return weather_path

    def _resolve_path_with_model_context(self, candidate: str, model_path: Path) -> Path:
        if candidate.startswith("file://"):
            return self._resolve_model_path(candidate)
        path = Path(candidate).expanduser()
        if path.is_absolute():
            return path.resolve()
        return (model_path.parent / path).resolve()

    def _extract_weather_path_from_osm(self, model_path: Path) -> str | None:
        try:
            text = model_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None
        # OpenStudio OSM stores weather path in OS:WeatherFile as the field with comment "!- Url".
        for line in text.splitlines():
            if "!- Url" not in line:
                continue
            raw = line.split("!- Url", 1)[0].strip()
            raw = re.sub(r"[;,]\s*$", "", raw)
            raw = raw.strip()
            if raw:
                return raw
        return None

    def _run_openstudio_cli_sync(
        self,
        job_id: str,
        model_id: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        model_state = self._get_model_state(model_id)
        model_path = self._resolve_model_path(model_state.metadata.get("model_uri", ""))
        weather_path = self._resolve_weather_path(model_state, options)

        workspace = self.workspace_manager.create_workspace(job_id)
        run_dir = workspace / "run"
        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)

        osm_target = workspace / "in.osm"
        shutil.copy2(model_path, osm_target)
        epw_target = workspace / weather_path.name
        shutil.copy2(weather_path, epw_target)

        osw_path = workspace / "in.osw"
        osw_payload = {
            "seed_file": osm_target.name,
            "weather_file": epw_target.name,
            "run_directory": "run",
            "steps": [],
        }
        osw_path.write_text(json.dumps(osw_payload, indent=2), encoding="utf-8")

        stdout_path = workspace / "openstudio.stdout.log"
        stderr_path = workspace / "openstudio.stderr.log"
        cmd = [self.openstudio_path, "run", "-w", str(osw_path)]
        completed = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
        )
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")

        self.job_manager.mark_running(job_id, progress=80)

        if completed.returncode != 0:
            raise ValueError(
                f"OpenStudio CLI failed with return code {completed.returncode}. See {stderr_path}."
            )

        sql_path = run_dir / "eplusout.sql"
        err_path = run_dir / "eplusout.err"
        end_path = run_dir / "eplusout.end"

        if not sql_path.exists():
            err_text = err_path.read_text(encoding="utf-8", errors="ignore") if err_path.exists() else ""
            raise ValueError(
                "Simulation did not produce eplusout.sql. "
                f"Error log: {err_text[:4000]}"
            )

        end_text = end_path.read_text(encoding="utf-8", errors="ignore") if end_path.exists() else ""
        if "EnergyPlus Completed Successfully" not in end_text:
            err_text = err_path.read_text(encoding="utf-8", errors="ignore") if err_path.exists() else ""
            raise ValueError(
                "EnergyPlus did not report successful completion. "
                f"Error log: {err_text[:4000]}"
            )

        severe_count = 0
        warning_count = 0
        if err_path.exists():
            err_content = err_path.read_text(encoding="utf-8", errors="ignore")
            severe_count = err_content.count("** Severe **")
            warning_count = err_content.count("** Warning **")

        osm_art = self.artifacts.create(
            kind="osm",
            parent_id=model_id,
            metadata={"job_id": job_id, "path": str(osm_target)},
        )
        sql_art = self.artifacts.create(
            kind="sql",
            parent_id=osm_art.artifact_id,
            metadata={"job_id": job_id, "path": str(sql_path)},
        )
        logs_art = self.artifacts.create(
            kind="logs",
            parent_id=osm_art.artifact_id,
            metadata={
                "job_id": job_id,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "err_path": str(err_path) if err_path.exists() else None,
            },
        )
        report_art = self.artifacts.create(
            kind="report",
            parent_id=sql_art.artifact_id,
            metadata={"job_id": job_id, "path": str(end_path) if end_path.exists() else None},
        )

        self.workspace_manager.ensure_quota(job_id)
        return {
            "artifacts": {
                "osm_id": osm_art.artifact_id,
                "sql_id": sql_art.artifact_id,
                "logs_id": logs_art.artifact_id,
                "report_id": report_art.artifact_id,
            },
            "severe_count": severe_count,
            "warnings_count": warning_count,
        }

    @staticmethod
    def _parse_float(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(",", "")
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return 0.0

    def _query_annual_end_use_by_fuel(self, conn: sqlite3.Connection) -> dict[str, float]:
        query = """
            SELECT Value
            FROM TabularDataWithStrings
            WHERE ReportName='AnnualBuildingUtilityPerformanceSummary'
              AND ReportForString='Entire Facility'
              AND TableName='End Uses'
              AND RowName=?
              AND ColumnName=?
            LIMIT 1
        """
        results: dict[str, float] = {}
        for end_use in ANNUAL_END_USES:
            for fuel_type in ANNUAL_FUEL_TYPES:
                row = conn.execute(query, (end_use, fuel_type)).fetchone()
                key = f"{end_use}|{fuel_type}"
                results[key] = self._parse_float(row[0]) if row else 0.0
        return results

    def _query_design_day_end_use_by_fuel(self, conn: sqlite3.Connection) -> dict[str, float]:
        idx_query = """
            SELECT ReportMeterDataDictionaryIndex
            FROM ReportMeterDataDictionary
            WHERE VariableName=?
            LIMIT 1
        """
        sum_query = """
            SELECT SUM(VariableValue)
            FROM ReportMeterData
            WHERE ReportMeterDataDictionaryIndex=?
        """
        results: dict[str, float] = {}
        for end_use in DD_END_USES:
            for fuel_type in DD_FUEL_TYPES:
                meter_name = f"{end_use}:{fuel_type}"
                idx_row = conn.execute(idx_query, (meter_name,)).fetchone()
                key = f"{end_use}|{fuel_type}"
                if not idx_row:
                    results[key] = 0.0
                    continue
                sum_row = conn.execute(sum_query, (idx_row[0],)).fetchone()
                results[key] = self._parse_float(sum_row[0]) if sum_row else 0.0
        return results

    def _query_annual_eui(self, conn: sqlite3.Connection) -> dict[str, float]:
        site_energy_query = """
            SELECT Value
            FROM TabularDataWithStrings
            WHERE ReportName='AnnualBuildingUtilityPerformanceSummary'
              AND ReportForString='Entire Facility'
              AND TableName='Site and Source Energy'
              AND RowName='Total Site Energy'
              AND ColumnName='Total Energy'
            LIMIT 1
        """
        floor_area_query = """
            SELECT Value
            FROM TabularDataWithStrings
            WHERE ReportName='AnnualBuildingUtilityPerformanceSummary'
              AND ReportForString='Entire Facility'
              AND TableName='Building Area'
              AND RowName='Total Building Area'
              AND ColumnName='Area'
            LIMIT 1
        """
        site_row = conn.execute(site_energy_query).fetchone()
        area_row = conn.execute(floor_area_query).fetchone()
        total_site_energy_gj = self._parse_float(site_row[0]) if site_row else 0.0
        floor_area_m2 = self._parse_float(area_row[0]) if area_row else 0.0

        total_site_energy_kbtu = total_site_energy_gj * 947.817
        floor_area_ft2 = floor_area_m2 * 10.7639
        site_eui_kbtu_per_ft2 = (
            total_site_energy_kbtu / floor_area_ft2 if floor_area_ft2 > 0 else 0.0
        )

        return {
            "total_site_energy_gj": total_site_energy_gj,
            "floor_area_m2": floor_area_m2,
            "floor_area_ft2": floor_area_ft2,
            "site_eui_kbtu_per_ft2": site_eui_kbtu_per_ft2,
        }

    @staticmethod
    def _extract_measure_summary(stdout_text: str | None) -> dict[str, Any]:
        if not stdout_text:
            return {}
        for line in reversed(stdout_text.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
        return {}


def create_server(
    *,
    host: str = "127.0.0.1",
    port: int = 10210,
    workspace_root: str | Path | None = None,
) -> FastMCP:
    workspace = Path(workspace_root or ".openstudio_mcp_workspace")
    service = OpenStudioService(workspace_root=workspace)
    mcp = FastMCP("openstudio-mcp", host=host, port=port)

    register_model_tools(mcp, service)
    register_sim_tools(mcp, service)
    register_results_tools(mcp, service)
    register_sdk_doc_tools(mcp, service)

    return mcp


def serve(
    host: str = "127.0.0.1",
    port: int = 10210,
    transport: str = "stdio",
    workspace_root: str | None = None,
) -> None:
    mcp = create_server(host=host, port=port, workspace_root=workspace_root)
    mcp.run(transport=transport)


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenStudio MCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10210)
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    parser.add_argument("--workspace-root", default=None)
    args = parser.parse_args()
    serve(
        host=args.host,
        port=args.port,
        transport=args.transport,
        workspace_root=args.workspace_root,
    )


if __name__ == "__main__":
    main()
