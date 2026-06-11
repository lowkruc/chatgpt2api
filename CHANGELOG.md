# Changelog

## Unreleased

## 1.4.1 - 2026-06-03

+ [Added] Account refresh is now asynchronous, with the frontend polling refresh/re-login progress.
+ [Added] The account pool page now supports re-login, recovering abnormal accounts via password login.
+ [Added] Automatically re-login abnormal accounts after refresh (can be enabled in settings).
+ [Added] Image generation supports a parallel mode, generating multiple images simultaneously with independent threads and accounts.
+ [Added] Auto-retry with a different account on image poll timeout (up to 4 times); on connection timeout, retry on the same account with increasing waits.
+ [Added] Image double-confirm and check-before-hit are now configurable; disabling them skips the wait and returns results directly.
+ [Added] Image task progress tracking, showing the current generation step (uploading / warming up / getting token / generating, etc.).
+ [Added] Image timeout resume-polling; the frontend shows a "Keep waiting" button.
+ [Added] New settings for image double-confirm, timeout wait time, auto re-login, and more.
+ [Improved] Optimized scroll-loading performance on the image page, with image lazy loading and scroll-position save/restore on conversation switch.

## 1.4.0 - 2026-05-31

+ [Added] Reverse-engineered AI generation of editable PSD files.
+ [Added] Reverse-engineered AI generation of editable PPT files.

## 1.3.1 - 2026-05-30

+ [Added] Added ChatGPT search debugging and Skills.

## 1.3.0 - 2026-05-30

+ [Added] Reverse-engineered the ChatGPT search API.

## 1.2.4 - 2026-05-30

+ [Added] Added chat-completion caching and duplicate-request merging.
+ [Added] Added one-click navigation to the infinite canvas.

## 1.2.3 - 2026-05-29

+ [Added] Added account-level proxy support.
+ [Fixed] Fixed 503 error messages and the frontend email line-break issue.

## 1.2.2 - 2026-05-29

+ [Added] Added Codex-path image generation, with 2k and 4k support.
+ [Added] Support for refreshing account info via RT.

## 1.2.0 - 2026-05-28

+ [Added] The current baseline version, including the web panel, drawing, account pool management, register, image management, log management, and settings.
+ [Added] The frontend version number can be clicked to open a version-update dialog showing the current version, latest version, and changelog.
+ [Improved] Improved register efficiency, greatly increasing the success rate.
+ [Improved] Improved the configuration options on the image page.
