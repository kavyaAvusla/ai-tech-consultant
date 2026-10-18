/** USD per million tokens. Used only to turn measured token counts into cost. */
export const TOKEN_PRICES_PER_MILLION: Record<string, { input: number; output: number }> = {
  "claude-haiku-5-5": { input: 0.1, output: 0.5 },
  "claude-sonnet-5-5": { input: 2, output: 10 },
};

export function tokenCostUsd(model: string, inputTokens: number, outputTokens: number): number {
  const price = TOKEN_PRICES_PER_MILLION[model];
  if (!price) {
    throw new Error(`No token price configured for ${model}.`);
  }
  return (inputTokens * price.input + outputTokens * price.output) / 1_000_000;
}
