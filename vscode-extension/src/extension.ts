import * as vscode from "vscode";
import * as http from "http";
import * as path from "path";
import { ChildProcess, spawn } from "child_process";

const SERVER_PORT = () =>
  vscode.workspace
    .getConfiguration("codebaseAgent")
    .get<number>("serverPort", 57384);

// ------------------------------------------------------------------ //
//  HTTP helpers (Node built-in, no extra deps)                        //
// ------------------------------------------------------------------ //

function httpPost(endpoint: string, body: object): Promise<any> {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = http.request(
      {
        hostname: "127.0.0.1",
        port: SERVER_PORT(),
        path: endpoint,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(data),
        },
      },
      (res) => {
        let raw = "";
        res.on("data", (c) => (raw += c));
        res.on("end", () => {
          try {
            resolve(JSON.parse(raw));
          } catch {
            resolve({ answer: raw });
          }
        });
      }
    );
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

function httpGet(endpoint: string): Promise<any> {
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        hostname: "127.0.0.1",
        port: SERVER_PORT(),
        path: endpoint,
        method: "GET",
      },
      (res) => {
        let raw = "";
        res.on("data", (c) => (raw += c));
        res.on("end", () => {
          try {
            resolve(JSON.parse(raw));
          } catch {
            resolve({});
          }
        });
      }
    );
    req.on("error", reject);
    req.end();
  });
}

async function isServerRunning(): Promise<boolean> {
  try {
    await httpGet("/health");
    return true;
  } catch {
    return false;
  }
}

// ------------------------------------------------------------------ //
//  Webview panel                                                       //
// ------------------------------------------------------------------ //

function getWebviewContent(): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:var(--vscode-font-family);font-size:13px;
       background:var(--vscode-sideBar-background);
       color:var(--vscode-foreground);height:100vh;display:flex;flex-direction:column}
  #toolbar{padding:8px;border-bottom:1px solid var(--vscode-panel-border);
           display:flex;gap:6px;flex-wrap:wrap}
  button{background:var(--vscode-button-background);
         color:var(--vscode-button-foreground);
         border:none;border-radius:3px;padding:4px 10px;
         font-size:12px;cursor:pointer}
  button:hover{background:var(--vscode-button-hoverBackground)}
  button.secondary{background:var(--vscode-button-secondaryBackground);
                   color:var(--vscode-button-secondaryForeground)}
  #status{font-size:11px;padding:4px 8px;
          color:var(--vscode-descriptionForeground);
          border-bottom:1px solid var(--vscode-panel-border)}
  #chat{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:10px}
  .msg{max-width:100%;word-break:break-word;line-height:1.5}
  .msg.user{align-self:flex-end;background:var(--vscode-button-background);
            color:var(--vscode-button-foreground);
            padding:6px 10px;border-radius:8px 8px 2px 8px;max-width:85%}
  .msg.assistant{align-self:flex-start;background:var(--vscode-editor-inactiveSelectionBackground);
                 padding:8px 10px;border-radius:2px 8px 8px 8px;max-width:100%}
  .msg.system{align-self:center;font-size:11px;
              color:var(--vscode-descriptionForeground);font-style:italic}
  .citations{margin-top:8px;display:flex;flex-direction:column;gap:3px}
  .cite{font-size:11px;color:var(--vscode-textLink-foreground);
        cursor:pointer;text-decoration:underline;width:fit-content}
  .cite:hover{color:var(--vscode-textLink-activeForeground)}
  pre{background:var(--vscode-textCodeBlock-background);
      padding:8px;border-radius:4px;overflow-x:auto;
      font-family:var(--vscode-editor-font-family);font-size:12px;margin:4px 0}
  code{font-family:var(--vscode-editor-font-family);font-size:12px;
       background:var(--vscode-textCodeBlock-background);padding:1px 4px;border-radius:2px}
  #input-row{display:flex;gap:6px;padding:8px;
             border-top:1px solid var(--vscode-panel-border)}
  #question{flex:1;background:var(--vscode-input-background);
            color:var(--vscode-input-foreground);
            border:1px solid var(--vscode-input-border,transparent);
            border-radius:3px;padding:6px 8px;font-size:13px;resize:none;height:60px;
            font-family:var(--vscode-font-family)}
  #question:focus{outline:1px solid var(--vscode-focusBorder)}
  #send{align-self:flex-end;padding:6px 14px}
  .spinner{display:inline-block;width:12px;height:12px;
           border:2px solid var(--vscode-foreground);
           border-top-color:transparent;border-radius:50%;
           animation:spin .7s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div id="toolbar">
  <button onclick="indexWorkspace()">Index workspace</button>
  <button class="secondary" onclick="checkStatus()">Status</button>
  <button class="secondary" onclick="clearIndex()">Clear index</button>
</div>
<div id="status">Not connected — make sure the sidecar server is running.</div>
<div id="chat"></div>
<div id="input-row">
  <textarea id="question" placeholder="Ask anything about your codebase…"
    onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendQuestion()}"></textarea>
  <button id="send" onclick="sendQuestion()">Ask</button>
</div>

<script>
const vscode = acquireVsCodeApi();
let isLoading = false;

// ── receive messages from extension host ──────────────────────────
window.addEventListener('message', e => {
  const msg = e.data;
  if (msg.type === 'status')   setStatus(msg.text, msg.ok);
  if (msg.type === 'answer')   showAnswer(msg);
  if (msg.type === 'system')   addMsg(msg.text, 'system');
  if (msg.type === 'loading')  setLoading(msg.value);
});

function setStatus(text, ok) {
  const el = document.getElementById('status');
  el.textContent = text;
  el.style.color = ok
    ? 'var(--vscode-testing-iconPassed)'
    : 'var(--vscode-descriptionForeground)';
}

function addMsg(text, role) {
  const chat = document.getElementById('chat');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

function showAnswer(msg) {
  const chat = document.getElementById('chat');
  const div = document.createElement('div');
  div.className = 'msg assistant';

  // Render markdown-ish: code blocks and inline code
  let html = escapeHtml(msg.answer)
    .replace(/\`\`\`([\\s\\S]*?)\`\`\`/g, '<pre>$1</pre>')
    .replace(/\`([^\`]+)\`/g, '<code>$1</code>')
    .replace(/\\n/g, '<br>');
  div.innerHTML = html;

  // Citations
  if (msg.citations && msg.citations.length > 0) {
    const citeDiv = document.createElement('div');
    citeDiv.className = 'citations';
    msg.citations.forEach(c => {
      const a = document.createElement('span');
      a.className = 'cite';
      const short = c.file_path.split('/').slice(-2).join('/');
      a.textContent = short + ':' + c.start_line;
      a.title = c.file_path + ':' + c.start_line;
      a.onclick = () => vscode.postMessage({
        type: 'openFile',
        file: c.file_path,
        line: c.start_line
      });
      citeDiv.appendChild(a);
    });
    div.appendChild(citeDiv);
  }

  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function setLoading(val) {
  isLoading = val;
  const btn = document.getElementById('send');
  btn.innerHTML = val ? '<span class="spinner"></span>' : 'Ask';
  btn.disabled = val;
}

function sendQuestion() {
  if (isLoading) return;
  const q = document.getElementById('question').value.trim();
  if (!q) return;
  document.getElementById('question').value = '';
  addMsg(q, 'user');
  vscode.postMessage({ type: 'query', question: q });
}

function indexWorkspace() {
  vscode.postMessage({ type: 'indexWorkspace' });
}

function checkStatus() {
  vscode.postMessage({ type: 'checkStatus' });
}

function clearIndex() {
  vscode.postMessage({ type: 'clearIndex' });
}

// Initial status check on load
setTimeout(() => vscode.postMessage({ type: 'checkStatus' }), 500);
</script>
</body>
</html>`;
}

// ------------------------------------------------------------------ //
//  Extension activate                                                  //
// ------------------------------------------------------------------ //

export function activate(context: vscode.ExtensionContext) {
  console.log("[codebase-agent] Extension activated");

  // ── Webview provider ──────────────────────────────────────────────
  const provider = new ChatViewProvider(context);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("codebaseAgent.chatView", provider)
  );

  // ── Commands ──────────────────────────────────────────────────────
  context.subscriptions.push(
    vscode.commands.registerCommand("codebaseAgent.indexWorkspace", async () => {
      const folders = vscode.workspace.workspaceFolders;
      if (!folders || folders.length === 0) {
        vscode.window.showErrorMessage("No workspace folder open.");
        return;
      }
      provider.triggerIndex(folders[0].uri.fsPath);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("codebaseAgent.indexFolder", async () => {
      const uri = await vscode.window.showOpenDialog({
        canSelectFolders: true,
        canSelectFiles: false,
        canSelectMany: false,
        openLabel: "Index this folder",
      });
      if (uri && uri[0]) {
        provider.triggerIndex(uri[0].fsPath);
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("codebaseAgent.clearIndex", async () => {
      const ok = await vscode.window.showWarningMessage(
        "Clear the entire codebase index?",
        "Yes, clear it",
        "Cancel"
      );
      if (ok === "Yes, clear it") {
        provider.clearIndex();
      }
    })
  );
}

export function deactivate() {}

// ------------------------------------------------------------------ //
//  ChatViewProvider                                                    //
// ------------------------------------------------------------------ //

class ChatViewProvider implements vscode.WebviewViewProvider {
  private _view?: vscode.WebviewView;

  constructor(private readonly _ctx: vscode.ExtensionContext) {}

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ) {
    this._view = webviewView;
    webviewView.webview.options = { enableScripts: true };
    webviewView.webview.html = getWebviewContent();

    webviewView.webview.onDidReceiveMessage(async (msg) => {
      switch (msg.type) {
        case "query":
          await this._handleQuery(msg.question);
          break;
        case "indexWorkspace": {
          const folders = vscode.workspace.workspaceFolders;
          if (folders && folders.length > 0) {
            this.triggerIndex(folders[0].uri.fsPath);
          } else {
            this._post({ type: "system", text: "No workspace folder open." });
          }
          break;
        }
        case "checkStatus":
          await this._checkStatus();
          break;
        case "clearIndex":
          this.clearIndex();
          break;
        case "openFile":
          this._openFile(msg.file, msg.line);
          break;
      }
    });
  }

  private _post(msg: object) {
    this._view?.webview.postMessage(msg);
  }

  private async _checkStatus() {
    try {
      const data = await httpGet("/status");
      const chunks = data.total_chunks ?? 0;
      const files  = data.total_files ?? 0;
      const indexing = data.is_indexing ? " (indexing…)" : "";
      this._post({
        type: "status",
        text: chunks > 0
          ? `Indexed ${chunks} chunks from ${files} files${indexing}`
          : `Server connected — no index yet. Click "Index workspace".`,
        ok: true,
      });
    } catch {
      this._post({
        type: "status",
        text: "Server not running. Start it: python3 run_server.py",
        ok: false,
      });
    }
  }

  private async _handleQuery(question: string) {
    this._post({ type: "loading", value: true });
    try {
      const data = await httpPost("/query", { question, top_k: 8 });
      if (data.detail) {
        this._post({ type: "answer", answer: data.detail, citations: [] });
      } else {
        this._post({
          type: "answer",
          answer: data.answer,
          citations: data.citations ?? [],
          chunks_used: data.chunks_used,
        });
      }
    } catch (e: any) {
      this._post({
        type: "answer",
        answer: `Error: ${e.message}. Is the server running on port ${SERVER_PORT()}?`,
        citations: [],
      });
    } finally {
      this._post({ type: "loading", value: false });
    }
  }

  triggerIndex(folderPath: string) {
    this._post({ type: "system", text: `Indexing ${folderPath} …` });
    httpPost("/index", { root_path: folderPath })
      .then(() => {
        this._post({ type: "system", text: "Indexing started — this may take a minute." });
        // Poll until done
        const poll = setInterval(async () => {
          try {
            const s = await httpGet("/status");
            if (!s.is_indexing) {
              clearInterval(poll);
              this._post({
                type: "status",
                text: `Indexed ${s.total_chunks} chunks from ${s.total_files} files`,
                ok: true,
              });
              this._post({
                type: "system",
                text: `Done! ${s.total_chunks} chunks ready. Ask me anything.`,
              });
            }
          } catch {
            clearInterval(poll);
          }
        }, 3000);
      })
      .catch((e) => {
        this._post({ type: "system", text: `Index error: ${e.message}` });
      });
  }

  clearIndex() {
    httpPost("/index", {})   // will fail gracefully
      .catch(() => {});
    // Use DELETE via raw http
    const req = http.request({
      hostname: "127.0.0.1",
      port: SERVER_PORT(),
      path: "/index",
      method: "DELETE",
    }, (res) => {
      this._post({ type: "system", text: "Index cleared." });
      this._post({ type: "status", text: "Index cleared.", ok: false });
    });
    req.on("error", () => {});
    req.end();
  }

  private _openFile(filePath: string, line: number) {
    const uri = vscode.Uri.file(filePath);
    vscode.workspace.openTextDocument(uri).then((doc) => {
      vscode.window.showTextDocument(doc, {
        selection: new vscode.Range(
          new vscode.Position(Math.max(0, line - 1), 0),
          new vscode.Position(Math.max(0, line - 1), 0)
        ),
        preserveFocus: false,
      });
    });
  }
}