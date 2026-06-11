"use client";

import { useState } from "react";
import { LoaderCircle, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { httpRequest } from "@/lib/request";

import { pretty, type ChatCompletionResponse, type ChatMessage } from "./types";

export function ChatPanel() {
  const [model, setModel] = useState("auto");
  const [input, setInput] = useState("Hello, first remember that my project is called chatgpt2api.");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [raw, setRaw] = useState<ChatCompletionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const sendChat = async () => {
    const content = input.trim();
    if (!content) return;
    const nextMessages: ChatMessage[] = [...messages, { role: "user", content }];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);
    setError("");
    try {
      const result = await httpRequest<ChatCompletionResponse>("/v1/chat/completions", { method: "POST", body: { model: model.trim() || "auto", messages: nextMessages } });
      setRaw(result);
      setMessages([...nextMessages, { role: "assistant", content: String(result.choices?.[0]?.message?.content || "") }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const clearChat = () => {
    setMessages([]);
    setRaw(null);
    setError("");
  };

  return (
    <div className="grid h-full min-h-0 gap-8 lg:grid-cols-[360px_minmax(0,1fr)]">
      <section className="flex min-h-0 flex-col lg:border-r lg:border-stone-200/70 lg:pr-8 dark:lg:border-white/10">
        <div className="border-b border-stone-200/70 pb-3 dark:border-white/10">
          <h2 className="text-sm font-medium text-stone-500 dark:text-stone-400">Request</h2>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-auto pt-4">
          <div className="space-y-2">
            <Label htmlFor="chat-model">Model</Label>
            <Input id="chat-model" value={model} onChange={(event) => setModel(event.target.value)} className="rounded-md border-stone-200/70 bg-transparent shadow-none dark:border-white/10" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="chat-input">Message</Label>
            <Textarea id="chat-input" value={input} onChange={(event) => setInput(event.target.value)} className="min-h-32 rounded-md border-stone-200/70 bg-transparent shadow-none dark:border-white/10" />
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => void sendChat()} disabled={loading || !input.trim()}>
              {loading ? <LoaderCircle className="animate-spin" /> : <Send />}
              Send
            </Button>
            <Button size="sm" variant="outline" onClick={clearChat}>
              Clear
            </Button>
          </div>
          {error ? <div className="rounded-md border border-rose-200 bg-rose-50/60 px-3 py-2 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/20 dark:text-rose-300">{error}</div> : null}
          <Textarea value={raw ? pretty(raw) : "{\n  \"messages\": []\n}"} readOnly className="min-h-72 resize-none rounded-md border-stone-200/70 bg-stone-50/50 p-4 font-mono text-xs leading-5 text-stone-600 shadow-none dark:border-white/10 dark:bg-white/[0.03] dark:text-stone-300" />
        </div>
      </section>
      <section className="flex min-h-0 flex-col">
        <div className="border-b border-stone-200/70 pb-3 dark:border-white/10">
          <h2 className="text-sm font-medium text-stone-500 dark:text-stone-400">Conversation</h2>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-auto pt-4">
          {messages.length ? messages.map((message, index) => (
            <div key={`${message.role}-${index}`} className="space-y-1.5 text-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-stone-400 dark:text-stone-500">{message.role}</div>
              <div className="whitespace-pre-wrap leading-7 text-stone-700 dark:text-stone-300">{message.content}</div>
            </div>
          )) : (
            <div className="flex h-full items-center justify-center text-sm text-stone-400 dark:text-stone-500">No messages yet</div>
          )}
        </div>
      </section>
    </div>
  );
}
