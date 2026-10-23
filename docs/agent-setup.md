# Connect an agent to Sonovect

[中文](agent-setup.zh-CN.md) · [MCP tool reference](mcp.md)

The service runs the models. A small client on the agent's machine connects to that service; the optional skill teaches the agent how to use it. The client needs Python 3.12+, not a GPU or model weights. Sonovect v0.1.0 ships a standard stdio MCP server and a portable skill directory/ZIP, not a marketplace-specific plugin installer.

## 1. Install and connect the client

From the matching source directory:

```sh
python -m pip install '.[mcp]'
sonovect --version
```

Alternatively, install the supplied wheel with its MCP extra:

```sh
python -m pip install './sonovect-0.1.0-py3-none-any.whl[mcp]'
```

Use the URL of your deployed HTTP API and a protected file containing only its token. All paths below are examples to replace on the **client machine**. The token must match the deployment's `SONOVECT_TOKEN`; the client does not automatically read `deploy/.env`, and an entire environment file is not a token file.

```sh
export SONOVECT_URL=http://127.0.0.1:8096
export SONOVECT_TOKEN_FILE=/path/to/sonovect.token
export SONOVECT_MCP_INPUT_ROOT=/path/to/audio
sonovect capabilities
```

`SONOVECT_TOKEN` is an alternative when supplied by the agent host's secret environment. Choose one authentication method. For a service on another machine, change the URL; the client uploads its local media to that service. Run `sonovect capabilities` successfully before configuring the agent.

## 2. Register the MCP server

In a client that uses `mcpServers` JSON, add this entry to its existing configuration:

```json
{
  "mcpServers": {
    "sonovect": {
      "command": "sonovect-mcp",
      "env": {
        "SONOVECT_URL": "http://127.0.0.1:8096",
        "SONOVECT_TOKEN_FILE": "/path/to/sonovect.token",
        "SONOVECT_MCP_INPUT_ROOT": "/path/to/audio"
      }
    }
  }
}
```

For Codex, use the equivalent entry in its existing `config.toml`, following the [official MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli):

```toml
[mcp_servers.sonovect]
command = "sonovect-mcp"
tool_timeout_sec = 300

[mcp_servers.sonovect.env]
SONOVECT_URL = "http://127.0.0.1:8096"
SONOVECT_TOKEN_FILE = "/path/to/sonovect.token"
SONOVECT_MCP_INPUT_ROOT = "/path/to/audio"
```

If the host cannot find the executable, set `command` to the absolute path returned by `command -v sonovect-mcp`. Desktop applications may not inherit your shell environment. The input root belongs to the MCP process; without it, read tools work but uploads are disabled. Sonovect uses stdio between the agent and this local bridge, and HTTP between the bridge and the deployed service. An HTTP-only MCP client cannot use the service URL as an MCP endpoint.

## 3. Install the skill

Copy the complete `skills/sonovect` directory into your agent's supported skill directory. The independent `sonovect-0.1.0-skill.zip` contains the same top-level `sonovect/` directory. Keep `SKILL.md`, `references/usage.md` and `agents/openai.yaml` together. Installing the wheel alone does not register a skill.

For a first user-level Codex installation, from the source directory:

```sh
mkdir -p "$HOME/.agents/skills"
test ! -e "$HOME/.agents/skills/sonovect" && \
  cp -R skills/sonovect "$HOME/.agents/skills/sonovect"
```

Codex also supports project-level `.agents/skills`, as described in its [official skill documentation](https://learn.chatgpt.com/docs/build-skills). Choose one installation location. When updating, replace that installed skill with the matching release instead of adding another copy; keep endpoint/token configuration in the host. Reload the agent if it does not discover the update. Other Agent Skills-compatible hosts use their own skill directory/import action.

## 4. Try one complete workflow

Ask the agent:

> Use $sonovect to transcribe /path/to/audio/example.wav. First check the available capabilities, submit once, wait for the same job, and return the text and subtitles. Leave optional analysis off.

The agent should discover six tools, call `sonovect_capabilities`, submit, poll the returned ID and read the result. A second request can add environmental sounds or pitch/energy if discovery advertises them. [The skill workflow](../skills/sonovect/references/usage.md) contains exact arguments, output layers and partial-result handling. With a CLI-only agent, configure the same URL/token and use the skill's command-line flow.

| Symptom | Check |
| --- | --- |
| Executable not found | Install in the agent's Python environment; use its absolute executable path |
| Unauthorized / HTTP 401 | Token file contains only the matching token and is readable by the MCP process |
| Upload root missing or file outside root | Configure a real client-side directory containing the user-selected file |
| Optional feature unavailable | Select an enabled feature from capabilities; deployment choices and job switches are separate |
| Job still running or client timed out | Query the original ID; do not submit it again |
| Skill missing | Install the entire directory in one supported location and reload discovery |
