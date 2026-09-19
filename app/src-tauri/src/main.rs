#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use rand::Rng;
use std::net::TcpListener;
use std::path::PathBuf;
use std::sync::{atomic::{AtomicBool, Ordering}, Arc, Mutex};
use tauri::{Emitter, Manager};

/// Pick a free loopback port for the sidecar.
fn free_port() -> u16 {
    let l = TcpListener::bind("127.0.0.1:0").expect("bind loopback");
    let port = l.local_addr().expect("addr").port();
    drop(l);
    port
}

fn gen_token() -> String {
    const CHARS: &[u8] = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
    let mut rng = rand::thread_rng();
    (0..48).map(|_| CHARS[rng.gen_range(0..CHARS.len())] as char).collect()
}

fn configured_data_dir(app: &tauri::App) -> Result<PathBuf, Box<dyn std::error::Error>> {
    #[cfg(windows)] { use winreg::{enums::HKEY_CURRENT_USER, RegKey}; if let Ok(key)=RegKey::predef(HKEY_CURRENT_USER).open_subkey("Software\\ATME") { if let Ok(value)=key.get_value::<String,_>("ProjectDataDir") { if !value.trim().is_empty(){return Ok(PathBuf::from(value));} } } }
    Ok(app.path().app_data_dir()?)
}

#[tauri::command]
fn sidecar_info(state: tauri::State<SidecarState>) -> serde_json::Value {
    serde_json::json!({
        "port": state.port,
        "token": state.token,
        "ready": state.ready.load(Ordering::Acquire),
    })
}

#[derive(Default)]
struct UiState { studio_open: AtomicBool }

#[tauri::command]
fn set_studio_open(open: bool, state: tauri::State<UiState>) {
    state.studio_open.store(open, Ordering::Release);
}

#[tauri::command]
fn import_dropped_source(path: String, project_id: i64, expected_revision: i64,
                         state: tauri::State<SidecarState>) -> Result<serde_json::Value, String> {
    let source = PathBuf::from(path).canonicalize().map_err(|_| "The dropped file is no longer available".to_string())?;
    if !source.is_file() { return Err("Drop a media file, not a folder".into()); }
    let extension = source.extension().and_then(|v| v.to_str()).unwrap_or("").to_ascii_lowercase();
    let endpoint = match extension.as_str() { "wav" => "wav", "mp4"|"mov"|"mkv"|"webm" => "video", _ => return Err("ATME accepts WAV, MP4, MOV, MKV and WebM sources".into()) };
    let file = std::fs::File::open(&source).map_err(|e| e.to_string())?;
    let name = source.file_name().and_then(|v| v.to_str()).unwrap_or("source");
    let response = reqwest::blocking::Client::new().post(format!("http://127.0.0.1:{}/projects/{}/media/{}?expected_revision={}", state.port, project_id, endpoint, expected_revision))
        .bearer_auth(&state.token).header("X-Filename", name).body(reqwest::blocking::Body::new(file)).send().map_err(|e| e.to_string())?;
    let status = response.status(); let value: serde_json::Value = response.json().map_err(|e| e.to_string())?;
    if !status.is_success() { return Err(value.pointer("/detail/message").and_then(|v| v.as_str()).unwrap_or("ATME could not import the dropped file").to_string()); }
    Ok(value)
}

#[tauri::command]
fn mcp_connection_info(state: tauri::State<SidecarState>) -> Result<serde_json::Value, String> {
    let command = display_windows_path(&state.sidecar_path.canonicalize().map_err(|e| e.to_string())?);
    Ok(serde_json::json!({
        "command": command,
        "args": ["mcp"],
        "transport": "stdio",
        "api_keys_required": false,
        "project_store": "resolved_from_windows_atme_configuration",
    }))
}

fn display_windows_path(path: &std::path::Path) -> String {
    let value = path.to_string_lossy().to_string();
    value.strip_prefix(r"\\?\").unwrap_or(&value).to_string()
}

fn client_config_path(client: &str) -> Result<PathBuf, String> {
    match client {
        "chatgpt" | "codex" => std::env::var_os("USERPROFILE").map(PathBuf::from)
            .map(|p| p.join(".codex").join("config.toml"))
            .ok_or_else(|| "Windows user profile could not be located".to_string()),
        "claude" => std::env::var_os("APPDATA").map(PathBuf::from)
            .map(|p| p.join("Claude").join("claude_desktop_config.json"))
            .ok_or_else(|| "Windows application-data folder could not be located".to_string()),
        _ => Err("Unsupported AI client".to_string()),
    }
}

fn write_config_safely(path: &std::path::Path, content: &[u8]) -> Result<Option<PathBuf>, String> {
    let parent = path.parent().ok_or_else(|| "Configuration location is invalid".to_string())?;
    std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let backup = path.with_extension(format!("{}.atme-backup", path.extension().and_then(|v| v.to_str()).unwrap_or("config")));
    let backup_created = if path.exists() {
        std::fs::copy(path, &backup).map_err(|e| format!("Could not back up existing configuration: {e}"))?;
        Some(backup)
    } else { None };
    let temporary = path.with_extension(format!("{}.atme-new", path.extension().and_then(|v| v.to_str()).unwrap_or("config")));
    std::fs::write(&temporary, content).map_err(|e| e.to_string())?;
    if path.exists() { std::fs::remove_file(path).map_err(|e| e.to_string())?; }
    std::fs::rename(&temporary, path).map_err(|e| e.to_string())?;
    Ok(backup_created)
}

#[tauri::command]
fn install_mcp_client(client: String, jev_key: Option<String>, state: tauri::State<SidecarState>) -> Result<serde_json::Value, String> {
    let executable = state.sidecar_path.canonicalize().map_err(|_| "ATME's MCP executable is missing. Reinstall ATME before configuring a client.".to_string())?;
    let command = display_windows_path(&executable);
    let path = client_config_path(&client)?;
    let existing = if path.exists() { std::fs::read_to_string(&path).map_err(|e| e.to_string())? } else { String::new() };
    let backup = if client == "claude" {
        let mut root: serde_json::Value = if existing.trim().is_empty() { serde_json::json!({}) } else { serde_json::from_str(&existing).map_err(|e| format!("Claude configuration is not valid JSON: {e}"))? };
        let object = root.as_object_mut().ok_or_else(|| "Claude configuration must be a JSON object".to_string())?;
        let servers = object.entry("mcpServers").or_insert_with(|| serde_json::json!({})).as_object_mut().ok_or_else(|| "Claude mcpServers must be a JSON object".to_string())?;
        let mut server = serde_json::json!({"command": command, "args": ["mcp"]});
        if let Some(key) = jev_key.filter(|v| !v.trim().is_empty()) { server["env"] = serde_json::json!({"TYPESAFE_API_KEY": key}); }
        servers.insert("atme".to_string(), server);
        write_config_safely(&path, serde_json::to_string_pretty(&root).map_err(|e| e.to_string())?.as_bytes())?
    } else {
        use toml_edit::{value, Array, DocumentMut, Item, Table};
        let mut document = if existing.trim().is_empty() { DocumentMut::new() } else { existing.parse::<DocumentMut>().map_err(|e| format!("Codex configuration is not valid TOML: {e}"))? };
        if !document.as_table().contains_key("mcp_servers") { document["mcp_servers"] = Item::Table(Table::new()); }
        let servers = document["mcp_servers"].as_table_mut().ok_or_else(|| "mcp_servers must be a TOML table".to_string())?;
        let mut server = Table::new(); server["command"] = value(command); let mut args = Array::new(); args.push("mcp"); server["args"] = value(args); server["startup_timeout_sec"] = value(20); server["tool_timeout_sec"] = value(120);
        if let Some(key) = jev_key.filter(|v| !v.trim().is_empty()) { let mut env = Table::new(); env["TYPESAFE_API_KEY"] = value(key); server["env"] = Item::Table(env); }
        servers.insert("atme", Item::Table(server));
        write_config_safely(&path, document.to_string().as_bytes())?
    };
    Ok(serde_json::json!({"installed": true, "client": client, "path": path, "backup": backup, "restart_required": true}))
}

#[tauri::command]
fn remove_mcp_client(client: String) -> Result<serde_json::Value, String> {
    let path = client_config_path(&client)?;
    if !path.exists() { return Ok(serde_json::json!({"removed": false, "path": path})); }
    let existing = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    if client == "claude" {
        let mut root: serde_json::Value = serde_json::from_str(&existing).map_err(|e| format!("Claude configuration is not valid JSON: {e}"))?;
        if let Some(servers) = root.get_mut("mcpServers").and_then(|v| v.as_object_mut()) { servers.remove("atme"); }
        write_config_safely(&path, serde_json::to_string_pretty(&root).map_err(|e| e.to_string())?.as_bytes())?;
    } else {
        use toml_edit::DocumentMut;
        let mut document = existing.parse::<DocumentMut>().map_err(|e| format!("Codex configuration is not valid TOML: {e}"))?;
        if let Some(servers) = document.get_mut("mcp_servers").and_then(|v| v.as_table_mut()) { servers.remove("atme"); }
        write_config_safely(&path, document.to_string().as_bytes())?;
    }
    Ok(serde_json::json!({"removed": true, "path": path, "restart_required": true}))
}

#[tauri::command]
fn open_artifact(path: String, reveal: bool,
                 state: tauri::State<SidecarState>) -> Result<(), String> {
    let requested = PathBuf::from(path).canonicalize().map_err(|e| e.to_string())?;
    let root = state.data_dir.canonicalize().map_err(|e| e.to_string())?;
    if !requested.starts_with(&root) {
        return Err("artifact is outside the ATME data directory".into());
    }
    let mut command = std::process::Command::new("explorer.exe");
    if reveal {
        command.arg(format!("/select,{}", requested.display()));
    } else {
        command.arg(&requested);
    }
    command.spawn().map_err(|e| e.to_string())?;
    Ok(())
}

#[derive(Clone)]
struct SidecarState {
    port: u16,
    token: String,
    child: Arc<Mutex<Option<tauri_plugin_shell::process::CommandChild>>>,
    data_dir: PathBuf,
    sidecar_path: PathBuf,
    ready: Arc<AtomicBool>,
    runtime_file: PathBuf,
}

fn wait_healthz(port: u16, _token: &str, timeout_secs: u64) -> bool {
    let url = format!("http://127.0.0.1:{port}/healthz");
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()
        .expect("health HTTP client");
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);
    while std::time::Instant::now() < deadline {
        if let Ok(resp) = client.get(&url).send() {
            if resp.status().is_success() {
                return true;
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(400));
    }
    false
}

/// Hard-kill the sidecar child (documented zombie-process fix).
fn kill_sidecar(child: tauri_plugin_shell::process::CommandChild) {
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;

        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let pid = child.pid().to_string();
        let _ = std::process::Command::new("taskkill.exe")
            .args(["/PID", &pid, "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .status();
    }
    let _ = child.kill();
}

fn main() {
    let port = free_port();
    let token = gen_token();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(UiState::default())
        .setup(move |app| {
            use tauri_plugin_shell::ShellExt;

            let data_dir = configured_data_dir(app)?;
            std::fs::create_dir_all(&data_dir)?;
            let runtime_dir = data_dir.join("runtime");
            std::fs::create_dir_all(&runtime_dir)?;
            let runtime_file = runtime_dir.join("desktop.json");
            let executable_dir = std::env::current_exe()?
                .parent().ok_or("ATME executable has no parent directory")?.to_path_buf();
            let sidecar_path = executable_dir.join("atme-sidecar.exe");
            let sidecar = app
                .shell()
                .sidecar("atme-sidecar")?
                .env("ATME_DATA_DIR", data_dir.to_string_lossy().to_string())
                .env("ATME_MODEL_DIR", data_dir.join("models").to_string_lossy().to_string())
                .env("ATME_PARENT_PID", std::process::id().to_string());

            // Sidecar contract: port + token via env; binds 127.0.0.1 only.
            let (mut rx, child) = sidecar
                .args([
                    "--port".to_string(),
                    port.to_string(),
                    "--token".to_string(),
                    token.clone(),
                ])
                .spawn()
                .expect("failed to spawn sidecar");

            let runtime_tmp = runtime_dir.join("desktop.json.tmp");
            std::fs::write(&runtime_tmp, serde_json::to_vec(&serde_json::json!({
                "version": 1,
                "pid": std::process::id(),
                "port": port,
                "token": token.clone(),
                "database": data_dir.join("jobs").join("jobs.db"),
            }))?)?;
            std::fs::rename(&runtime_tmp, &runtime_file)?;

            let child_handle = Arc::new(Mutex::new(Some(child)));
            let ready = Arc::new(AtomicBool::new(false));
            tauri::async_runtime::spawn(async move {
                use tauri_plugin_shell::process::CommandEvent;
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            println!("[sidecar] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            eprintln!("[sidecar] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Terminated(status) => {
                            eprintln!("[sidecar] terminated: {:?}", status.code);
                            break;
                        }
                        _ => {}
                    }
                }
            });

            let health_token = token.clone();
            let health_child = child_handle.clone();
            let health_ready = ready.clone();
            let health_app = app.handle().clone();
            std::thread::spawn(move || {
                if wait_healthz(port, &health_token, 60) {
                    health_ready.store(true, Ordering::Release);
                } else {
                    eprintln!("sidecar healthz timeout");
                    if let Ok(mut slot) = health_child.lock() {
                        if let Some(child) = slot.take() {
                            kill_sidecar(child);
                        }
                    }
                    health_app.exit(1);
                }
            });

            app.manage(SidecarState { port, token, child: child_handle, data_dir, sidecar_path, ready, runtime_file });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if window.state::<UiState>().studio_open.swap(false, Ordering::AcqRel) {
                    api.prevent_close();
                    let _ = window.emit("atme://return-to-projects", ());
                    return;
                }
                if let Some(state) = window.app_handle().try_state::<SidecarState>() {
                    let url = format!(
                        "http://127.0.0.1:{}/shutdown",
                        state.port
                    );
                    let client = reqwest::blocking::Client::builder()
                        .timeout(std::time::Duration::from_secs(2))
                        .build()
                        .expect("shutdown HTTP client");
                    let _ = client
                        .post(&url)
                        .header("Authorization", format!("Bearer {}", state.token))
                        .send();
                    // give the sidecar a moment to exit gracefully; OS reaps on process exit
                    std::thread::sleep(std::time::Duration::from_millis(300));
                    if let Ok(mut slot) = state.child.lock() {
                        if let Some(child) = slot.take() {
                            kill_sidecar(child);
                        }
                    }
                    let _ = std::fs::remove_file(&state.runtime_file);
                    window.app_handle().exit(0);
                }
            }
        })
        .invoke_handler(tauri::generate_handler![sidecar_info, set_studio_open, import_dropped_source, mcp_connection_info, install_mcp_client, remove_mcp_client, open_artifact])
        .run(tauri::generate_context!())
        .expect("error while running ATME");
}
