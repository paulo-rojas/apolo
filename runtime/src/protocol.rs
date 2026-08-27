use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const PROTOCOL_VERSION: &str = "0.1";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceInfo {
    pub id: String,
    pub name: String,
    pub platform: String,
    pub capabilities: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum RuntimeMessage {
    #[serde(rename = "device.register")]
    DeviceRegister {
        protocol_version: String,
        request_id: String,
        device: DeviceInfo,
    },
    #[serde(rename = "device.registered")]
    DeviceRegistered {
        protocol_version: String,
        request_id: String,
        device_id: String,
        ok: bool,
    },
    #[serde(rename = "device.heartbeat")]
    DeviceHeartbeat {
        protocol_version: String,
        request_id: String,
        device_id: String,
    },
    #[serde(rename = "tool.execute")]
    ToolExecute {
        protocol_version: String,
        request_id: String,
        tool: String,
        #[serde(default)]
        args: Value,
    },
    #[serde(rename = "tool.result")]
    ToolResult {
        protocol_version: String,
        request_id: String,
        ok: bool,
        #[serde(skip_serializing_if = "Option::is_none")]
        result: Option<Value>,
        #[serde(skip_serializing_if = "Option::is_none")]
        error: Option<String>,
    },
    #[serde(rename = "error")]
    Error {
        protocol_version: String,
        request_id: String,
        error: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        code: Option<String>,
    },
}

impl RuntimeMessage {
    pub fn register(request_id: String, device: DeviceInfo) -> Self {
        Self::DeviceRegister {
            protocol_version: PROTOCOL_VERSION.to_string(),
            request_id,
            device,
        }
    }

    pub fn heartbeat(request_id: String, device_id: String) -> Self {
        Self::DeviceHeartbeat {
            protocol_version: PROTOCOL_VERSION.to_string(),
            request_id,
            device_id,
        }
    }

    pub fn result(request_id: String, result: anyhow::Result<Value>) -> Self {
        match result {
            Ok(value) => Self::ToolResult {
                protocol_version: PROTOCOL_VERSION.to_string(),
                request_id,
                ok: true,
                result: Some(value),
                error: None,
            },
            Err(error) => Self::ToolResult {
                protocol_version: PROTOCOL_VERSION.to_string(),
                request_id,
                ok: false,
                result: None,
                error: Some(error.to_string()),
            },
        }
    }
}
