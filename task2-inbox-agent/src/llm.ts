import Anthropic from "@anthropic-ai/sdk";
import type { AppEnv } from "./env.js";
import { redactSecrets } from "./env.js";

export class ModelCallError extends Error {
  readonly kind: "billing" | "unauthorized" | "timeout" | "model_error";

  constructor(kind: ModelCallError["kind"], message: string) {
    super(message);
    this.name = "ModelCallError";
    this.kind = kind;
  }
}

export type TokenUsage = {
  inputTokens: number;
  outputTokens: number;
};

let tokenUsage: TokenUsage = { inputTokens: 0, outputTokens: 0 };

export function resetTokenUsage(): void {
  tokenUsage = { inputTokens: 0, outputTokens: 0 };
}

export function readTokenUsage(): TokenUsage {
  return { ...tokenUsage };
}

function thinkingFor(modelName: string): { type: "disabled" } | { type: "between_tools" } {
  if (modelName.includes("sonnet-5-5") || modelName.includes("sonnet-5.5")) {
    return { type: "between_tools" };
  }
  return { type: "disabled" };
}

export async function completeText(
  env: AppEnv,
  system: string,
  user: string,
  maxTokens = 700,
): Promise<string> {
  const client = new Anthropic({ apiKey: env.anthropicApiKey, timeout: 45_000, maxRetries: 0 });
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 45_000);
  try {
    const response = await Promise.race([
      client.messages.create(
        {
          model: env.modelName,
          max_tokens: maxTokens,
          thinking: thinkingFor(env.modelName),
          output_config: { effort: "low" },
          system,
          messages: [{ role: "user", content: user }],
        } as Anthropic.MessageCreateParamsNonStreaming,
        { timeout: 45_000, maxRetries: 0, signal: controller.signal },
      ),
      new Promise<never>((_, reject) => {
        controller.signal.addEventListener(
          "abort",
          () => reject(new ModelCallError("timeout", "The model request timed out.")),
          { once: true },
        );
      }),
    ]);
    tokenUsage = {
      inputTokens: tokenUsage.inputTokens + (response.usage?.input_tokens ?? 0),
      outputTokens: tokenUsage.outputTokens + (response.usage?.output_tokens ?? 0),
    };
    const text = response.content
      .filter((block): block is Anthropic.TextBlock => block.type === "text")
      .map((block) => block.text)
      .join("\n")
      .trim();
    if (!text) {
      throw new ModelCallError("model_error", "The model returned an empty reply.");
    }
    return text;
  } catch (error) {
    if (error instanceof ModelCallError) throw error;
    const message = error instanceof Error ? error.message : "model request failed";
    const safe = redactSecrets(message, env);
    if (error instanceof Anthropic.APIError) {
      if (error.status === 401) {
        throw new ModelCallError("unauthorized", "Anthropic rejected the API key.");
      }
      if (error.status === 402 || /credit balance|billing/i.test(safe)) {
        throw new ModelCallError("billing", "Anthropic could not run the model (billing).");
      }
    }
    if (/timeout|timed out/i.test(safe)) {
      throw new ModelCallError("timeout", "The model request timed out.");
    }
    if (/credit balance|billing/i.test(safe)) {
      throw new ModelCallError("billing", "Anthropic could not run the model (billing).");
    }
    throw new ModelCallError("model_error", `Model request failed: ${safe.slice(0, 240)}`);
  } finally {
    clearTimeout(timer);
  }
}
