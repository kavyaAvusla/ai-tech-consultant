import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import type { IncomingMessage } from "node:http";
import type { AppEnv } from "../env.js";

export type KbSuccess = {
  ok: true;
  answer: string;
  sources: string[];
  evidence: "strong" | "weak";
  escalation_id: number | null;
};

export type KbFailureKind =
  | "timeout"
  | "unauthorized"
  | "billing"
  | "http_error"
  | "network"
  | "invalid_response";

export type KbFailure = {
  ok: false;
  failure: KbFailureKind;
  status: number | null;
  message: string;
  sources: string[];
};

export type KbResult = KbSuccess | KbFailure;

type QueryPayload = {
  answer?: unknown;
  sources?: unknown;
  evidence?: unknown;
  escalation_id?: unknown;
  error?: unknown;
  code?: unknown;
  detail?: unknown;
};

const DEFAULT_TIMEOUT_MS = 30_000;
const ATTEMPTS = 2;

function asSources(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.length > 0);
}

function asEscalationId(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value) && value > 0) return value;
  return null;
}

function clip(text: string): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > 280 ? `${clean.slice(0, 277)}...` : clean;
}

export function createKnowledgeClient(env: AppEnv, timeoutMs = DEFAULT_TIMEOUT_MS) {
  return {
    query(question: string): Promise<KbResult> {
      return queryKnowledge(env, question, timeoutMs);
    },
  };
}

export async function queryKnowledge(
  env: AppEnv,
  question: string,
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<KbResult> {
  const trimmed = question.trim();
  if (trimmed.length < 3) {
    return {
      ok: false,
      failure: "invalid_response",
      status: null,
      message: "Question is too short to send to the knowledge service.",
      sources: [],
    };
  }

  let last = timeoutFailure(timeoutMs);
  for (let attempt = 1; attempt <= ATTEMPTS; attempt += 1) {
    const result = await queryOnce(env, trimmed, timeoutMs);
    if (result.ok) return result;
    last = result;
    if (result.failure !== "timeout" && result.failure !== "network") return result;
  }
  return last;
}

function timeoutFailure(timeoutMs: number): KbFailure {
  return {
    ok: false,
    failure: "timeout",
    status: null,
    message: `Knowledge Brain did not respond within ${timeoutMs}ms.`,
    sources: [],
  };
}

type HttpResponse = { status: number; raw: string };

function postJson(
  url: string,
  apiKey: string,
  question: string,
  timeoutMs: number,
): { promise: Promise<HttpResponse>; cancel: () => void } {
  const body = JSON.stringify({ question });
  const target = new URL(url);
  const send = target.protocol === "https:" ? httpsRequest : httpRequest;
  let response: IncomingMessage | undefined;
  let cancel = () => undefined;
  const promise = new Promise<HttpResponse>((resolve, reject) => {
    const req = send(
      target,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
          "X-API-Key": apiKey,
        },
        timeout: timeoutMs,
      },
      (res: IncomingMessage) => {
        response = res;
        const chunks: Buffer[] = [];
        const bodyTimer = setTimeout(() => {
          res.destroy(new Error("timeout"));
        }, timeoutMs);
        res.on("data", (chunk: Buffer) => chunks.push(chunk));
        res.on("end", () => {
          clearTimeout(bodyTimer);
          resolve({ status: res.statusCode ?? 0, raw: Buffer.concat(chunks).toString("utf8") });
        });
        res.on("error", (error: Error) => {
          clearTimeout(bodyTimer);
          reject(error);
        });
      },
    );
    cancel = () => {
      req.destroy();
      response?.destroy();
    };
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("timeout"));
    });
    req.on("error", reject);
    req.end(body);
  });
  return { promise, cancel };
}

async function queryOnce(env: AppEnv, question: string, timeoutMs: number): Promise<KbResult> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const call = postJson(`${env.kbApiUrl}/query`, env.kbApiKey, question, timeoutMs);
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      call.cancel();
      reject(new Error("timeout"));
    }, timeoutMs);
  });
  try {
    const response = await Promise.race([call.promise, deadline]);
    return interpretResponse(response.status, response.raw);
  } catch (error) {
    call.cancel();
    call.promise.catch(() => undefined);
    const message = error instanceof Error ? error.message : "";
    if (/timeout/i.test(message)) return timeoutFailure(timeoutMs);
    return {
      ok: false,
      failure: "network",
      status: null,
      message: "Knowledge Brain could not be reached.",
      sources: [],
    };
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function interpretResponse(status: number, raw: string): KbResult {
  let payload: QueryPayload | null = null;
  if (raw.trim().length > 0) {
    try {
      payload = JSON.parse(raw) as QueryPayload;
    } catch {
      payload = null;
    }
  }

  if (status === 401) {
    return {
      ok: false,
      failure: "unauthorized",
      status,
      message: "Knowledge Brain rejected the API key (401).",
      sources: [],
    };
  }

  if (status === 402 || payload?.code === "billing") {
    return {
      ok: false,
      failure: "billing",
      status,
      message: "Knowledge Brain could not answer because the model account is unavailable (402).",
      sources: asSources(payload?.sources),
    };
  }

  if (status < 200 || status >= 300 || payload === null) {
    return {
      ok: false,
      failure: payload === null ? "invalid_response" : "http_error",
      status,
      message: `Knowledge Brain returned HTTP ${response.status}${payload?.code ? ` (${String(payload.code)})` : ""}.`,
      sources: asSources(payload?.sources),
    };
  }

  const evidence = payload.evidence === "strong" || payload.evidence === "weak" ? payload.evidence : null;
  const answer = typeof payload.answer === "string" ? payload.answer.trim() : "";
  if (!evidence || (evidence === "strong" && answer.length === 0)) {
    const code = typeof payload.code === "string" ? payload.code : "invalid_response";
    return {
      ok: false,
      failure: "invalid_response",
      status,
      message: `Knowledge Brain response was incomplete (${code}). No reply was drafted.`,
      sources: asSources(payload.sources),
    };
  }

  return {
    ok: true,
    answer: evidence === "weak" ? "not enough evidence" : answer,
    sources: asSources(payload.sources),
    evidence,
    escalation_id: asEscalationId(payload.escalation_id),
  };
}

export function failureLabel(result: KbFailure): string {
  return clip(result.message);
}
