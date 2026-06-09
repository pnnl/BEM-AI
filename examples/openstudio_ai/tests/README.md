# OpenStudio Agent Evaluation Cases

`agent_eval_cases.json` contains conversation-style test cases for evaluating
the OpenStudio AI Model Workspace Agent.

The cases are intentionally simple and focused on realistic building energy
modeling questions. They are designed to evaluate:

- professionalism of the response;
- whether clarification is requested when inputs are missing;
- plan quality before tool execution;
- correct tool and skill routing;
- task completion;
- step efficiency and avoidance of unnecessary tools.

The file is data only. A future harness can read each case, send `query` to the
agent, and grade the response against `expected_output`, `expected_behavior`,
and `pass_criteria`.
