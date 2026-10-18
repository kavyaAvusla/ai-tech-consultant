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

export async function completeText(
  env: AppEnv,
  system: string,
  user: string,
  maxTokens = 700,
): Promise<string> {
  const client = new Anthropic({ apiKey: env.anthropicApiKey, timeout: 60_000 });
  try {
    const response = await client.messages.create({
      model: env.modelName,
      max_tokens: maxTokens,
      thinking: { type: "disabled" },
      output_config: { effort: "low" },
      system,
      messages: [{ role: "user", content: user }],
    } as Anthropic.MessageCreateParamsNonStreaming);
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
  }
}
