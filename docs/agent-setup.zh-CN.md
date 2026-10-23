# 部署后接入智能体

[English](agent-setup.md) · [MCP工具参考](mcp.md)

服务端运行模型；智能体所在机器安装轻量客户端连接服务；skill（技能）指导智能体如何调用。客户端需要 Python3.12+，无需显卡或模型权重。Sonovect v0.1.0 提供标准 MCP（模型上下文协议）服务和可独立安装的技能目录／压缩包，当前没有特定插件市场的一键安装包。

## 1. 安装并连接客户端

在同版本源码目录执行：

```sh
python -m pip install '.[mcp]'
sonovect --version
```

也可以安装提供的 wheel（Python安装包），同时启用 MCP 依赖：

```sh
python -m pip install './sonovect-0.1.0-py3-none-any.whl[mcp]'
```

使用已部署服务的 HTTP（网络接口）地址，并由部署者提供一个**仅含服务令牌**的受保护文件。以下路径均需替换为**客户端机器**上的实际路径。令牌必须与部署配置的 `SONOVECT_TOKEN` 一致；客户端不会自动读取 `deploy/.env`，也不能把整个配置文件当令牌文件。

```sh
export SONOVECT_URL=http://127.0.0.1:8096
export SONOVECT_TOKEN_FILE=/path/to/sonovect.token
export SONOVECT_MCP_INPUT_ROOT=/path/to/audio
sonovect capabilities
```

也可通过智能体宿主的秘密环境变量提供 `SONOVECT_TOKEN`，两种认证方式选一种。服务在其他机器时替换地址；客户端会把本地文件上传给该服务处理。先确认 `sonovect capabilities` 能返回能力，再配置智能体。

## 2. 配置 MCP

使用 `mcpServers` JSON（结构化配置）的客户端，将下面的服务条目合并到已有配置：

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

Codex 使用已有 `config.toml` 中的对应条目，格式见[官方MCP说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)：

```toml
[mcp_servers.sonovect]
command = "sonovect-mcp"
tool_timeout_sec = 300

[mcp_servers.sonovect.env]
SONOVECT_URL = "http://127.0.0.1:8096"
SONOVECT_TOKEN_FILE = "/path/to/sonovect.token"
SONOVECT_MCP_INPUT_ROOT = "/path/to/audio"
```

如果宿主找不到命令，把 `command` 替换为 `command -v sonovect-mcp` 查到的绝对路径；桌面应用不一定继承终端环境。输入根目录由本地 MCP 进程读取，未配置时只能查询、不能上传。智能体与本地桥接进程通过 stdio（标准输入输出）通信，桥接进程再用 HTTP 连接服务端；不能把服务地址直接填成远程 MCP 地址。

## 3. 安装技能

把源码里的整个 `skills/sonovect` 目录复制到智能体支持的技能目录。独立的 `sonovect-0.1.0-skill.zip` 解压后也是同一 `sonovect/` 目录，须保留其中的 `SKILL.md`、`references/usage.md` 和 `agents/openai.yaml`。只安装 Python 包不会自动注册技能。

Codex 首次安装到用户技能目录，可以从源码目录执行：

```sh
mkdir -p "$HOME/.agents/skills"
test ! -e "$HOME/.agents/skills/sonovect" && \
  cp -R skills/sonovect "$HOME/.agents/skills/sonovect"
```

Codex 也支持项目里的 `.agents/skills`，详见[官方技能说明](https://learn.chatgpt.com/docs/build-skills)。选择一个安装位置即可；更新时用同版本技能替换原安装副本，连接和认证仍保留在宿主配置。未发现更新时重新加载智能体。其他兼容 Agent Skills（智能体技能规范）的宿主，使用各自的目录或导入功能。

## 4. 跑通一次调用

对智能体说：

> 使用 $sonovect 转写 /path/to/audio/example.wav。先检查服务能力，提交一次并等待同一个任务，返回文字和字幕。附加分析先关闭。

应能发现六个工具，并依次完成能力查询、提交、同编号轮询和结果读取。之后可按能力增加环境音或音高能量分析。[技能使用流程](../skills/sonovect/references/usage.md)给出具体参数、结果层次和部分成功的处理方式。只有命令行能力的智能体，也可以配置同样的地址和令牌后，按技能中的命令行流程调用。

| 现象 | 检查方法 |
| --- | --- |
| 找不到命令 | 在智能体的Python环境安装客户端，使用可执行文件绝对路径 |
| HTTP 401／认证失败 | 令牌文件仅含匹配的令牌，且MCP进程有读取权限 |
| 未配置输入根目录／文件越界 | 配置包含用户指定文件的客户端实际目录 |
| 附加能力不可用 | 先查询能力；部署启用的功能与单次任务开关分别设置 |
| 仍在处理或客户端超时 | 查询原任务编号，等待无需重新提交 |
| 找不到技能 | 完整安装到一个受支持的位置，再重新加载发现列表 |
