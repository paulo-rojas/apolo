use crate::protocol::DeviceInfo;

pub fn local_device() -> DeviceInfo {
    let hostname = hostname::get()
        .ok()
        .and_then(|name| name.into_string().ok())
        .unwrap_or_else(|| "apolo-runtime".to_string());
    DeviceInfo {
        id: format!("{}-{}", hostname.to_lowercase(), std::env::consts::OS),
        name: hostname,
        platform: std::env::consts::OS.to_string(),
        capabilities: allowed_capabilities(),
    }
}

pub fn allowed_capabilities() -> Vec<String> {
    vec![
        "system.info".to_string(),
        "system.open_app".to_string(),
        "system.close_app".to_string(),
    ]
}
