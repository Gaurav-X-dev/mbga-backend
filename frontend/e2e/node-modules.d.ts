// Minimal typings for the Node built-ins used by the E2E test-data helper.
// (@types/node is not installed so browser code cannot accidentally rely on Node globals.)
declare module "node:child_process" {
  export function execFileSync(
    file: string,
    args: readonly string[],
    options: { cwd?: string; encoding: "utf8" }
  ): string;
}

declare module "node:fs" {
  export function existsSync(path: string): boolean;
}

declare module "node:path" {
  export function dirname(path: string): string;
  export function join(...paths: string[]): string;
  export function resolve(...paths: string[]): string;
}

declare module "node:url" {
  export function fileURLToPath(url: string | URL): string;
}
