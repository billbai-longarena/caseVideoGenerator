# Claude Code 通过 LiteLLM 使用 Azure GPT-5.6 Sol

这份文档用于把本机已经验证过的配置复制到另一台电脑：Claude Code 仍然作为交互式 agent/UI 使用，LiteLLM 在本机起一个 Anthropic-compatible 代理，把请求转到 Azure OpenAI 上的 `gpt-5.6-sol`。

## 架构

```text
Claude Code / claudex
  -> http://127.0.0.1:4000/v1/messages
  -> LiteLLM Docker proxy
  -> Azure OpenAI v1 endpoint
  -> model/deployment: gpt-5.6-sol
```

关键点：

- Claude Code 连接的是本机 LiteLLM，不直接连接 Azure。
- LiteLLM 配置使用 `openai/gpt-5.6-sol`，因为当前 Azure endpoint 是 OpenAI-compatible v1 形式。
- Azure 密钥只放在 shell 环境变量里，不写入 LiteLLM YAML、脚本或本文档。
- 本机代理只绑定 `127.0.0.1`，不要暴露到局域网或公网。

## 前置条件

目标机器需要：

- macOS + zsh。
- Docker Desktop 已安装并运行。
- Claude Code CLI 已安装，命令名为 `claude`。
- `rg` 命令可用；脚本用它判断 Docker 容器名。没有的话先执行 `brew install ripgrep`。
- Azure OpenAI 已有可用的 `gpt-5.6-sol` model/deployment。
- Azure OpenAI endpoint 是 v1/OpenAI-compatible 形式，通常类似：

```text
https://<your-resource>.cognitiveservices.azure.com/openai/v1
```

先检查：

```zsh
command -v docker
docker info
command -v claude
claude --version
command -v rg || brew install ripgrep
```

如果 `docker info` 失败，先启动 Docker Desktop：

```zsh
open -a Docker
```

## 1. 设置 Azure 环境变量

把下面两行写入 `~/.zshrc`，替换成目标机器自己的 Azure 信息：

```zsh
export AZURE_OPENAI_ENDPOINT="https://<your-resource>.cognitiveservices.azure.com/openai/v1"
export AZURE_OPENAI_API_KEY="<your-azure-openai-api-key>"
```

加载配置：

```zsh
source ~/.zshrc
```

不要把真实 key 写进 Git 仓库、Markdown、LiteLLM YAML 或脚本。

## 2. 准备目录和 Docker 镜像

```zsh
mkdir -p ~/.litellm ~/.local/bin
docker pull docker.litellm.ai/berriai/litellm:latest
```

如果镜像拉取慢，可以先继续后面的文件创建；启动脚本在镜像不存在时也会自动 `docker pull`。

## 3. 创建 LiteLLM 配置

创建 `~/.litellm/claude-azure-gpt56sol.yaml`：

```yaml
model_list:
  - model_name: gpt-5.6-sol
    litellm_params:
      model: openai/gpt-5.6-sol
      api_base: os.environ/AZURE_OPENAI_ENDPOINT
      api_key: os.environ/AZURE_OPENAI_API_KEY
    model_info:
      base_model: openai/gpt-5.6-sol

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

注意：这里不是 `azure/gpt-5.6-sol`。本机验证通过的是 Azure OpenAI v1 endpoint + `openai/gpt-5.6-sol` 这条路线。

## 4. 创建 LiteLLM 启动脚本

创建 `~/.local/bin/litellm-azure-gpt56sol-start`：

```zsh
#!/usr/bin/env zsh
set -euo pipefail

CONFIG="${LITELLM_CONFIG:-$HOME/.litellm/claude-azure-gpt56sol.yaml}"
ENV_FILE="${LITELLM_ENV_FILE:-$HOME/.litellm/claude-azure-gpt56sol.env}"
PORT="${LITELLM_PORT:-4000}"
CONTAINER="${LITELLM_CONTAINER_NAME:-litellm-claude-azure-gpt56sol}"
IMAGE="${LITELLM_DOCKER_IMAGE:-docker.litellm.ai/berriai/litellm:latest}"

if [[ -f "$HOME/.zshrc" ]]; then
  set +u
  source "$HOME/.zshrc" >/dev/null 2>&1 || true
  set -u
fi

if [[ -f "$ENV_FILE" ]]; then
  set +u
  source "$ENV_FILE"
  set -u
fi

if [[ -z "${LITELLM_MASTER_KEY:-}" ]]; then
  mkdir -p "$(dirname "$ENV_FILE")"
  umask 077
  LITELLM_MASTER_KEY="sk-local-$(openssl rand -hex 24)"
  printf 'LITELLM_MASTER_KEY=%s\n' "$LITELLM_MASTER_KEY" > "$ENV_FILE"
fi

export LITELLM_MASTER_KEY

if [[ -z "${AZURE_OPENAI_API_KEY:-}" ]]; then
  print -u2 "Missing AZURE_OPENAI_API_KEY. Put it in your shell env or ~/.zshrc."
  exit 2
fi

if [[ -z "${AZURE_OPENAI_ENDPOINT:-}" ]]; then
  print -u2 "Missing AZURE_OPENAI_ENDPOINT. Put it in your shell env or ~/.zshrc."
  exit 2
fi

if [[ ! -f "$CONFIG" ]]; then
  print -u2 "Missing LiteLLM config: $CONFIG"
  exit 2
fi

if ! docker info >/dev/null 2>&1; then
  print -u2 "Docker is not running. Start Docker Desktop, then rerun this command."
  exit 2
fi

if docker ps --format '{{.Names}}' | rg -qx "$CONTAINER"; then
  print "LiteLLM is already running at http://127.0.0.1:$PORT"
  exit 0
fi

if docker ps -a --format '{{.Names}}' | rg -qx "$CONTAINER"; then
  docker rm -f "$CONTAINER" >/dev/null
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker pull "$IMAGE"
fi

docker run -d \
  --name "$CONTAINER" \
  -p "127.0.0.1:${PORT}:4000" \
  -v "$CONFIG:/app/config.yaml:ro" \
  -e AZURE_OPENAI_API_KEY \
  -e AZURE_OPENAI_ENDPOINT \
  -e LITELLM_MASTER_KEY \
  "$IMAGE" \
  --config /app/config.yaml \
  --host 0.0.0.0 \
  --port 4000 >/dev/null

for _ in {1..60}; do
  if curl -fsS "http://127.0.0.1:${PORT}/health/liveliness" >/dev/null 2>&1; then
    print "LiteLLM is running at http://127.0.0.1:$PORT"
    exit 0
  fi

  if ! docker ps --format '{{.Names}}' | rg -qx "$CONTAINER"; then
    docker logs --tail 80 "$CONTAINER" 2>&1
    exit 1
  fi

  sleep 1
done

print -u2 "LiteLLM did not become healthy in time. Recent logs:"
docker logs --tail 80 "$CONTAINER" 2>&1
exit 1
```

## 5. 创建 LiteLLM 停止脚本

创建 `~/.local/bin/litellm-azure-gpt56sol-stop`：

```zsh
#!/usr/bin/env zsh
set -euo pipefail

CONTAINER="${LITELLM_CONTAINER_NAME:-litellm-claude-azure-gpt56sol}"

if ! docker info >/dev/null 2>&1; then
  print -u2 "Docker is not running."
  exit 2
fi

if docker ps -a --format '{{.Names}}' | rg -qx "$CONTAINER"; then
  docker rm -f "$CONTAINER" >/dev/null
  print "Stopped $CONTAINER"
else
  print "$CONTAINER is not running"
fi
```

## 6. 创建 Claude Code 包装命令 claudex

创建 `~/.local/bin/claudex`：

```zsh
#!/usr/bin/env zsh
set -euo pipefail

ENV_FILE="${LITELLM_ENV_FILE:-$HOME/.litellm/claude-azure-gpt56sol.env}"
PORT="${LITELLM_PORT:-4000}"
MODEL="${CLAUDEX_MODEL:-gpt-5.6-sol}"

if [[ -f "$HOME/.zshrc" ]]; then
  set +u
  source "$HOME/.zshrc" >/dev/null 2>&1 || true
  set -u
fi

if [[ -f "$ENV_FILE" ]]; then
  set +u
  source "$ENV_FILE"
  set -u
fi

if [[ -z "${LITELLM_MASTER_KEY:-}" ]]; then
  mkdir -p "$(dirname "$ENV_FILE")"
  umask 077
  LITELLM_MASTER_KEY="sk-local-$(openssl rand -hex 24)"
  printf 'LITELLM_MASTER_KEY=%s\n' "$LITELLM_MASTER_KEY" > "$ENV_FILE"
fi

export LITELLM_MASTER_KEY
export LITELLM_PORT="$PORT"

if ! curl -fsS "http://127.0.0.1:${PORT}/health/liveliness" >/dev/null 2>&1; then
  "$HOME/.local/bin/litellm-azure-gpt56sol-start"
fi

for _ in {1..60}; do
  if curl -fsS "http://127.0.0.1:${PORT}/health/liveliness" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS "http://127.0.0.1:${PORT}/health/liveliness" >/dev/null 2>&1; then
  print -u2 "LiteLLM is not healthy at http://127.0.0.1:$PORT"
  exit 1
fi

export ANTHROPIC_BASE_URL="http://127.0.0.1:${PORT}"
unset ANTHROPIC_API_KEY
export ANTHROPIC_AUTH_TOKEN="$LITELLM_MASTER_KEY"
export CLAUDE_CODE_SUBAGENT_MODEL="$MODEL"
export CLAUDE_CODE_ALWAYS_ENABLE_EFFORT="${CLAUDE_CODE_ALWAYS_ENABLE_EFFORT:-1}"
export CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY="${CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY:-3}"
export ENABLE_TOOL_SEARCH="${ENABLE_TOOL_SEARCH:-false}"

unset CLAUDE_CODE_USE_FOUNDRY
unset ANTHROPIC_FOUNDRY_API_KEY
unset ANTHROPIC_FOUNDRY_RESOURCE

exec claude --model "$MODEL" "$@"
```

这个包装命令会：

- 自动启动本机 LiteLLM。
- 让 Claude Code 使用 `http://127.0.0.1:4000`。
- 设置主模型和子 agent 模型为 `gpt-5.6-sol`。
- `unset ANTHROPIC_API_KEY`，避免 Claude Code 同时看到 `ANTHROPIC_AUTH_TOKEN` 和 `ANTHROPIC_API_KEY` 后出现黄色警告。

## 7. 赋权并确认 PATH

```zsh
chmod 755 ~/.local/bin/litellm-azure-gpt56sol-start
chmod 755 ~/.local/bin/litellm-azure-gpt56sol-stop
chmod 755 ~/.local/bin/claudex
```

确认 `~/.local/bin` 在 PATH 里：

```zsh
echo "$PATH" | tr ':' '\n' | rg -x "$HOME/.local/bin"
```

如果没有，把这一行加入 `~/.zshrc`：

```zsh
export PATH="$HOME/.local/bin:$PATH"
```

然后：

```zsh
source ~/.zshrc
```

## 8. 启动和验证

启动 LiteLLM：

```zsh
litellm-azure-gpt56sol-start
```

健康检查：

```zsh
curl -fsS http://127.0.0.1:4000/health/liveliness
```

预期包含：

```text
I'm alive!
```

检查模型列表：

```zsh
source ~/.litellm/claude-azure-gpt56sol.env
curl -fsS \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  http://127.0.0.1:4000/v1/models
```

预期能看到 `gpt-5.6-sol`。

检查 Anthropic-compatible `/v1/messages`：

```zsh
curl -sS -w '\nHTTP_STATUS:%{http_code}\n' \
  -H "x-api-key: ${LITELLM_MASTER_KEY}" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  http://127.0.0.1:4000/v1/messages \
  -d '{"model":"gpt-5.6-sol","max_tokens":16,"messages":[{"role":"user","content":"Reply with OK only."}]}'
```

预期：

- 返回内容包含 `OK`。
- `HTTP_STATUS:200`。

最后检查 Claude Code：

```zsh
claudex --print 'Reply OK only.'
```

预期返回：

```text
OK
```

## 日常使用

进入交互式 Claude Code：

```zsh
claudex
```

继续上一次会话：

```zsh
claudex --continue
```

一次性提问：

```zsh
claudex --print 'Reply OK only.'
```

停止 LiteLLM：

```zsh
litellm-azure-gpt56sol-stop
```

## 常见问题

### Claude Code 提示同时设置了 ANTHROPIC_AUTH_TOKEN 和 ANTHROPIC_API_KEY

这通常不是 Azure 或 LiteLLM 故障，而是 shell 里已有 `ANTHROPIC_API_KEY`。本方案的 `claudex` 已经在启动 Claude Code 前执行：

```zsh
unset ANTHROPIC_API_KEY
export ANTHROPIC_AUTH_TOKEN="$LITELLM_MASTER_KEY"
```

如果仍然有警告，开一个新终端再试，或检查是否有别名/脚本绕过了 `~/.local/bin/claudex`。

### Azure 返回 404 或 Resource not found

优先检查三件事：

```zsh
echo "$AZURE_OPENAI_ENDPOINT"
rg -n "model:|api_base|api_key" ~/.litellm/claude-azure-gpt56sol.yaml
curl -fsS http://127.0.0.1:4000/v1/models \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}"
```

本方案要求 endpoint 末尾是 `/openai/v1`，LiteLLM YAML 里是：

```yaml
model: openai/gpt-5.6-sol
api_base: os.environ/AZURE_OPENAI_ENDPOINT
```

如果你的 Azure endpoint 是旧式 `api-version` 路线，这份配置需要改，不能直接照抄。

### 手动测试报 max_output_tokens 太小

`gpt-5.6-sol` 的手动测试里不要把 `max_tokens` 设得太小。本机验证用的是：

```json
"max_tokens": 16
```

### 4000 端口被占用

换端口：

```zsh
export LITELLM_PORT=4001
litellm-azure-gpt56sol-start
claudex --print 'Reply OK only.'
```

`claudex` 会读取同一个 `LITELLM_PORT`。

### Docker 没启动

```zsh
open -a Docker
docker info
litellm-azure-gpt56sol-start
```

### 看 LiteLLM 日志

```zsh
docker logs --tail 120 litellm-claude-azure-gpt56sol
```

### 完全重启代理

```zsh
litellm-azure-gpt56sol-stop
litellm-azure-gpt56sol-start
```

## 安全检查清单

配置完成后确认：

- `~/.litellm/claude-azure-gpt56sol.yaml` 只引用 `os.environ/...`，没有真实 Azure key。
- `~/.local/bin/claudex` 里有 `unset ANTHROPIC_API_KEY`。
- `~/.litellm/claude-azure-gpt56sol.env` 权限不是公开可读。
- Docker 映射端口是 `127.0.0.1:${PORT}:4000`，不是 `0.0.0.0:${PORT}:4000`。
- 不把 `AZURE_OPENAI_API_KEY`、`LITELLM_MASTER_KEY`、`.env` 文件提交到 Git。

可以检查：

```zsh
ls -l ~/.litellm/claude-azure-gpt56sol.env
rg -n "AZURE_OPENAI_API_KEY|LITELLM_MASTER_KEY|ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN" \
  ~/.litellm/claude-azure-gpt56sol.yaml \
  ~/.local/bin/litellm-azure-gpt56sol-start \
  ~/.local/bin/claudex
```

预期：只看到变量名，不应该看到真实 key 值。

## Agent 执行验收

另一个 agent 按本文档配置完后，至少要完成这些验收：

```zsh
zsh -n ~/.local/bin/litellm-azure-gpt56sol-start
zsh -n ~/.local/bin/litellm-azure-gpt56sol-stop
zsh -n ~/.local/bin/claudex
litellm-azure-gpt56sol-start
curl -fsS http://127.0.0.1:4000/health/liveliness
source ~/.litellm/claude-azure-gpt56sol.env
curl -fsS -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" http://127.0.0.1:4000/v1/models
claudex --print 'Reply OK only.'
```

交付标准：

- 三个脚本语法检查通过。
- LiteLLM health check 通过。
- `/v1/models` 能看到 `gpt-5.6-sol`。
- `claudex --print 'Reply OK only.'` 返回 `OK`。
- Claude Code 启动时不再出现 `Both ANTHROPIC_AUTH_TOKEN and ANTHROPIC_API_KEY set` 警告。
