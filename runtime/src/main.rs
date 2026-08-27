mod adapters;
mod capabilities;
mod client;
mod permissions;
mod protocol;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let core_url = std::env::var("APOLO_CORE_WS_URL")
        .unwrap_or_else(|_| "ws://127.0.0.1:8000/ws/runtime".to_string());
    client::run(&core_url).await
}
