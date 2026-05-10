---
name: sdk_simulation_results
description: OpenStudio Python SDK idioms for simulation files, OSW setup, SQL attachment, and result extraction.
version: 0.1.0
---

# SDK Simulation and Results Context

This pack documents source-observed simulation and SQL idioms. In the
OpenStudio MCP demo, actual simulation execution, polling, artifact retrieval,
and result summaries belong to MCP `sim_*` and `results_*` tools. Do not use
`run_python` to launch OpenStudio CLI, shell commands, or subprocesses.

Use this pack when explaining existing scripts, understanding result artifacts,
or drafting a non-executed review plan.

## Forward Translate Model to IDF

```python
forward_translator = openstudio.energyplus.ForwardTranslator()
idf = forward_translator.translateModel(model)
idf.save(openstudio.path(f"{run_dir}/in.idf"), True)
model.save(openstudio.path(f"{run_dir}/in.osm"), True)
```

This translates an OpenStudio model to EnergyPlus IDF and saves both model and
IDF inputs. In this demo, prefer MCP simulation workflows instead of doing this
inside `run_python`.

## Prepare WorkflowJSON

```python
model.resetSqlFile()
workflow = openstudio.WorkflowJSON()
workflow.setSeedFile("in.osm")
workflow.setWeatherFile(epw_name)
workflow.saveAs(os.path.abspath(str(osw_path)))
```

`resetSqlFile()` detaches a previous SQL result from the model before a new run.
`WorkflowJSON` defines the seed OSM and weather file for an OpenStudio CLI run.

## Attach SQL File to Model

```python
sql_path = openstudio.path(os.path.join(run_dir, "run", "eplusout.sql"))
if openstudio.exists(sql_path):
    sql = openstudio.SqlFile(sql_path)
    if sql.connectionOpen():
        model.setSqlFile(sql)
```

This checks for a SQL result file, opens it, verifies the connection, and
attaches it to the model.

## Query Severe and Fatal Errors

```python
query = "SELECT ErrorMessage FROM Errors WHERE ErrorType in(1,2)"
errs_optional = model.sqlFile().get().execAndReturnVectorOfString(query)
errs = errs_optional.get() if errs_optional.is_initialized() else []
```

This runs a direct SQL query against the attached result file. The query result
is optional.

## Load SQL and Read Annual End Uses

```python
sql = openstudio.SqlFile(openstudio.path(ep_sql_file_path))
gas_gj = sql.naturalGasTotalEndUses().get()
electricity_gj = sql.electricityTotalEndUses().get()
```

This loads an EnergyPlus SQL file and retrieves annual natural gas and
electricity totals in GJ. The reviewed code unwraps the optionals after checking
the SQL path exists. Generated scripts should check optionals when possible.

## Output Summary Reports

```python
reports = model.getOutputTableSummaryReports()
reports.addSummaryReport("AllSummaryAndSizingPeriod")
```

This requests EnergyPlus summary tables in future simulation output.

## MCP Routing Reminder

- Use `model_validate` before simulation when a copied model was edited.
- Use `sim_run` to start the simulation.
- Use `sim_status` until the job reaches `SUCCEEDED` or `FAILED`.
- Use `sim_artifacts` to retrieve output model, SQL, logs, and report artifact
  IDs.
- Use `results_query` and `results_summarize` for result retrieval and user
  summaries.
