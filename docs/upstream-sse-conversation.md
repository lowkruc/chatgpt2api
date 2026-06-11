# Upstream Conversation SSE protocol

Conversation SSE is the streaming response protocol of the upstream conversation path. Each SSE `data:` is usually a JSON payload, but may also be a protocol marker or an end marker. The client must consume these payloads in order, maintaining the current conversation state, text content, tool-call state, and image-result pointers.

## Basic shapes

Common payload examples:

```text
"v1"
{"type":"resume_conversation_token",...}
{"p":"","o":"add","v":{...}}
{"v":{...}}
{"p":"/message/content/parts/0","o":"append","v":"..."}
{"type":"server_ste_metadata","metadata":{...}}
[DONE]
```

Handling recommendations:

| payload | Meaning | How to handle |
|:--|:--|:--|
| `"v1"` | Protocol version marker | Can be logged; usually has no business impact |
| `[DONE]` | The current SSE stream has ended | Stop reading |
| JSON object | An event, message, or patch | Update the conversation state by field |
| JSON string | A short text patch or protocol marker | Handle in context |
| Non-JSON content | Raw content | Keep it as a raw event to avoid breaking the stream |

## Common fields

| Field | Description |
|:--|:--|
| `type` | Upstream event type, e.g. `resume_conversation_token`, `input_message`, `message_marker`, `title_generation`, `server_ste_metadata` |
| `conversation_id` | The current conversation ID, available from several events |
| `p` | Patch path, e.g. `/message/content/parts/0` |
| `o` | Patch operation, e.g. `add`, `append`, `replace`, `patch` |
| `v` | Patch value; may be a string, an array, or contain a full message |
| `c` | Message index or cursor, common in `add`-type events |
| `message.id` | Message ID |
| `message.author.role` | Message role, commonly `system`, `user`, `assistant`, `tool` |
| `message.content.content_type` | Content type, e.g. `text`, `multimodal_text`, `model_editable_context` |
| `message.content.parts` | Content parts; may contain text, image pointers, or multimodal objects |
| `message.status` | Message status, e.g. `in_progress`, `finished_successfully` |
| `message.end_turn` | Whether the current turn ends |
| `metadata.tool_invoked` | Whether a tool was invoked this turn |
| `metadata.turn_use_case` | The turn's use case, e.g. `text`, `multimodal` |
| `metadata.async_task_type` | The async tool task type; image generation is usually `image_gen` |

## Conversation-start events

The upstream usually returns a resume token or conversation token first:

```json
{
  "type": "resume_conversation_token",
  "kind": "topic",
  "token": "...",
  "conversation_id": "..."
}
```

This event mainly identifies the conversation and restores context. The business layer usually only needs to store the `conversation_id`; the `token` should not be exposed to downstream users.

## Message add case

A full message may appear via `add` or an event carrying `v.message`:

```json
{
  "p": "",
  "o": "add",
  "v": {
    "message": {
      "author": {"role": "assistant"},
      "content": {"content_type": "text", "parts": [""]},
      "status": "in_progress"
    },
    "conversation_id": "..."
  },
  "c": 3
}
```

Such events typically create a new message. If the message role is `assistant`, subsequent text is usually appended via patches.

## Text increment case

Text output usually consists of multiple patches:

```json
{"p":"/message/content/parts/0","o":"append","v":"Hello"}
{"v":" world"}
{"p":"","o":"patch","v":[
  {"p":"/message/content/parts/0","o":"append","v":"!"},
  {"p":"/message/status","o":"replace","v":"finished_successfully"},
  {"p":"/message/end_turn","o":"replace","v":true}
]}
```

Key points:

| Shape | Meaning |
|:--|:--|
| `p == "/message/content/parts/0"` and `o == "append"` | Append content to the current text |
| `o == "replace"` | Replace the target field with the new value |
| `o == "patch"` and `v` is an array | A batch patch; process the array in order |
| Only `v` and `v` is a string | Likely a text increment with the path omitted; handle it against the current text stream |

## Input message case

User input appears as `input_message` or a regular `user` message. An image-edit request includes the reference image uploaded by the user:

```json
{
  "type": "input_message",
  "input_message": {
    "author": {"role": "user"},
    "content": {
      "content_type": "multimodal_text",
      "parts": [
        {"asset_pointer": "sediment://file_input"},
        "edit prompt"
      ]
    }
  },
  "conversation_id": "..."
}
```

A `sediment://...` like this represents an input attachment, not a generated result. Even if it can be downloaded, it must not be returned as an output image.

## Image tool success case

When image generation or editing succeeds, the upstream generally produces a tool message:

```json
{
  "v": {
    "message": {
      "author": {"role": "tool"},
      "content": {
        "content_type": "multimodal_text",
        "parts": [
          {"asset_pointer": "file-service://file_result"},
          {"asset_pointer": "sediment://file_result"}
        ]
      },
      "metadata": {"async_task_type": "image_gen"}
    }
  },
  "conversation_id": "..."
}
```

Only image pointers that satisfy all of the following should be treated as output results:

| Condition | Description |
|:--|:--|
| `message.author.role == "tool"` | The source is a tool message |
| `metadata.async_task_type == "image_gen"` | The tool task is image generation |
| `asset_pointer` is `file-service://...` or `sediment://...` | Points to a resolvable image resource |

## Image pointer types

| Pointer | Common source | Description |
|:--|:--|:--|
| `file-service://file_xxx` | Image tool output | Resolvable via the file download API |
| `sediment://file_xxx` | Input attachment or image tool output | Determine the source by message role |
| `file_upload` | Upload-in-progress placeholder | Usually should not be treated as output |

Do not treat something as an output image just because `file_` or `sediment://` appears in a string. You must also consider the message role and task type.

## Policy refusal case

When the upstream refuses a request, it usually does not produce an image tool message, but returns a regular assistant text:

```text
I can't assist with that request. If you have another type of modification...
```

Commonly accompanying events:

```json
{"type":"title_generation","title":"Request Denied","conversation_id":"..."}
```

```json
{
  "type": "server_ste_metadata",
  "metadata": {
    "tool_invoked": false,
    "turn_use_case": "multimodal",
    "did_prompt_contain_image": true
  },
  "conversation_id": "..."
}
```

Key points:

| Condition | Behavior |
|:--|:--|
| There is an assistant refusal text | Return the text message |
| `tool_invoked == false` | Indicates there is no actual tool result |
| No message with `role=tool` and `async_task_type=image_gen` | Do not collect output images |
| The user input message contains an image pointer | Still treat it only as an input attachment |

## moderation case

Some requests may return a moderation event:

```json
{
  "type": "moderation",
  "moderation_response": {
    "blocked": true
  },
  "conversation_id": "..."
}
```

If `blocked == true`, the turn should be considered policy-blocked. If assistant text follows, return that text first; if there is no text, return an appropriate error message.

## marker and title events

The upstream returns some auxiliary events:

```json
{"type":"message_marker","marker":"user_visible_token","event":"first"}
{"type":"message_marker","marker":"last_token","event":"last"}
{"type":"title_generation","title":"...","conversation_id":"..."}
```

These events are usually used for frontend display, title generation, or streaming status markers, and do not represent actual text content or image results.

## metadata events

`server_ste_metadata` describes this turn's scheduling and tool state:

```json
{
  "type": "server_ste_metadata",
  "metadata": {
    "tool_invoked": true,
    "turn_use_case": "multimodal",
    "model_slug": "i-mini-m",
    "did_prompt_contain_image": true
  }
}
```

Common checks:

| Field | Description |
|:--|:--|
| `tool_invoked == true` | The upstream considers that a tool was invoked this turn |
| `tool_invoked == false` | No tool was invoked; common for refusals or plain-text responses |
| `turn_use_case == "text"` | Handle as a text response |
| `turn_use_case == "multimodal"` | A multimodal request; does not necessarily mean there is image output |
| `did_prompt_contain_image == true` | The input contains an image; does not mean the output contains an image |

## Determining the result after the stream ends

After the SSE ends, determine the result in this order:

1. If image tool output pointers were collected, resolve and download the output images.
2. If there is no output image pointer but there is assistant text, and this turn was blocked or no tool was invoked, return the text message.
3. If there is no output image pointer but there is a `conversation_id`, query the full conversation details and keep looking for image tool output.
4. When querying the full conversation, still only read messages with `role=tool` and `async_task_type=image_gen`.
5. If there is neither an image result nor text, return the upstream error or an empty-result error.
