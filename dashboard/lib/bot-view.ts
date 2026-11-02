import type { Bot } from "./bots.ts";

export function filterBots(bots: Bot[], value: string): Bot[] {
  const query = value.trim().toLowerCase();
  return bots.filter((bot) => bot.name.toLowerCase().includes(query));
}
