# ADK General Guide (Agent Development Kit)

This guide consolidates **principles**, **best practices**, and **copy/paste code templates**

> TL;DR: Prefer a small **coordinator** that calls **specialists** (tools or sub-agents), pass structured data via **`output_key` + `session.state`**, keep tools **deterministic + JSON-friendly**, and isolate **`google_search`** into its own agent.

---

## SmartSorter-Specific Notes

In this project, LLM prompts are centralized in `ai_folder_sorter/prompts.py`. The prompts module provides:

- `SUMMARIZE_FILE` — file summarization prompt
- `PLAN_GLOBAL` — global planning prompt
- `CRITIQUE_GLOBAL_PLAN` — critic prompt for plan review
- `REPAIR_GLOBAL_PLAN` — repair prompt for fixing rejected plans

Agent wrappers in `ai_folder_sorter/adk_agents.py` use these prompts and include:
- Retry logic with exponential backoff (3 retries)
- Markdown code block stripping for model responses
- Consistent JSON parsing and validation

When modifying prompts:
1. Edit the prompt constants in `prompts.py`
2. Run `python -m compileall ai_folder_sorter` to check syntax
3. Test with `python -m ai_folder_sorter --local-path /path --show-summaries --logging`

---

## 1) Core concepts (mental model)

### Agents
- **`LlmAgent` / `Agent`**: a model-backed agent that reads messages + state, optionally calls tools, and returns a response.
- **Workflow agents** (no model):
  - **`SequentialAgent`**: runs sub-agents in a fixed order.
  - **`ParallelAgent`**: runs sub-agents concurrently.
  - **`LoopAgent`**: repeats a sequence until a stop condition or `max_iterations`.

### Tools
- **Function Tools**: plain Python functions, schema inferred from name + type hints + docstring. Best for deterministic work.
- **Built-in tools**: shipped with ADK (for example `google_search`).
- **`AgentTool`**: wraps another agent (including workflows) as a callable tool so a coordinator can route requests dynamically.

### State (`session.state`) and `output_key`
- Each `LlmAgent` can write its result into `session.state` using **`output_key="some_key"`**.
- Other agents can read those values by referencing **`{some_key}`** in their `instruction`.

In this repo, the common pattern is:
- A worker agent writes `output_key="requirements_summary"`.
- A downstream agent’s instruction includes `"Brief:\n{requirements_summary}"`.

### Conversation history vs state: `include_contents`
- `include_contents="default"` (or omit it): agent sees normal conversation context.
- `include_contents="none"`: agent ignores chat history and relies on `{state_keys}` and its own instruction.

Use `none` for reliability when you want a sub-agent to behave like a pure step in a pipeline.

---

## 2) Project structure (what ADK loads)

A minimal folder-based agent app typically exports:

```python
# agent.py
from google.adk.agents import LlmAgent

root_agent = LlmAgent(
    name="my_agent",
    model="gemini-2.5-flash",
    instruction="...",
)
```

In this repo, each pattern folder contains its own `agent.py` and exposes `root_agent`.

To run the dev UI from the repo root:

```bash
adk web
```

---

## 3) Principles (design rules that scale)

### Principle A — Separate *reasoning* from *execution*
- Let the LLM decide *what to do*.
- Let tools and specialists do *the doing* (math, lookups, formatting, deterministic transforms).

### Principle B — Prefer specialists + coordinator over “god agents”
Instead of attaching 15 tools to one agent, prefer:
- Small specialist agents (math, research, writing)
- One coordinator that routes via `AgentTool`

This is the most reliable way to combine incompatible tool families (notably `google_search` + function tools).

### Principle C — Make data flow explicit
Use `output_key` and `{state_keys}` as contracts between steps. This:
- reduces hallucinations,
- makes debugging easy,
- makes pipelines reproducible.

### Principle D — Treat prompts as APIs
Instructions are a behavior contract. They should state:
- role,
- when/how to use tools,
- response format,
- error behavior,
- explicit “after tools, write a final user response”.

---

## 4) Best practices (with code)

### 4.1 Function Tools: keep them JSON-friendly, deterministic, and structured
**Do**
- Use simple parameter types: `str | int | float | bool | list | dict`.
- Normalize inputs inside the tool.
- Return a consistent object schema.

**Template**

```python
def simple_calculator(a: float, b: float, op: str) -> dict:
    """Compute arithmetic with structured results."""
    op = op.strip().lower()

    if op in ["add", "+"]:
        return {"status": "success", "result": a + b}
    if op in ["sub", "-"]:
        return {"status": "success", "result": a - b}
    if op in ["mul", "*", "x"]:
        return {"status": "success", "result": a * b}
    if op in ["div", "/"]:
        if b == 0:
            return {"status": "error", "message": "Cannot divide by zero."}
        return {"status": "success", "result": a / b}

    return {"status": "error", "message": f"Unknown op: {op}"}
```

**Don’t**
- Raise exceptions for user mistakes.
- Return free-form text (harder for the LLM to parse reliably).
- Add side effects unless the tool is explicitly a side-effecting tool.

### 4.2 Single-agent + tools (baseline pattern)
Matches the style in `01-single-agent-single-function-tool/`.

```python
from google.adk.agents import LlmAgent

math_agent = LlmAgent(
    name="simple_math_agent",
    model="gemini-2.5-flash-lite",
    tools=[simple_calculator],
    instruction=(
        "You are a calculator agent.\n"
        "- For arithmetic, call simple_calculator.\n"
        "- After the tool returns, explain the result in plain language.\n"
        "- If the tool returns status=error, explain the problem and ask for clarification."
    ),
)

root_agent = math_agent
```

### 4.3 Multiple function tools on one agent
Matches `02-single-agent-multi-function-tools/`.

Best practice: keep each tool single-responsibility (calculator vs word count).

```python
multi_tool_agent = LlmAgent(
    name="multi_function_tools_agent",
    model="gemini-2.5-flash-lite",
    tools=[simple_calculator, word_counter],
    instruction=(
        "Use simple_calculator for arithmetic. Use word_counter for word-count questions. "
        "After tool calls, respond with a user-friendly answer (not raw JSON)."
    ),
)
```

### 4.4 Built-in `google_search`: isolate it
Matches `03-single-agent-google-search/`.

```python
from google.adk.agents import LlmAgent
from google.adk.tools import google_search

search_agent = LlmAgent(
    name="google_search_agent",
    model="gemini-2.0-flash",  # Gemini 2.x requirement for google_search
    tools=[google_search],
    instruction=(
        "Use google_search for up-to-date or factual questions. "
        "Summarize in your own words and mention sources/domains when possible."
    ),
)
```

**Important limitation (practical rule):**
- Do not attach `google_search` and function tools to the same `LlmAgent`.
- Instead: put `google_search` in a dedicated agent and call it through `AgentTool`.

### 4.5 Coordinator pattern (routing to specialists)
Matches `04-coordinator-multi-agent/`.

```python
from google.adk.agents import Agent
from google.adk.tools import AgentTool, google_search

math_agent = Agent(..., tools=[simple_calculator])
search_agent = Agent(..., tools=[google_search])

coordinator = Agent(
    name="coordinator_agent",
    model="gemini-2.5-pro",
    tools=[
        AgentTool(agent=math_agent),
        AgentTool(agent=search_agent),
    ],
    instruction=(
        "Route math to math_agent_tool and factual questions to search_agent_tool. "
        "For mixed tasks: search first, then math. Return one final user answer."
    ),
)

root_agent = coordinator
```

**Coordinator best practices**
- Use a stronger model for the coordinator only.
- Keep specialist instructions narrow.
- Make the coordinator responsible for the final response (single voice).

### 4.6 SequentialAgent (fixed pipeline)
Matches `05-sequential-multi-agent/`.

Use when every request must go through the same steps.

```python
from google.adk.agents import LlmAgent, SequentialAgent

step_a = LlmAgent(..., output_key="generated_code")
step_b = LlmAgent(..., include_contents="none", instruction="Review:\n{generated_code}", output_key="review")
step_c = LlmAgent(..., include_contents="none", instruction="Fix using review:\n{review}")

root_agent = SequentialAgent(sub_agents=[step_a, step_b, step_c])
```

### 4.7 ParallelAgent (fan-out) + synthesis (fan-in)
Matches `06-parallel-multi-agent/`.

Rules:
- Each parallel worker writes to a unique `output_key`.
- Follow parallel work with a synthesis agent.

### 4.8 LoopAgent (iterative refinement)
Matches `07-loop-multi-agent/`.

Rules:
- Use **two stop conditions**:
  - semantic: critic emits a completion token/phrase
  - safety: `max_iterations`
- Place the loop at the end of a pipeline if your exit strategy escalates.

A common exit tool pattern uses `ToolContext`:

```python
from google.adk.tools import ToolContext

def exit_loop(tool_context: ToolContext) -> dict:
    tool_context.actions.escalate = True
    return {}
```

---

## 5) Reliability & safety checklist

### Instruction checklist
- Does the instruction say **when** to use each tool?
- Does it explicitly require a **final natural-language response** after tools?
- Does it define behavior for tool errors (for example `{"status": "error"}`)?
- Are response constraints clear (word limit, structure, bullets)?

### State checklist
- Are state keys named clearly (and consistently) like `requirements_summary`?
- Are you avoiding state key collisions, especially with `ParallelAgent`?
- Are downstream prompts reading from `{state_key}` rather than relying on chat history?

### Search safety checklist
- Don’t put PII (names, emails, addresses, account IDs) into search queries.
- Instruct search agents to mention uncertainty when results conflict.

### Cost/perf checklist
- Use a **cheap model** for workers (for example `gemini-2.5-flash` / `-lite`).
- Use a **strong model** for the coordinator only (for example `gemini-2.5-pro`).
- Keep tool outputs and state summaries short; cap loops with `max_iterations`.

---

## 6) Common pitfalls (seen in this repo)

- **Tool call happens but no user-facing answer**: instruction didn’t require a final response after tool calls.
- **Mixing `google_search` with function tools on the same agent**: split into specialist agents and route with `AgentTool`.
- **Parallel state collisions**: two parallel agents wrote to the same `output_key`.
- **Runaway loops**: missing `max_iterations` or critic approves too easily.

---

## 7) Which pattern should I use?

- **One capability + one deterministic tool** → Single agent + function tool (folder `01`).
- **A handful of deterministic tools** → Single agent + multiple function tools (folder `02`).
- **Up-to-date factual answers** → Search-only agent (folder `03`).
- **Mixed capabilities (math + search + synthesis)** → Coordinator + specialists (folder `04`).
- **Always-the-same multi-step workflow** → `SequentialAgent` pipeline (folder `05`).
- **Independent sub-tasks, then merge** → `ParallelAgent` + synthesis (folder `06`).
- **Iterative improvement until good enough** → `LoopAgent` (folder `07`).
- **Real systems** → Combine coordinator + sequential/parallel/loop pipelines (folder `08`).
