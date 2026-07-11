<div align=center>
   
<img src="assets/free-claudecode.svg" alt="Logo" width="200"/>   

</div>

>[!IMPORTANT]
>I am making a direct experiment on the `main` branch for some reasons, so if you want to use that, just download the latest release `1.0.2` or the `version 1.0.0` zip and install it with the scripts. and use it 

# ***my-free-claudecode***
- Use **Claude Code** with **NVIDIA NIM** models for free (using your NVIDIA NIM API key). This project provides a local proxy that translates Claude Code requests into NVIDIA NIM API calls.

## High-Performance Multi-Server Architecture

Choose the best engine for your needs:

| Engine | Benefit | Ideal For |
| :--- | :--- | :--- |
| **Python** | Compatibility | Best for rapid development and full feature support. |
| **Go** | Concurrency | High-throughput streaming with low memory footprint. |
| **Rust** | Safety & Speed | Maximum memory safety and consistent high performance. |
| **C++** | Latency | Ultra-low latency and bare-metal execution speed. |

>[!NOTE]
>- You must install CloudCode first, and then only should you install this proxy.
<div align=center>
<image src="assets/working-fine.png" alt="claudecode-woring-image">
</div>

## How It Works
>Here is the detailed high-performance multi-server proxy architecture showing how requests flow, translate, and stream between Claude Code and the NVIDIA NIM APIs:

```mermaid
graph TD
    %% Define styles and classes
    classDef client fill:#d1e7dd,stroke:#0f5132,stroke-width:2px;
    classDef proxy fill:#cff4fc,stroke:#087990,stroke-width:2px;
    classDef upstream fill:#f8d7da,stroke:#842029,stroke-width:2px;
    classDef storage fill:#fff3cd,stroke:#664d03,stroke-width:2px;

    subgraph ClientSpace ["User Space & Client"]
        User(["User / Developer"]) -->|runs| CC["Claude Code CLI<br>(my-claudecode)"]
        CC -->|Env Vars Set:<br>ANTHROPIC_BASE_URL=http://localhost:2424/v1| CC
    end

    subgraph ProxySpace ["Local Proxy Architecture (Port: 2424)"]
        PS{"Proxy Engines<br>(Selectable)"}:::proxy
        PyProxy["Python Proxy<br>(FastAPI/Uvicorn)"]:::proxy
        GoProxy["Go Proxy<br>(fasthttp)"]:::proxy
        RustProxy["Rust Proxy<br>(axum/tokio)"]:::proxy
        CppProxy["C++ Proxy<br>(Boost.Beast)"]:::proxy

        PS --- PyProxy
        PS --- GoProxy
        PS --- RustProxy
        PS --- CppProxy

        AdminUI["Admin Control Panel<br>(localhost:2424/admin)"]:::proxy

        subgraph Logic ["Request Handling & Translation Core"]
            LocalCheck{"Is Local Fast Greeting?<br>(FREE_AGENTS_LOCAL_GREETINGS=1)"}
            LocalGreet["Instant Local Response<br>('Hi! I am ready.')"]

            PayloadTranslate["Payload Translation<br>(build_openai_request)"]
            ToolMap["Bidirectional Tool Use Mapping<br>(Anthropic Messages <-> OpenAI)"]
            ModelMap["Selected Model Resolution<br>(Meta/Mistral/DeepSeek/etc.)"]
        end
    end

    subgraph ConfigSpace ["Configuration & Storage"]
        EnvFile[".env File<br>(NVIDIA_NIM_API key)"]:::storage
        SettingsFile["settings.json<br>(Configured Models/State)"]:::storage
    end

    subgraph UpstreamSpace ["NVIDIA NIM Global Upstream"]
        NimAPI["NVIDIA NIM API Gateway<br>(integrate.api.nvidia.com)"]:::upstream
        NimModels["NVIDIA NIM Models<br>(Llama-3.3-70b / Nemotron / etc.)"]:::upstream
    end

    %% Flow connections
    CC -->|1. HTTP /v1/messages| PS
    PS -->|Read Config| EnvFile
    PS -->|Read Settings| SettingsFile

    AdminUI -->|Update Keys/Models| EnvFile
    AdminUI -->|Update Preferences| SettingsFile
    AdminUI -.->|Test Connection| NimAPI

    %% Execution flow within Logic
    PyProxy & GoProxy & RustProxy & CppProxy --> LocalCheck

    LocalCheck -->|Yes: e.g. 'hi'| LocalGreet
    LocalGreet -->|Instant Response| CC

    LocalCheck -->|No| PayloadTranslate
    PayloadTranslate --> ToolMap
    ToolMap --> ModelMap

    ModelMap -->|2. Forward translated request| NimAPI
    NimAPI -->|Processes request| NimModels

    %% Stream & Response backflow
    NimModels -->|3. Streaming chunks (OpenAI SSE)| NimAPI
    NimAPI -->|Forward SSE Stream| PS

    subgraph ResponseLogic ["Response Mapping Engine"]
        SSEParser["High-Performance SSE Parser"]
        ResponseTranslate["Payload Mapping<br>(openai_to_anthropic)"]
    end

    PS --> SSEParser
    SSEParser --> ResponseTranslate
    ResponseTranslate -->|4. Chunked Anthropic Events| CC
    CC -->|5. Real-time Typing Effect| User
```

<!-- ## Table of contents

- [Providers](#Providers)
- [Installation](#Installation)
- [Installation using pip](#Installation-using-pip)
- [Update](#Update)
- [How to Use](#How-to-Use)
- [Configuration](#Configuration) -->

<a name="Providers"></a>
## Providers
>[!NOTE]
>Currently this project only uses the `NVIDIA NIM API` only; other providers will be added in the future.
- [**NVIDIA NIM**](https://build.nvidia.com/explore/discover)

---

<a name="Installation"></a>
## Installation

### Linux/MacOS
Run the following command in your terminal:
```bash
curl -fsSL https://raw.githubusercontent.com/Chintanpatel24/my-free-agents/main/install.sh | bash
```

### Windows (PowerShell)
Run the following command in PowerShell:
```powershell
irm https://raw.githubusercontent.com/Chintanpatel24/my-free-agents/main/install.ps1 | iex
```

<a name="Installation-using-pip"></a>
### Python (pip)
Alternatively, you can install it as a Python package:
```bash
pip install git+https://github.com/Chintanpatel24/my-free-agents.git
```

---

<a name="Update"></a>
## Update

To update to the latest version, run the following command:

### macOS / Linux
```bash
curl -fsSL https://raw.githubusercontent.com/Chintanpatel24/my-free-agents/main/update.sh | bash
```

### Windows (PowerShell)
```powershell
irm https://raw.githubusercontent.com/Chintanpatel24/my-free-agents/main/update.ps1 | iex
```

---

<a name="How-to-Use"></a>
## How to Use

1. **Choose and Install Your Proxy Server**:
   Run the new installation script to select your preferred high-performance engine:
   ```bash
   bash install_server.sh
   ```
   *Engines available:*
   - **Python (Default)**: Best compatibility, uses FastAPI + Uvicorn.
   - **Go**: Ultra-fast, low memory usage with `fasthttp`.
   - **Rust**: Maximum performance and safety with `axum` + `tokio`.
   - **C++**: Lowest possible latency with `Boost.Beast`.

2. **Start the Proxy Server**:
   Depending on your choice:
   ```bash
   # If you chose Python
   start-claudecode-server

   # If you chose Go
   ./bin/go-proxy

   # If you chose Rust
   ./bin/rust-proxy

   # If you chose C++
   ./bin/cpp-proxy
   ```
   The server uses a fast NVIDIA NIM default model (`meta/llama-3.1-8b-instruct`) so Claude Code can start immediately. You can change it any time in the Admin UI.
2. **Launch Claude Code**:
   In a new terminal window, run:
   ```bash
   my-claudecode
   ```
3. **Select a Model**:
   - Inside the terminal in which you host that `server`, open the `admin panel` and configure a `model` and check a connection.
     <details>
        <summary>Admin panel</summary>
        <p><image src="assets/admin.png" width="300"></p>
     </details>
   - Select the selected model from the /model command in the claudecode (which is launched with the my-claudcode command (while server it running in background))
     <details>
        <summary>/models</summary>
        <p><image src="assets/model.png" width="300"></p>
     </details>

---

<a name="Configuration"></a>
## Configuration

If you need to change your API key later, you can:
- Edit the `.env` file located at `~/.my-free-agents/claudecode/.env` (Linux/Mac) or `%USERPROFILE%\.my-free-agents\claudecode\.env` (Windows).
- Use the Admin UI at `http://127.0.0.1:2424/admin` while the server is running.
- Set it via command line:
  ```bash
  start-claudecode-server --set-key your-nvapi-key
  ```

### Performance options

The proxy uses HTTP/1.1 by default because it is the most reliable path for NVIDIA NIM from local Python installs. HTTP/2 is still available if your environment handles it well:

```bash
NVIDIA_NIM_HTTP2=1 start-claudecode-server
```

Useful optional settings:

- `NVIDIA_NIM_RETRIES=2` retries short non-streaming upstream failures.
- `NVIDIA_NIM_STREAM_RETRIES=1` retries a stream only before any response bytes are sent.
- `NVIDIA_NIM_INCLUDE_PUBLIC_CATALOG=1` adds NVIDIA's public catalog to `/models`; disabled by default for faster startup and model refresh.
- `FREE_AGENTS_LOCAL_GREETINGS=1` replies locally to tiny greetings like `hi`, so the quick health-check prompt answers instantly.

Streaming responses send the Anthropic `message_start` event immediately, before waiting for NVIDIA, so Claude Code should not look frozen while the upstream model is warming up.
