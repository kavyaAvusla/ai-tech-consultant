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

const DEFAULT_TIMEOUT_MS = 90_000;

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

  let response: Response;
  try {
    response = await fetch(`${env.kbApiUrl}/query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": env.kbApiKey,
      },
      body: JSON.stringify({ question: trimmed }),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    const name = error instanceof Error ? error.name : "";
    if (name === "TimeoutError" || name === "AbortError") {
      return {
        ok: false,
        failure: "timeout",
        status: null,
        message: `Knowledge Brain did not respond within ${timeoutMs}ms.`,
        sources: [],
      };
    }
    return {
      ok: false,
      failure: "network",
      status: null,
      message: "Knowledge Brain could not be reached.",
      sources: [],
    };
  }

  const raw = await response.text();
  let payload: QueryPayload | null = null;
  if (raw.trim().length > 0) {
    try {
      payload = JSON.parse(raw) as QueryPayload;
    } catch {
      payload = null;
    }
  }

  if (response.status === 401) {
    return {
      ok: false,
      failure: "unauthorized",
      status: 401,
      message: "Knowledge Brain rejected the API key (401).",
      sources: [],
    };
  }

  if (response.status === 402 || payload?.code === "billing") {
    return {
      ok: false,
      failure: "billing",
      status: response.status,
      message: "Knowledge Brain could not answer because the model account is unavailable (402).",
      sources: asSources(payload?.sources),
    };
  }

  if (!response.ok || payload === null) {
    return {
      ok: false,
      failure: payload === null ? "invalid_response" : "http_error",
      status: response.status,
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
      status: response.status,
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
