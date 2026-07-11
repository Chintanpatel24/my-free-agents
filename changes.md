# Changes Log - NVIDIA NIM to Claude Code Proxy

## [2026-07-08] - Initial Stability and Performance Phase

### Rust
- Added `tokio-stream` dependency to `Cargo.toml` to fix compilation error.
- Fixed borrow checker error `E0505` in `server.rs` by converting `model_id` to owned `String`.
- **Admin UI**: Implemented `/admin` and `/admin/save` routes.
- **Static Files**: Added `ServeDir` to serve the Admin Dashboard from `assets/admin`.
- **Performance**: Enabled `tcp_nodelay` and configured connection pooling in `main.rs`.
- **State Management**: Wrapped `Config` in `Arc<Mutex<Config>>` to allow runtime updates via the Admin UI.

### C++
- Identified missing `boost_system` and `boost_thread` dependencies. (Awaiting system install).

### Planned
- Implement Async I/O engine for all languages.
- Finalize NVIDIA $\rightarrow$ Claude payload mapping.
