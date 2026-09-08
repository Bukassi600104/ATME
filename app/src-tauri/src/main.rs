#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use rand::Rng;
use std::net::TcpListener;
use std::path::PathBuf;
use std::sync::{atomic::{AtomicBool, Ordering}, Arc, Mutex};
use tauri::Manager;

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

#[tauri::command]
fn sidecar_info(state: tauri::State<SidecarState>) -> serde_json::Value {
    serde_json::json!({
        "port": state.port,
        "token": state.token,
        "ready": state.ready.load(Ordering::Acquire),
    })
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
    ready: Arc<AtomicBool>,
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
        .setup(move |app| {
            use tauri_plugin_shell::ShellExt;

            let data_dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&data_dir)?;
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

            app.manage(SidecarState { port, token, child: child_handle, data_dir, ready });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
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
                    window.app_handle().exit(0);
                }
            }
        })
        .invoke_handler(tauri::generate_handler![sidecar_info, open_artifact])
        .run(tauri::generate_context!())
        .expect("error while running ATME");
}
