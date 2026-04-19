import * as vscode from "vscode";
import * as http from "http";
import * as path from "path";
import * as fs from "fs/promises";
import { ChildProcess, spawn } from "child_process";

const GROQ_SECRET_KEY = "groq_api_key";
const SERVER_START_TIMEOUT_MS = 45_000;

const SERVER_PORT = () =>
  vscode.workspace
    .getConfiguration("codebaseAgent")
    .get<number>("serverPort", 57384);

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

function httpDelete(endpoint: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        hostname: "127.0.0.1",
        port: SERVER_PORT(),
        path: endpoint,
        method: "DELETE",
      },
      (res) => {
        res.resume();
        res.on("end", () => resolve());
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

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

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
  #workspace-label{font-size:11px;padding:4px 8px;
                   color:var(--vscode-descriptionForeground);
                   border-bottom:1px solid var(--vscode-panel-border);
                   white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
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
  <button class="secondary" onclick="pickFolder()">Index folder&hellip;</button>
  <button class="secondary" onclick="checkStatus()">Status</button>
  <button class="secondary" onclick="clearIndex()">Clear index</button>
</div>
<div id="workspace-label">Workspace: &mdash;</div>
<div id="status">Preparing Codebase Agent&hellip;</div>
<div id="chat"></div>
<div id="input-row">
  <textarea id="question" placeholder="Ask anything about your codebase&hellip;"
    onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendQuestion()}"></textarea>
  <button id="send" onclick="sendQuestion()">Ask</button>
</div>

<script>
const vscode = acquireVsCodeApi();
let isLoading = false;

window.addEventListener('message', e => {
  const msg = e.data;
  if (msg.type === 'status')           setStatus(msg.text, msg.ok);
  if (msg.type === 'answer')           showAnswer(msg);
  if (msg.type === 'system')           addMsg(msg.text, 'system');
  if (msg.type === 'loading')          setLoading(msg.value);
  if (msg.type === 'workspaceChanged') setWorkspaceLabel(msg.folder);
});

function setStatus(text, ok) {
  const el = document.getElementById('status');
  el.textContent = text;
  el.style.color = ok
    ? 'var(--vscode-testing-iconPassed)'
    : 'var(--vscode-descriptionForeground)';
}

function setWorkspaceLabel(folder) {
  const el = document.getElementById('workspace-label');
  el.textContent = folder ? 'Workspace: ' + folder : 'Workspace: \\u2014';
  el.title = folder ?? '';
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

  let html = escapeHtml(msg.answer)
    .replace(/\`\`\`([\s\S]*?)\`\`\`/g, '<pre>$1</pre>')
    .replace(/\`([^\`]+)\`/g, '<code>$1</code>')
    .replace(/\\n/g, '<br>');
  div.innerHTML = html;

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

function pickFolder() {
  vscode.postMessage({ type: 'pickFolder' });
}

function checkStatus() {
  vscode.postMessage({ type: 'checkStatus' });
}

function clearIndex() {
  vscode.postMessage({ type: 'clearIndex' });
}

setTimeout(() => vscode.postMessage({ type: 'checkStatus' }), 500);
</script>
</body>
</html>`;
}

class ServerManager implements vscode.Disposable {
  private proc: ChildProcess | null = null;
  private bootPromise: Promise<void> | null = null;
  private readonly output = vscode.window.createOutputChannel("Codebase Agent");

  constructor(private readonly ctx: vscode.ExtensionContext) {}

  dispose() {
    if (this.proc) {
      this.proc.kill();
      this.proc = null;
    }
    this.output.dispose();
  }

  async ensureServerReady(progress?: (message: string) => void): Promise<void> {
    if (await isServerRunning()) {
      return;
    }

    if (!this.bootPromise) {
      this.bootPromise = this.boot(progress).finally(() => {
        this.bootPromise = null;
      });
    }

    return this.bootPromise;
  }

  async setGroqApiKey(): Promise<boolean> {
    const value = await vscode.window.showInputBox({
      title: "Enter your Groq API key",
      prompt: "This is stored securely in VS Code secret storage.",
      password: true,
      ignoreFocusOut: true,
      placeHolder: "gsk_...",
      validateInput: (input) => input.trim() ? undefined : "Groq API key is required.",
    });

    if (!value) {
      return false;
    }

    await this.ctx.secrets.store(GROQ_SECRET_KEY, value.trim());
    if (this.proc) {
      this.proc.kill();
      this.proc = null;
    }
    vscode.window.showInformationMessage("Groq API key saved. Codebase Agent is ready to start.");
    return true;
  }

  private async boot(progress?: (message: string) => void): Promise<void> {
    if (!await this.ensureGroqKey()) {
      throw new Error("A Groq API key is required to start Codebase Agent.");
    }

    progress?.("Preparing local Python runtime...");
    const runtime = await this.ensureRuntime(progress);

    progress?.("Starting local server...");
    await this.startServer(runtime, progress);
  }

  private async ensureGroqKey(): Promise<boolean> {
    const existing = await this.ctx.secrets.get(GROQ_SECRET_KEY);
    if (existing) {
      return true;
    }

    const choice = await vscode.window.showInformationMessage(
      "Codebase Agent needs your Groq API key once to start locally.",
      "Add Groq API Key",
      "Cancel"
    );
    if (choice !== "Add Groq API Key") {
      return false;
    }

    return this.setGroqApiKey();
  }

  private async ensureRuntime(progress?: (message: string) => void): Promise<string> {
    const storageRoot = this.ctx.globalStorageUri.fsPath;
    const runtimeRoot = path.join(storageRoot, "runtime");
    const venvRoot = path.join(runtimeRoot, ".venv");
    const stampPath = path.join(runtimeRoot, "install.stamp");
    const pythonConfig = vscode.workspace.getConfiguration("codebaseAgent").get<string>("pythonPath", "").trim();

    await fs.mkdir(runtimeRoot, { recursive: true });

    const basePython = pythonConfig || await this.findPython();
    const venvPython = process.platform === "win32"
      ? path.join(venvRoot, "Scripts", "python.exe")
      : path.join(venvRoot, "bin", "python");

    if (!await this.exists(venvPython)) {
      progress?.("Creating Python environment...");
      await this.runCommand(basePython, ["-m", "venv", venvRoot], runtimeRoot);
    }

    if (!await this.exists(stampPath)) {
      const serverRoot = this.getServerRoot();
      const requirementsPath = path.join(serverRoot, "requirements.txt");
      progress?.("Installing Python dependencies...");
      await this.runCommand(venvPython, ["-m", "pip", "install", "--upgrade", "pip"], runtimeRoot);
      await this.runCommand(venvPython, ["-m", "pip", "install", "-r", requirementsPath], runtimeRoot);
      await fs.writeFile(stampPath, `ready:${Date.now()}\n`, "utf8");
    }

    return venvPython;
  }

  private async startServer(pythonPath: string, progress?: (message: string) => void): Promise<void> {
    if (await isServerRunning()) {
      return;
    }

    const groqApiKey = await this.ctx.secrets.get(GROQ_SECRET_KEY);
    if (!groqApiKey) {
      throw new Error("Missing Groq API key.");
    }

    const storageRoot = this.ctx.globalStorageUri.fsPath;
    const dataRoot = path.join(storageRoot, "data");
    const serverRoot = this.getServerRoot();
    await fs.mkdir(dataRoot, { recursive: true });

    this.output.appendLine(`[codebase-agent] Launching server from ${serverRoot}`);
    this.proc = spawn(
      pythonPath,
      ["run_server.py", "--host", "127.0.0.1", "--port", String(SERVER_PORT())],
      {
        cwd: serverRoot,
        env: {
          ...process.env,
          PYTHONUNBUFFERED: "1",
          GROQ_API_KEY: groqApiKey,
          CHROMA_PATH: path.join(dataRoot, "chroma"),
          SQLITE_PATH: path.join(dataRoot, "symbols.db"),
        },
      }
    );

    this.proc.stdout?.on("data", (chunk) => this.output.append(chunk.toString()));
    this.proc.stderr?.on("data", (chunk) => this.output.append(chunk.toString()));
    this.proc.on("exit", (code, signal) => {
      this.output.appendLine(`[codebase-agent] Server exited (code=${code}, signal=${signal})`);
      this.proc = null;
    });

    const started = await this.waitForHealth();
    if (!started) {
      this.output.show(true);
      throw new Error("The local Codebase Agent server did not start. Check the 'Codebase Agent' output panel.");
    }

    progress?.("Server ready.");
  }

  private getServerRoot(): string {
    const configured = vscode.workspace.getConfiguration("codebaseAgent").get<string>("serverPath", "").trim();
    if (configured) {
      return configured;
    }

    const bundled = path.join(this.ctx.extensionPath, "server");
    return bundled;
  }

  private async waitForHealth(): Promise<boolean> {
    const deadline = Date.now() + SERVER_START_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (await isServerRunning()) {
        return true;
      }
      if (this.proc && this.proc.exitCode !== null) {
        break;
      }
      await delay(1000);
    }
    return false;
  }

  private async findPython(): Promise<string> {
    const candidates: Array<[string, string[]]> = process.platform === "win32"
      ? [["py", ["-3", "--version"]], ["python", ["--version"]]]
      : [["python3", ["--version"]], ["python", ["--version"]]];

    for (const [cmd, args] of candidates) {
      try {
        await this.runCommand(cmd, args, this.ctx.extensionPath, false);
        return cmd;
      } catch {
        continue;
      }
    }

    throw new Error("Python 3.10+ was not found. Install Python or set codebaseAgent.pythonPath.");
  }

  private runCommand(cmd: string, args: string[], cwd: string, log = true): Promise<void> {
    return new Promise((resolve, reject) => {
      if (log) {
        this.output.appendLine(`[codebase-agent] ${cmd} ${args.join(" ")}`);
      }

      const child = spawn(cmd, args, { cwd, env: process.env });
      let stderr = "";

      child.stdout?.on("data", (chunk) => {
        if (log) {
          this.output.append(chunk.toString());
        }
      });
      child.stderr?.on("data", (chunk) => {
        const text = chunk.toString();
        stderr += text;
        if (log) {
          this.output.append(text);
        }
      });
      child.on("error", reject);
      child.on("exit", (code) => {
        if (code === 0) {
          resolve();
        } else {
          reject(new Error(stderr.trim() || `${cmd} exited with code ${code}`));
        }
      });
    });
  }

  private async exists(target: string): Promise<boolean> {
    try {
      await fs.access(target);
      return true;
    } catch {
      return false;
    }
  }
}

export function activate(context: vscode.ExtensionContext) {
  console.log("[codebase-agent] Extension activated");

  const serverManager = new ServerManager(context);
  const provider = new ChatViewProvider(context, serverManager);

  context.subscriptions.push(serverManager);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("codebaseAgent.chatView", provider)
  );

  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      const folders = vscode.workspace.workspaceFolders;
      const newRoot = folders && folders.length > 0 ? folders[0].uri.fsPath : null;
      provider.onWorkspaceFolderChanged(newRoot);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("codebaseAgent.indexWorkspace", async () => {
      const folders = vscode.workspace.workspaceFolders;
      if (!folders || folders.length === 0) {
        vscode.window.showErrorMessage("No workspace folder open.");
        return;
      }
      await provider.triggerIndex(folders[0].uri.fsPath);
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
        await provider.triggerIndex(uri[0].fsPath);
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

  context.subscriptions.push(
    vscode.commands.registerCommand("codebaseAgent.setGroqApiKey", async () => {
      await serverManager.setGroqApiKey();
    })
  );
}

export function deactivate() {}

class ChatViewProvider implements vscode.WebviewViewProvider {
  private _view?: vscode.WebviewView;
  private _indexedRoot: string | null = null;

  constructor(
    private readonly _ctx: vscode.ExtensionContext,
    private readonly _serverManager: ServerManager
  ) {}

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ) {
    this._view = webviewView;
    webviewView.webview.options = { enableScripts: true };
    webviewView.webview.html = getWebviewContent();

    const folders = vscode.workspace.workspaceFolders;
    if (folders && folders.length > 0) {
      this._notifyWorkspace(folders[0].uri.fsPath);
    }

    webviewView.webview.onDidReceiveMessage(async (msg) => {
      switch (msg.type) {
        case "query":
          await this._handleQuery(msg.question);
          break;

        case "indexWorkspace": {
          const currentFolders = vscode.workspace.workspaceFolders;
          if (currentFolders && currentFolders.length > 0) {
            await this.triggerIndex(currentFolders[0].uri.fsPath);
          } else {
            this._post({
              type: "system",
              text: "No workspace folder open. Use 'Index folder…' to pick one manually.",
            });
          }
          break;
        }

        case "pickFolder": {
          const uri = await vscode.window.showOpenDialog({
            canSelectFolders: true,
            canSelectFiles: false,
            canSelectMany: false,
            openLabel: "Index this folder",
          });
          if (uri && uri[0]) {
            await this.triggerIndex(uri[0].fsPath);
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

  onWorkspaceFolderChanged(newRoot: string | null) {
    const label = newRoot ? path.basename(newRoot) : "none";

    if (newRoot !== this._indexedRoot) {
      this._clearIndexSilent().then(() => {
        this._post({
          type: "status",
          text: `Workspace changed to "${label}" — index cleared. Click "Index workspace" to re-index.`,
          ok: false,
        });
        this._post({
          type: "system",
          text: `Switched to "${label}". Old index cleared — click "Index workspace" to index this folder.`,
        });
      });
    }

    this._notifyWorkspace(newRoot);
  }

  async triggerIndex(folderPath: string) {
    this._indexedRoot = folderPath;
    this._notifyWorkspace(folderPath);
    this._post({ type: "system", text: `Indexing ${folderPath} ...` });

    try {
      await this._serverManager.ensureServerReady((message) => {
        this._post({ type: "status", text: message, ok: false });
      });
      await httpPost("/index", { root_path: folderPath });
      this._post({ type: "system", text: "Indexing started — this may take a minute." });
      this.pollUntilIndexed();
    } catch (e: any) {
      this._post({
        type: "system",
        text: `Index error: ${e.message}`,
      });
      this._post({
        type: "status",
        text: "Codebase Agent could not start.",
        ok: false,
      });
    }
  }

  clearIndex() {
    this._clearIndexSilent()
      .then(() => {
        this._post({ type: "system", text: "Index cleared." });
        this._post({ type: "status", text: "Index cleared.", ok: false });
      })
      .catch(() => {
        this._post({ type: "system", text: "Could not reach server to clear index." });
      });
  }

  private _notifyWorkspace(folderPath: string | null) {
    const short = folderPath ? path.basename(folderPath) : null;
    this._post({ type: "workspaceChanged", folder: short });
  }

  private _post(msg: object) {
    this._view?.webview.postMessage(msg);
  }

  private async _checkStatus() {
    try {
      await this._serverManager.ensureServerReady((message) => {
        this._post({ type: "status", text: message, ok: false });
      });
      const data = await httpGet("/status");
      const chunks = data.total_chunks ?? 0;
      const files = data.total_files ?? 0;
      const root = data.root_path ?? this._indexedRoot ?? "unknown";
      const indexing = data.is_indexing ? " (indexing...)" : "";
      const shortRoot = root && root !== "unknown" ? path.basename(root) : "workspace";
      this._post({
        type: "status",
        text: chunks > 0
          ? `Indexed ${chunks} chunks from ${files} files in "${shortRoot}"${indexing}`
          : "Server connected — no index yet. Click 'Index workspace'.",
        ok: true,
      });
    } catch (e: any) {
      this._post({
        type: "status",
        text: e.message || "Server setup failed.",
        ok: false,
      });
    }
  }

  private async _handleQuery(question: string) {
    this._post({ type: "loading", value: true });
    try {
      await this._serverManager.ensureServerReady((message) => {
        this._post({ type: "status", text: message, ok: false });
      });
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
        answer: `Error: ${e.message}`,
        citations: [],
      });
    } finally {
      this._post({ type: "loading", value: false });
    }
  }

  private pollUntilIndexed() {
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
  }

  private async _clearIndexSilent(): Promise<void> {
    try {
      await this._serverManager.ensureServerReady();
      await httpDelete("/index");
    } catch {
      // Ignore setup/connection issues while silently clearing.
    } finally {
      this._indexedRoot = null;
    }
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
