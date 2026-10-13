import * as vscode from "vscode";

const DEFAULT_PORT = 8765;

// W12: one terminal named Autopilot, reused while it is open.
function send(text: string): void {
  let term = vscode.window.terminals.find((t) => t.name === "Autopilot");
  if (!term) {
    term = vscode.window.createTerminal({ name: "Autopilot" });
  }
  term.show();
  term.sendText(text);
}

// The run writes its port to <workspace>/.agent/status.port (P13-T01a).
async function statusPort(): Promise<number> {
  const folder = vscode.workspace.workspaceFolders?.[0]?.uri;
  if (!folder) {
    return DEFAULT_PORT;
  }
  try {
    const n = parseInt(new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(folder, ".agent", "status.port"))).trim(), 10);
    return n > 0 && n < 65536 ? n : DEFAULT_PORT;
  } catch {
    return DEFAULT_PORT;
  }
}

async function answers(url: string): Promise<boolean> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(2000) });
    return res.status > 0;
  } catch {
    return false;
  }
}

class StatusView implements vscode.WebviewViewProvider {
  async resolveWebviewView(view: vscode.WebviewView): Promise<void> {
    view.webview.options = { enableScripts: false };
    const render = async (): Promise<void> => {
      const port = await statusPort();
      const local = vscode.Uri.parse(`http://127.0.0.1:${port}/`);
      const up = await answers(local.toString());
      const ext = (await vscode.env.asExternalUri(local)).toString();
      view.webview.html = page(ext, up);
    };
    view.onDidChangeVisibility(() => {
      if (view.visible) {
        void render();
      }
    });
    await render();
  }
}

function page(src: string, up: boolean): string {
  const csp = `default-src 'none'; frame-src ${src}; style-src 'unsafe-inline';`;
  const body = up
    ? `<iframe src="${src}" style="width:100%;height:100vh;border:0"></iframe>`
    : `<p>No run answers. In the terminal, run <code>ap</code> first.</p>`;
  return `<!DOCTYPE html><html><head><meta charset="UTF-8">` +
    `<meta http-equiv="Content-Security-Policy" content="${csp}"></head><body>${body}</body></html>`;
}

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("autopilot.start", () => send("ap start")),
    vscode.commands.registerCommand("autopilot.answer", () => send("ap answer")),
    vscode.commands.registerCommand("autopilot.stop", () => send("ap stop")),
    vscode.window.registerWebviewViewProvider("autopilotStatus", new StatusView())
  );
}

export function deactivate(): void {}
