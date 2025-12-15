from google.adk.agents import LlmAgent

# Minimal ADK entrypoint (optional; CLI is primary).
root_agent = LlmAgent(
    name="smart_sorter_root_agent",
    model="gemini-2.5-flash",
    instruction=(
        "This repository's primary interface is the CLI (`python -m ai_folder_sorter`). "
        "Use the CLI for end-to-end runs."
    ),
)

