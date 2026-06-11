# Review

- [P2] Poll when the image tool was invoked  
  `services/protocol/conversation.py:586`  
  For image-generation tasks without an input image, the delayed result may still arrive after the SSE returns `tool_invoked: true`, but the new condition here ignores `tool_invoked`. As a result it returns the intermediate text directly instead of continuing to poll the conversation for the image ID.

- [P2] Align CloudMail domain validation with the UI  
  `web/src/app/register/components/register-card.tsx:266`  
  The `cloudmail_gen` placeholder says leaving it empty uses the service default domain, but the backend `create_mailbox` does not accept an empty domain. After a user saves following the UI hint, this provider fails before it can actually create an address.
