<h1 align="center">ChatGPT2API</h1>

<p align="center">ChatGPT2API mainly reverse-engineers and wraps capabilities of the official ChatGPT website, providing an OpenAI-compatible image API / proxy for ChatGPT image generation, image editing, and multi-image composite editing. It integrates an online drawing workbench, account pool management, multiple account import methods, and Docker self-hosting.</p>

> [!WARNING]
> Disclaimer:
>
> This project involves reverse-engineering research of the official ChatGPT website's text-generation, image-generation, and image-editing APIs, and is intended only for personal study, technical research, and non-commercial technical exchange.
>
> - Using this project for any commercial purpose, profit-making use, bulk operations, automated abuse, or large-scale calls is strictly prohibited.
> - Using this project to disrupt market order, engage in unfair competition, arbitrage and resale, secondary resale of related services, or any behavior that violates OpenAI's terms of service or local laws and regulations is strictly prohibited.
> - Using this project to generate, distribute, or assist in generating illegal, violent, pornographic, or minor-related content, or for fraud, deception, harassment, or other illegal or improper purposes is strictly prohibited.
> - Users bear all risks themselves, including but not limited to account restrictions, temporary or permanent bans, and legal liability arising from non-compliant use.
> - Using this project means you fully understand and agree to all of this disclaimer; any consequences caused by abuse, violations, or illegal use are borne by the user.
> - This project is implemented based on reverse-engineering research of the official ChatGPT website, and carries the risk of account restrictions, temporary bans, or permanent bans. Do not use your important, frequently used, or high-value accounts for testing.

## Quick start

Published images support `linux/amd64` and `linux/arm64`, automatically pulling the matching architecture on x86 servers and Apple Silicon / ARM Linux devices.

### Run with Docker

```bash
git clone git@github.com:basketikun/chatgpt2api.git
cd chatgpt2api
docker compose up -d
```

Before starting, set `auth-key` in `config.json`, or override it via `CHATGPT2API_AUTH_KEY` in `docker-compose.yml`.

- Web panel: `http://localhost:3000`
- API address: `http://localhost:3000/v1`
- Data directory: `./data`

### Local development

Start the backend:

```bash
git clone git@github.com:basketikun/chatgpt2api.git
cd chatgpt2api
uv sync
uv run main.py
```

Start the frontend:

```bash
cd chatgpt2api/web
bun install
bun run dev
```

Updating to a new version later:

```bash
docker pull ghcr.io/basketikun/chatgpt2api:latest
docker-compose down
docker-compose up -d

```

### Storage backend configuration

You can switch the storage method via the `STORAGE_BACKEND` environment variable:

- `json` - local JSON file (default)
- `sqlite` - local SQLite database
- `postgres` - external PostgreSQL (requires `DATABASE_URL`)
- `git` - private Git repository (requires `GIT_REPO_URL` and `GIT_TOKEN`)

Example: using PostgreSQL

```yaml
environment:
  - STORAGE_BACKEND=postgres
  - DATABASE_URL=postgresql://user:password@host:5432/dbname
```

## Features

### API compatibility

- Compatible `POST /v1/images/generations` image-generation endpoint
- Compatible `POST /v1/images/edits` image-editing endpoint
- Compatible `POST /v1/chat/completions` for image scenarios
- Compatible `POST /v1/completions` legacy text-completion endpoint
- Compatible `POST /v1/responses` for text responses, image-generation tool calls, JSON mode hints, and lightweight function-call output parsing
- `GET /v1/models` returns `gpt-image-2`, `codex-gpt-image-2`, `auto`, `gpt-5`, `gpt-5-1`, `gpt-5-2`, `gpt-5-3`, `gpt-5-3-mini`,
  `gpt-5-mini`
- Supports returning multiple results via `n`
- Supports generating editable PPT files
- Supports generating editable PSD files
- Supports reverse-engineered Codex image generation, available only for `Plus` / `Team` / `Pro` subscriptions, with the model alias `codex-gpt-image-2`. You can map it back to
  `gpt-image-2` in other scenarios if needed; it is used to distinguish it from the official web drawing, which means the same account has separate image quotas for the web and for Codex.

### Online drawing

- Built-in online drawing workbench supporting generation, image editing, and multi-image composite editing
- Supports model selection among `gpt-image-2`, `codex-gpt-image-2`, `auto`, `gpt-5`, `gpt-5-1`, `gpt-5-2`, `gpt-5-3`, `gpt-5-3-mini`, `gpt-5-mini`
- Edit mode supports reference-image upload
- The frontend supports multi-image generation interactions
- Image conversation history is saved locally, with review, deletion, and clearing
- Supports server-side caching of image URLs
- Image generation progress tracking, with the ability to keep waiting after a timeout
- Image lazy loading and scroll-position memory, optimizing performance with many images

### Account pool management

- Automatically refreshes account email, type, quota, and recovery time (with async progress tracking)
- Round-robins available accounts for image generation and editing
- Automatically removes invalid tokens when token-invalidation errors occur
- Periodically checks rate-limited accounts and refreshes them automatically
- Supports password re-login to recover abnormal accounts, with automatic re-login after refresh
- Supports configuring a global HTTP / HTTPS / SOCKS5 / SOCKS5H proxy from the web UI
- Supports searching, filtering, bulk refresh, export, manual editing, and account cleanup
- Supports four import methods: local CPA JSON file import, remote CPA server import, `sub2api` server import, and `access_token` import
- Supports configuring a `sub2api` server in settings, then filtering and bulk-importing its OpenAI OAuth accounts

### Experimental / planned

- `/v1/complete` text completion and streaming output are implemented but still being tested; currently there is a conversation-repetition issue, so test with caution
- The `/v1/chat/completions` and `/v1/responses` text paths support short-TTL caching, duplicate-request merging, adjacent duplicate-message cleanup, JSON mode hints, developer/tool role normalization, and lightweight tool-call JSON parsing, adjustable via `chat_completion_cache`
- For detailed status, see: [Feature list](./docs/feature-status.en.md)

## Showcase

<table width="100%">
  <tr>
    <td width="50%"><img src="https://i.ibb.co/Jj8nfwwP/image.png" alt="image" border="0"></td>
    <td width="50%"><img src="https://i.ibb.co/pqf235v/image-edit.png" alt="image edit" border="0"></td>
  </tr>
  <tr>
    <td width="50%"><img src="https://i.ibb.co/tPcqtVfd/chery-studio.png" alt="chery studio" border="0"></td>
    <td width="50%"><img src="https://i.ibb.co/PsT9YHBV/account-pool.png" alt="account pool" border="0"></td>
  </tr>
  <tr>
    <td width="50%"><img src="https://i.ibb.co/rRWLG08q/new-api.png" alt="new api" border="0"></td>
  </tr>
</table>

## API

All AI endpoints require the header:

```http
Authorization: Bearer <auth-key>
```

<details>
<summary><code>GET /v1/models</code></summary>
<br>

Returns the list of currently exposed image models.

```bash
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer <auth-key>"
```

<details>
<summary>Notes</summary>
<br>

| Field            | Description                                                                                                 |
|:-----------------|:------------------------------------------------------------------------------------------------------------|
| Returned models  | `gpt-image-2`, `codex-gpt-image-2`, `auto`, `gpt-5`, `gpt-5-1`, `gpt-5-2`, `gpt-5-3`, `gpt-5-3-mini`, `gpt-5-mini` |
| Integration      | Can be integrated with upstreams or clients such as Cherry Studio and New API                               |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/images/generations</code></summary>
<br>

OpenAI-compatible image-generation endpoint for text-to-image.

```bash
curl http://localhost:8000/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "A cat floating in space",
    "n": 1,
    "response_format": "b64_json"
  }'
```

<details>
<summary>Field descriptions</summary>
<br>

| Field             | Description                                                          |
|:------------------|:--------------------------------------------------------------------|
| `model`           | Image model; current valid values follow `/v1/models`, `gpt-image-2` recommended |
| `prompt`          | Image-generation prompt                                             |
| `n`               | Number of images; currently limited to `1-4` by the backend         |
| `response_format` | Included in the request model; defaults to `b64_json`               |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/images/edits</code></summary>
<br>

OpenAI-compatible image-editing endpoint; you can upload an image file, or pass image URLs in the official JSON format to generate an edited result.

```bash
curl http://localhost:8000/v1/images/edits \
  -H "Authorization: Bearer <auth-key>" \
  -F "model=gpt-image-2" \
  -F "prompt=Change this image to a cyberpunk night-scene style" \
  -F "n=1" \
  -F "image=@./input.png"
```

You can also pass an image URL directly:

```bash
curl http://localhost:8000/v1/images/edits \
  -H "Authorization: Bearer <auth-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "Change this image to a cyberpunk night-scene style",
    "images": [
      {"image_url": "https://example.com/input.png"}
    ]
  }'
```

<details>
<summary>Field descriptions</summary>
<br>

| Field       | Description                                            |
|:------------|:------------------------------------------------------|
| `model`     | Image model, `gpt-image-2`                            |
| `prompt`    | Image-editing prompt                                  |
| `n`         | Number of images; currently limited to `1-4`          |
| `image`     | The image file to edit, uploaded via multipart/form-data |
| `images`    | JSON image-reference array, supports `{"image_url": "https://..."}` |
| `image_url` | In form mode you can also pass image URLs directly, repeating the field for multiple images |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/chat/completions</code></summary>
<br>

A Chat Completions-compatible endpoint for image scenarios, not a full general-purpose chat proxy.

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-image-2",
    "messages": [
      {
        "role": "user",
        "content": "Generate a cyberpunk cat on a Tokyo street on a rainy night"
      }
    ],
    "n": 1
  }'
```

<details>
<summary>Field descriptions</summary>
<br>

| Field      | Description                                          |
|:-----------|:----------------------------------------------------|
| `model`    | Image model; defaults to image-generation handling  |
| `messages` | Message array; must be image-related request content |
| `n`        | Number of images; parsed as the image count by the current implementation |
| `stream`   | Implemented, but still being tested                 |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/completions</code></summary>
<br>

Legacy text-completions compatibility endpoint. The server maps `prompt` to a single user chat message and returns an OpenAI-style text completion response.

```bash
curl http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "auto",
    "prompt": "Briefly explain Docker Compose"
  }'
```

<br>
</details>

<details>
<summary><code>POST /v1/responses</code></summary>
<br>

A Responses API-compatible endpoint for text responses, image-generation tool calls, JSON-mode hints, and lightweight function-call output parsing.

```bash
curl http://localhost:8000/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-5",
    "input": "Generate a futuristic city skyline image",
    "tools": [
      {
        "type": "image_generation"
      }
    ]
  }'
```

<details>
<summary>Field descriptions</summary>
<br>

| Field    | Description                                          |
|:---------|:----------------------------------------------------|
| `model`  | The model field is echoed in the response, but image generation still uses the image-generation compatibility logic |
| `input`  | Input content; text messages, response content parts, and function-call output items are accepted |
| `tools`  | Use `image_generation` for image output, or function tools for lightweight tool-call parsing |
| `stream` | Implemented, but still being tested                 |

<br>
</details>
</details>

## Community

Learn AI on the L community: [LinuxDO](https://linux.do)
