# Feature status

This document is based on the current implementation in this repository and helps users quickly see which features are already available, which are still being refined, and which are pending.

| Feature | Status | Notes |
| --- | --- | --- |
| OpenAI-compatible `POST /v1/images/generations` | ✅ | Supported; used for image generation and can return multiple images via `n`. |
| OpenAI-compatible `POST /v1/images/edits` | ✅ | Supported; you can upload an image to edit. |
| `POST /v1/chat/completions` for image workflows | ✅ | Image-related requests are supported. |
| `POST /v1/responses` for image workflows | ✅ | The image-generation tool call is supported. |
| `GET /v1/models` endpoint | ✅ | Currently returns `gpt-image-2`, `codex-gpt-image-2`, `auto`, `gpt-5`, `gpt-5-1`, `gpt-5-2`, `gpt-5-3`, `gpt-5-3-mini`, `gpt-5-mini`. |
| Generating multiple images at once | ✅ | Supported on both backend and frontend. |
| Parallel image generation | ✅ | Multiple images are generated simultaneously using independent threads and accounts; can be disabled via `image_parallel_generation`. |
| Image generation progress tracking | ✅ | Tasks show the current step (uploading / warming up / getting token / generating, etc.) with elapsed-time stats. |
| Image timeout resume-polling | ✅ | Timed-out tasks can keep waiting; the frontend shows a "Keep waiting" button and the backend exposes a resume-poll API. |
| Image double-confirm and check-before-hit | ✅ | Configurable via `image_settle_enabled` and `image_check_before_hit_enabled`; disabling them skips the wait and returns directly. |
| Frontend image workbench | ✅ | Supports image generation, image editing, model selection, history, and full-size viewing. |
| Frontend image lazy-loading and scroll optimization | ✅ | LazyImage lazy loading, saving/restoring scroll position on conversation switch, and bfcache page-restore sync. |
| Frontend image input / reference-image interaction | ✅ | Supports reference-image upload, preview, removal, and the edit-mode workflow. |
| Codex image API reverse engineering | ✅ | Supported; available only for `Plus` / `Team` / `Pro` subscriptions, with the model alias `codex-gpt-image-2`. You can map it back to `gpt-image-2` in other scenarios if needed. This is the Codex reverse-engineered path, used to distinguish it from the official web drawing; the same account usually has separate image quotas for the web and for Codex. |
| Cherry Studio integration | ✅ | Supported as a drawing endpoint for Cherry Studio. |
| New API integration | ✅ | Integration with New API is supported. |
| Account pool management | ✅ | Supports listing, filtering, bulk operations, export, manual editing, refresh, and deletion. |
| Async account refresh progress tracking | ✅ | Refresh and re-login are now asynchronous, with the frontend polling for progress. |
| Password re-login to recover abnormal accounts | ✅ | The account pool page supports re-login, and abnormal accounts can be re-logged automatically after refresh. |
| Account quota refresh and recovery-time sync | ✅ | Account info refresh is supported, and rate-limited accounts continue to be checked automatically. |
| Automatic cleanup of invalid tokens | ✅ | Invalid tokens are removed automatically. |
| CPA connection management | ✅ | Supports adding, editing, querying, and deleting CPA connections. |
| CPA file browsing and on-demand import | ✅ | Supports reading the remote file list, filtering, selecting, and importing into the local pool. |
| CPA import progress tracking | ✅ | Supports import-progress display with polling updates. |
| `sub2api` connection management and account browsing | ✅ | Supports adding, editing, and deleting `sub2api` servers, group queries, and reading the OpenAI OAuth account list. |
| `sub2api` import | ✅ | Supports selecting OpenAI OAuth accounts from `sub2api`, bulk-fetching their `access_token`s into the local pool, and showing import progress. |
| Docker self-hosting | ✅ | Supports Docker Compose deployment and provides multi-arch images. |
| Multiple reference images in compatible APIs | ✅ | Implemented; multiple reference images can be passed to the compatible APIs. |
| More advanced token scheduling strategy | ⚠️ | A basic round-robin and rate-limit refresh mechanism exists; more complex scheduling strategies are still being refined. |
| Render / Vercel and similar deployment docs | ⚠️ | Docker is currently the primary deployment method; other platforms are not yet documented in detail. |
| `/v1/complete` text completion and streaming output | ✅ | Implemented. |
| Streaming output support | ✅ | Implemented. |
| Text-completion cache and duplicate-request merging | ✅ | The `/v1/chat/completions` text path enables a 60-second short cache, streamed-result replay, in-flight request merging, and adjacent duplicate-message cleanup by default; configurable or disableable via `chat_completion_cache`. |
| Image size parameter | ❌ | Pending. |
| Server-side image URL caching | ✅ | Implemented. |
| `rt_token` refresh | ❌ | Pending. |
| Proxy configuration | ✅ | Supports configuring a global HTTP / HTTPS / SOCKS5 / SOCKS5H proxy from the web UI, applied to outbound requests. |
| Anthropic protocol support | ❌ | Pending. |
