use std::time::Duration;

use anyhow::{anyhow, Result};
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use uuid::Uuid;

use crate::adapters::system;
use crate::capabilities::local_device;
use crate::permissions::PermissionSet;
use crate::protocol::RuntimeMessage;

pub async fn run(core_url: &str) -> Result<()> {
    loop {
        if let Err(error) = connect_once(core_url).await {
            eprintln!("apolo-runtime: disconnected: {error}");
            tokio::time::sleep(Duration::from_secs(2)).await;
        }
    }
}

async fn connect_once(core_url: &str) -> Result<()> {
    let device = local_device();
    let permissions = PermissionSet::new(&device.capabilities);
    let device_id = device.id.clone();
    let (socket, _) = connect_async(core_url).await?;
    let (mut write, mut read) = socket.split();
    let register = RuntimeMessage::register(Uuid::new_v4().to_string(), device);
    write.send(Message::Text(serde_json::to_string(&register)?)).await?;

    let mut heartbeat = tokio::time::interval(Duration::from_secs(15));
    loop {
        tokio::select! {
            _ = heartbeat.tick() => {
                let message = RuntimeMessage::heartbeat(Uuid::new_v4().to_string(), device_id.clone());
                write.send(Message::Text(serde_json::to_string(&message)?)).await?;
            }
            incoming = read.next() => {
                let Some(incoming) = incoming else {
                    return Err(anyhow!("connection closed"));
                };
                let incoming = incoming?;
                if !incoming.is_text() {
                    continue;
                }
                let message: RuntimeMessage = serde_json::from_str(incoming.to_text()?)?;
                if let RuntimeMessage::ToolExecute { request_id, tool, args, .. } = message {
                    let result = if permissions.allows(&tool) {
                        system::execute(&tool, &args).await
                    } else {
                        Err(anyhow!("capability denied: {tool}"))
                    };
                    let response = RuntimeMessage::result(request_id, result);
                    write.send(Message::Text(serde_json::to_string(&response)?)).await?;
                }
            }
        }
    }
}
