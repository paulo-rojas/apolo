use anyhow::{anyhow, Result};
use serde_json::{json, Value};
use tokio::process::Command;

pub async fn execute(tool: &str, args: &Value) -> Result<Value> {
    match tool {
        "system.info" => Ok(system_info()),
        "system.open_app" => open_app(args).await,
        "system.close_app" => close_app(args).await,
        _ => Err(anyhow!("unsupported system capability: {tool}")),
    }
}

fn system_info() -> Value {
    json!({
        "ok": true,
        "hostname": hostname::get().ok().and_then(|name| name.into_string().ok()),
        "platform": std::env::consts::OS,
        "architecture": std::env::consts::ARCH,
        "family": std::env::consts::FAMILY
    })
}

async fn open_app(args: &Value) -> Result<Value> {
    let name = app_name(args)?;
    #[cfg(target_os = "windows")]
    {
        Command::new("cmd")
            .args(["/C", "start", "", &name])
            .spawn()?;
        return Ok(json!({"ok": true, "app": name}));
    }
    #[cfg(target_os = "macos")]
    {
        Command::new("open").arg("-a").arg(&name).spawn()?;
        return Ok(json!({"ok": true, "app": name}));
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        Command::new("gtk-launch").arg(&name).spawn()?;
        return Ok(json!({"ok": true, "app": name}));
    }
}

async fn close_app(args: &Value) -> Result<Value> {
    let name = app_name(args)?;
    #[cfg(target_os = "windows")]
    {
        let status = Command::new("taskkill")
            .args(["/IM", &format!("{name}.exe"), "/T"])
            .status()
            .await?;
        return Ok(json!({"ok": status.success(), "app": name}));
    }
    #[cfg(not(target_os = "windows"))]
    {
        let status = Command::new("pkill").arg(&name).status().await?;
        return Ok(json!({"ok": status.success(), "app": name}));
    }
}

fn app_name(args: &Value) -> Result<String> {
    let value = args
        .get("name")
        .or_else(|| args.get("app"))
        .or_else(|| args.get("application"))
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim();
    if value.is_empty() || value.chars().any(|ch| matches!(ch, '\\' | '/' | '&' | '|' | ';')) {
        return Err(anyhow!("invalid app name"));
    }
    Ok(value.to_string())
}
