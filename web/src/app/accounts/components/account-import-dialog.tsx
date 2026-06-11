"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, type ChangeEvent } from "react";
import {
  ArrowLeft,
  Copy,
  ExternalLink,
  FileJson,
  FileText,
  Files,
  KeyRound,
  LoaderCircle,
  LogIn,
  ServerCog,
  Upload,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  createAccounts,
  finishOAuthLogin,
  startOAuthLogin,
  type Account,
  type AccountImportPayload,
  type OAuthLoginStartResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type ImportMethod = "menu" | "token" | "session" | "codex-auth" | "cpa" | "oauth";

type AccountImportDialogProps = {
  disabled?: boolean;
  onImported: (items: Account[]) => void;
};

type PendingCpaImport = {
  tokens: string[];
  accounts: AccountImportPayload[];
  parsedFileCount: number;
  errorCount: number;
};

const sessionUrl = "https://chatgpt.com/api/auth/session";

function splitTokens(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function getSessionAccessToken(value: unknown) {
  const token = (value as { accessToken?: unknown })?.accessToken;
  return typeof token === "string" ? token.trim() : "";
}

function getCpaAccount(value: unknown): AccountImportPayload | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const raw = value as Record<string, unknown>;
  const tokenValue = raw.access_token ?? raw.accessToken;
  const token = typeof tokenValue === "string" ? tokenValue.trim() : "";
  if (!token) {
    return null;
  }

  const payload: AccountImportPayload = {
    ...raw,
    access_token: token,
    source_type: "codex",
  };
  delete payload.accessToken;
  if (payload.type === "codex") {
    payload.export_type = "codex";
    delete payload.type;
  }
  return payload;
}

function getCodexAuthAccount(value: unknown): AccountImportPayload | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const raw = value as Record<string, unknown>;
  const tokenValue = raw.access_token ?? raw.accessToken;
  const token = typeof tokenValue === "string" ? tokenValue.trim() : "";
  if (!token) {
    return null;
  }

  const payload: AccountImportPayload = {
    ...raw,
    access_token: token,
    export_type: "codex",
    source_type: "codex",
  };
  delete payload.accessToken;
  if (payload.type === "codex") {
    delete payload.type;
  }
  return payload;
}

function readFileAsText(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => reject(reader.error ?? new Error(`Failed to read file: ${file.name}`));
    reader.readAsText(file);
  });
}

function MethodCard({
  title,
  description,
  icon: Icon,
  onClick,
}: {
  title: string;
  description: string;
  icon: typeof KeyRound;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full rounded-2xl border border-stone-200 bg-white p-0 text-left transition hover:border-stone-300 hover:bg-stone-50"
    >
      <Card className="rounded-2xl border-0 bg-transparent shadow-none">
        <CardContent className="flex items-start gap-4 p-4">
          <div className="rounded-xl bg-stone-100 p-3 text-stone-700">
            <Icon className="size-5" />
          </div>
          <div className="space-y-1">
            <div className="text-sm font-semibold text-stone-900">{title}</div>
            <div className="text-sm leading-6 text-stone-500">{description}</div>
          </div>
        </CardContent>
      </Card>
    </button>
  );
}

export function AccountImportDialog({ disabled, onImported }: AccountImportDialogProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState<ImportMethod>("menu");
  const [tokenInput, setTokenInput] = useState("");
  const [sessionInput, setSessionInput] = useState("");
  const [codexAuthInput, setCodexAuthInput] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pendingCpaImport, setPendingCpaImport] = useState<PendingCpaImport | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [oauthEmailHint, setOauthEmailHint] = useState("");
  const [oauthSession, setOauthSession] = useState<OAuthLoginStartResponse | null>(null);
  const [oauthCallbackInput, setOauthCallbackInput] = useState("");
  const [oauthStarting, setOauthStarting] = useState(false);

  const txtInputRef = useRef<HTMLInputElement | null>(null);
  const cpaInputRef = useRef<HTMLInputElement | null>(null);

  const resetState = () => {
    setMethod("menu");
    setTokenInput("");
    setSessionInput("");
    setCodexAuthInput("");
    setPendingCpaImport(null);
    setConfirmOpen(false);
    setOauthEmailHint("");
    setOauthSession(null);
    setOauthCallbackInput("");
    setOauthStarting(false);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      resetState();
    }
  };

  const submitTokens = async (tokens: string[], successText?: string, accountPayloads: AccountImportPayload[] = []) => {
    const normalizedTokens = tokens.map((item) => item.trim()).filter(Boolean);

    if (normalizedTokens.length === 0) {
      toast.error("Please provide at least one valid token first");
      return;
    }

    setIsSubmitting(true);
    try {
      const data = await createAccounts(normalizedTokens, accountPayloads);
      onImported(data.items);
      setOpen(false);
      resetState();

      if ((data.errors?.length ?? 0) > 0) {
        const firstError = data.errors?.[0]?.error;
        toast.error(
          `${successText ?? "Import complete"}: added ${data.added ?? 0}, refreshed ${data.refreshed ?? 0}, failed ${data.errors?.length ?? 0}${firstError ? `, first error: ${firstError}` : ""}`,
        );
      } else {
        toast.success(
          `${successText ?? "Import complete"}: added ${data.added ?? 0}, skipped ${data.skipped ?? 0} duplicates, account info refreshed automatically`,
        );
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to import accounts";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleImportTokenText = async () => {
    await submitTokens(splitTokens(tokenInput), "Access token import complete");
  };

  // Start authorization: get the authorize URL and open it in a new window for the user to log in
  const handleStartOAuth = async () => {
    setOauthStarting(true);
    try {
      const data = await startOAuthLogin(oauthEmailHint.trim());
      setOauthSession(data);
      setOauthCallbackInput("");
      if (typeof window !== "undefined") {
        window.open(data.authorize_url, "_blank", "noopener,noreferrer");
      }
      toast.success("Opened the OpenAI authorization page; after logging in, copy the callback URL back");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to start OAuth";
      toast.error(message);
    } finally {
      setOauthStarting(false);
    }
  };

  // Use the pasted callback URL to exchange tokens and persist them
  const handleFinishOAuth = async () => {
    if (!oauthSession) {
      toast.error("Click \"Open authorization page\" first to get a session");
      return;
    }
    const trimmed = oauthCallbackInput.trim();
    if (!trimmed) {
      toast.error("Please paste the callback URL or code");
      return;
    }

    setIsSubmitting(true);
    try {
      const data = await finishOAuthLogin(oauthSession.session_id, trimmed);
      onImported(data.items);
      setOpen(false);
      resetState();

      if ((data.errors?.length ?? 0) > 0) {
        const firstError = data.errors?.[0]?.error;
        toast.error(
          `OAuth login complete: added ${data.added ?? 0}, refreshed ${data.refreshed ?? 0}, failed ${data.errors?.length ?? 0}${firstError ? `, first error: ${firstError}` : ""}`,
        );
      } else {
        toast.success(
          `OAuth login complete: added ${data.added ?? 0}, skipped ${data.skipped ?? 0} duplicates, account info refreshed automatically`,
        );
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "OAuth token exchange failed";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  // Copy the authorize URL to the clipboard (with browser + fallback support)
  const handleCopyAuthorizeUrl = async () => {
    if (!oauthSession) {
      return;
    }
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(oauthSession.authorize_url);
        toast.success("Authorization URL copied to the clipboard");
      } else {
        toast.error("This environment does not support auto-copy; please select and copy manually");
      }
    } catch {
      toast.error("Copy failed; please select and copy manually");
    }
  };

  const handleTxtSelected = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";

    if (!file) {
      return;
    }

    try {
      const content = await readFileAsText(file);
      const tokens = splitTokens(content);

      if (tokens.length === 0) {
        toast.error("No valid token found in the TXT file");
        return;
      }

      setTokenInput((prev) => {
        const next = [...splitTokens(prev), ...tokens];
        return next.join("\n");
      });
      toast.success(`Read ${tokens.length} tokens from ${file.name}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to read the TXT file";
      toast.error(message);
    }
  };

  const handleImportSessionJson = async () => {
    if (!sessionInput.trim()) {
      toast.error("Please paste the full Session JSON first");
      return;
    }

    try {
      const payload = JSON.parse(sessionInput) as unknown;
      const token = getSessionAccessToken(payload);

      if (!token) {
        toast.error("No accessToken extracted from the Session JSON");
        return;
      }

      await submitTokens([token], "Session JSON import complete");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to parse the Session JSON";
      toast.error(message);
    }
  };

  const handleImportCodexAuthJson = async () => {
    if (!codexAuthInput.trim()) {
      toast.error("Please paste the Codex auth JSON first");
      return;
    }

    try {
      const payload = JSON.parse(codexAuthInput) as unknown;
      const account = getCodexAuthAccount(payload);

      if (!account) {
        toast.error("No access_token extracted from the Codex auth JSON");
        return;
      }

      await submitTokens([account.access_token], "Codex auth JSON import complete", [account]);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to parse the Codex auth JSON";
      toast.error(message);
    }
  };

  const handleCpaSelected = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";

    if (files.length === 0) {
      return;
    }

    try {
      const results = await Promise.all(
        files.map(async (file) => {
          const raw = await readFileAsText(file);
          const parsed = JSON.parse(raw) as unknown;
          const account = getCpaAccount(parsed);
          return {
            account,
          };
        }),
      );

      const accounts = results.map((item) => item.account).filter((item): item is AccountImportPayload => Boolean(item));
      const tokens = accounts.map((item) => item.access_token);
      const parsedFileCount = accounts.length;
      const errorCount = results.length - parsedFileCount;

      if (parsedFileCount === 0) {
        toast.error("No usable access_token found in these CPA JSON files");
        return;
      }

      setPendingCpaImport({
        tokens,
        accounts,
        parsedFileCount,
        errorCount,
      });
      setConfirmOpen(true);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to read the CPA JSON files";
      toast.error(message);
    }
  };

  const renderMethodBody = () => {
    if (method === "token") {
      const tokenCount = splitTokens(tokenInput).length;

      return (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => setMethod("menu")}
              className="inline-flex items-center gap-1 text-sm text-stone-500 transition hover:text-stone-800"
            >
              <ArrowLeft className="size-4" />
              Back to import methods
            </button>
            <span className="text-xs text-stone-400">{tokenCount} tokens detected</span>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-stone-700">Access token list</label>
            <Textarea
              placeholder="One access token per line..."
              value={tokenInput}
              onChange={(event) => setTokenInput(event.target.value)}
              className="min-h-56 resize-none rounded-xl border-stone-200"
            />
          </div>
          <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-1">
                <div className="text-sm font-medium text-stone-800">Import from a TXT file</div>
                <div className="text-sm leading-6 text-stone-500">Supports `.txt`, with one token per line.</div>
              </div>
              <Button
                type="button"
                variant="outline"
                className="rounded-xl border-stone-200 bg-white"
                onClick={() => txtInputRef.current?.click()}
                disabled={isSubmitting}
              >
                <FileText className="size-4" />
                Choose TXT
              </Button>
            </div>
          </div>
          <input
            ref={txtInputRef}
            type="file"
            accept=".txt,text/plain"
            className="hidden"
            onChange={(event) => void handleTxtSelected(event)}
          />
        </div>
      );
    }

    if (method === "session") {
      return (
        <div className="space-y-4">
          <button
            type="button"
            onClick={() => setMethod("menu")}
            className="inline-flex items-center gap-1 text-sm text-stone-500 transition hover:text-stone-800"
          >
            <ArrowLeft className="size-4" />
            Back to import methods
          </button>
          <div className="rounded-2xl border border-stone-200 bg-stone-50 p-4 text-sm leading-6 text-stone-600">
            Open
            {" "}
            <a
              href={sessionUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 font-medium text-stone-900 underline underline-offset-4"
            >
              {sessionUrl}
              <ExternalLink className="size-3.5" />
            </a>
. Copy the full JSON returned by the page; the system will extract its `accessToken` automatically.
          </div>
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
            <div className="font-medium">Risk notice</div>
            <div>
              Do not use your main account; prefer a rarely-used secondary account to avoid the risk of bans. This project takes no responsibility for ban risk.
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-stone-700">Session JSON</label>
            <Textarea
              placeholder='Paste the full JSON, e.g. an object containing "accessToken"...'
              value={sessionInput}
              onChange={(event) => setSessionInput(event.target.value)}
              className="min-h-56 resize-none rounded-xl border-stone-200 font-mono text-xs"
            />
          </div>
        </div>
      );
    }

    if (method === "oauth") {
      return (
        <div className="space-y-4">
          <button
            type="button"
            onClick={() => setMethod("menu")}
            className="inline-flex items-center gap-1 text-sm text-stone-500 transition hover:text-stone-800"
          >
            <ArrowLeft className="size-4" />
            Back to import methods
          </button>
          <div className="rounded-2xl border border-stone-200 bg-stone-50 p-4 text-sm leading-6 text-stone-600 space-y-2">
            <div className="font-medium text-stone-800">Steps</div>
            <ol className="list-decimal pl-5 space-y-1">
              <li>(Optional) Enter your ChatGPT account email; the login page will prefill it.</li>
              <li>Click "Open authorization page" below and log into your ChatGPT account in a new tab.</li>
              <li>After login the browser redirects to <code className="rounded bg-stone-200 px-1">platform.openai.com/auth/callback?code=...</code>. Immediately copy the full URL from the address bar (or open F12, find the callback line in Network, right-click Copy → Copy URL).</li>
              <li>Paste the callback URL into the box below and click "Finish import".</li>
            </ol>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-stone-700">Email (optional prefill)</label>
            <input
              type="email"
              placeholder="you@example.com"
              value={oauthEmailHint}
              onChange={(event) => setOauthEmailHint(event.target.value)}
              disabled={Boolean(oauthSession) || oauthStarting}
              className="w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-sm outline-none focus:border-stone-400"
            />
          </div>
          {!oauthSession ? (
            <Button
              type="button"
              className="h-10 rounded-xl bg-stone-950 text-white hover:bg-stone-800"
              onClick={() => void handleStartOAuth()}
              disabled={oauthStarting}
            >
              {oauthStarting ? <LoaderCircle className="size-4 animate-spin" /> : <ExternalLink className="size-4" />}
              Open authorization page
            </Button>
          ) : (
            <div className="space-y-3">
              <div className="rounded-2xl border border-stone-200 bg-white p-3 text-xs leading-6 text-stone-600 break-all font-mono">
                {oauthSession.authorize_url}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="rounded-xl border-stone-200 bg-white"
                  onClick={() => void handleCopyAuthorizeUrl()}
                >
                  <Copy className="size-4" />
                  Copy authorization URL
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="rounded-xl border-stone-200 bg-white"
                  onClick={() => window.open(oauthSession.authorize_url, "_blank", "noopener,noreferrer")}
                >
                  <ExternalLink className="size-4" />
                  Open again
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="rounded-xl border-stone-200 bg-white"
                  onClick={() => {
                    setOauthSession(null);
                    setOauthCallbackInput("");
                  }}
                >
                  Regenerate
                </Button>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">Paste callback URL (or just the code)</label>
                <Textarea
                  placeholder={"https://platform.openai.com/auth/callback?code=...&state=..."}
                  value={oauthCallbackInput}
                  onChange={(event) => setOauthCallbackInput(event.target.value)}
                  className="min-h-24 resize-none rounded-xl border-stone-200 font-mono text-xs"
                />
              </div>
            </div>
          )}
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
            <div className="font-medium">Note</div>
            <div>
              The authorization code can only be used once. If the callback page finishes loading and shows an OpenAI error page, the code has most likely been consumed;
              click "Regenerate" and try again. The whole flow just needs to finish within 10 minutes.
            </div>
          </div>
        </div>
      );
    }

    if (method === "cpa") {
      return (
        <div className="space-y-4">
          <button
            type="button"
            onClick={() => setMethod("menu")}
            className="inline-flex items-center gap-1 text-sm text-stone-500 transition hover:text-stone-800"
          >
            <ArrowLeft className="size-4" />
            Back to import methods
          </button>
          <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 p-5">
            <div className="space-y-2">
              <div className="text-sm font-medium text-stone-800">Select multiple local CPA JSON files</div>
              <div className="text-sm leading-6 text-stone-500">
                Each file should be a JSON object. The system extracts `access_token` or `accessToken` from the object automatically,
              </div>
            </div>
            <Button
              type="button"
              className="mt-4 rounded-xl bg-stone-950 text-white hover:bg-stone-800"
              onClick={() => cpaInputRef.current?.click()}
              disabled={isSubmitting}
            >
              <Files className="size-4" />
              Choose multiple JSON files
            </Button>
          </div>
          <input
            ref={cpaInputRef}
            type="file"
            accept=".json,application/json"
            multiple
            className="hidden"
            onChange={(event) => void handleCpaSelected(event)}
          />
          {pendingCpaImport ? (
            <div className="rounded-2xl border border-stone-200 bg-white p-4 text-sm leading-6 text-stone-600">
              Last read found {pendingCpaImport.parsedFileCount} tokens
              {pendingCpaImport.errorCount > 0 ? `, plus ${pendingCpaImport.errorCount} files that could not be parsed` : ""}.
            </div>
          ) : null}
        </div>
      );
    }

    if (method === "codex-auth") {
      return (
        <div className="space-y-4">
          <button
            type="button"
            onClick={() => setMethod("menu")}
            className="inline-flex items-center gap-1 text-sm text-stone-500 transition hover:text-stone-800"
          >
            <ArrowLeft className="size-4" />
            Back to import methods
          </button>
          <div className="space-y-2">
            <label className="text-sm font-medium text-stone-700">Codex auth JSON</label>
            <Textarea
              placeholder='Paste the Codex auth JSON containing "access_token", "refresh_token", "id_token"...'
              value={codexAuthInput}
              onChange={(event) => setCodexAuthInput(event.target.value)}
              className="min-h-64 resize-none rounded-xl border-stone-200 font-mono text-xs"
            />
          </div>
        </div>
      );
    }

    return (
      <div className="space-y-3">
        <MethodCard
          title="OAuth login for an existing account (with auto-refresh)"
          description="Log into your ChatGPT account in the browser; paste back the callback URL to obtain a refresh_token, and the backend will renew it automatically."
          icon={LogIn}
          onClick={() => setMethod("oauth")}
        />
        <MethodCard
          title="Import access token"
          description="Paste directly (one per line), or read from a TXT file (one per line)."
          icon={KeyRound}
          onClick={() => setMethod("token")}
        />
        <MethodCard
          title="Import Session JSON"
          description="Copy the full JSON from chatgpt.com's session API; the accessToken is extracted automatically."
          icon={FileJson}
          onClick={() => setMethod("session")}
        />
        <MethodCard
          title="Import Codex auth JSON"
          description="Paste the Codex auth JSON; imported accounts are marked with source codex."
          icon={FileJson}
          onClick={() => setMethod("codex-auth")}
        />
        <MethodCard
          title="Import CPA JSON files"
          description="Select multiple local JSON files at once; the access_token in each object is read and imported."
          icon={Files}
          onClick={() => setMethod("cpa")}
        />
        <MethodCard
          title="Import from a remote CPA server"
          description="Configure the remote CPA server on the settings page before importing."
          icon={Files}
          onClick={() => {
            setOpen(false);
            resetState();
            router.push("/settings");
          }}
        />
        <MethodCard
          title="Import from a Sub2API server"
          description="Configure the Sub2API server on the settings page, then choose which OpenAI accounts to import."
          icon={ServerCog}
          onClick={() => {
            setOpen(false);
            resetState();
            router.push("/settings");
          }}
        />
      </div>
    );
  };

  const footerDisabled = disabled || isSubmitting;

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <Button
          className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800"
          onClick={() => setOpen(true)}
          disabled={disabled}
        >
          <Upload className="size-4" />
          Import
        </Button>
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>
              {method === "menu"
                ? "Import accounts"
                : method === "token"
                  ? "Import access token"
                  : method === "session"
                    ? "Import Session JSON"
                    : method === "codex-auth"
                      ? "Import Codex auth JSON"
                    : method === "oauth"
                      ? "OAuth login for an existing account"
                      : "Import CPA JSON"}
            </DialogTitle>
            <DialogDescription className="text-sm leading-6">
              {method === "menu"
                ? "Choose an import method. After a successful import, email, type and quota are fetched automatically."
                : method === "token"
                  ? "Paste manually or import from a TXT file, one token per line."
                  : method === "session"
                    ? "Paste the full Session JSON; the system extracts the accessToken automatically."
                    : method === "codex-auth"
                      ? "Paste the Codex auth JSON; the system imports it with source codex."
                    : method === "oauth"
                      ? "Run OpenAI's standard OAuth in the browser; once a refresh_token is obtained the system renews it automatically."
                      : "Read multiple local JSON files at once, with a count confirmation before submitting."}
            </DialogDescription>
          </DialogHeader>

          {renderMethodBody()}

          <DialogFooter className="pt-2">
            <Button
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setOpen(false)}
              disabled={footerDisabled}
            >
              Cancel
            </Button>
            {method === "token" ? (
              <Button
                className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
                onClick={() => void handleImportTokenText()}
                disabled={footerDisabled}
              >
                {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
                Import token
              </Button>
            ) : null}
            {method === "session" ? (
              <Button
                className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
                onClick={() => void handleImportSessionJson()}
                disabled={footerDisabled}
              >
                {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
                Import JSON
              </Button>
            ) : null}
            {method === "codex-auth" ? (
              <Button
                className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
                onClick={() => void handleImportCodexAuthJson()}
                disabled={footerDisabled}
              >
                {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
                Import JSON
              </Button>
            ) : null}
            {method === "oauth" ? (
              <Button
                className={cn(
                  "h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800",
                  !oauthSession ? "hidden" : "",
                )}
                onClick={() => void handleFinishOAuth()}
                disabled={footerDisabled || !oauthSession || !oauthCallbackInput.trim()}
              >
                {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
                Finish import
              </Button>
            ) : null}
            {method === "cpa" ? (
              <Button
                className={cn(
                  "h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800",
                  !pendingCpaImport ? "hidden" : "",
                )}
                onClick={() => setConfirmOpen(true)}
                disabled={footerDisabled || !pendingCpaImport}
              >
                Review import confirmation
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>Confirm CPA token import</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              {pendingCpaImport
                ? `Detected ${pendingCpaImport.parsedFileCount} tokens. Confirm the import?`
                : "No importable tokens have been read yet."}
              {pendingCpaImport?.errorCount
                ? `, plus ${pendingCpaImport.errorCount} files that could not be parsed.`
                : "。"}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="pt-2">
            <Button
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setConfirmOpen(false)}
              disabled={isSubmitting}
            >
              Back
            </Button>
            <Button
              className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
              onClick={() =>
                void submitTokens(
                  pendingCpaImport?.tokens ?? [],
                  "CPA JSON import complete",
                  pendingCpaImport?.accounts ?? [],
                )
              }
              disabled={isSubmitting || !pendingCpaImport}
            >
              {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
              Confirm import
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
