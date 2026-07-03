<div align=center>
   
<img src="assets/free-claudecode.svg" alt="Logo" width="200"/>   

</div>

# ***my-free-claudecode***
- Use **Claude Code** with **NVIDIA NIM** models for free (using your NVIDIA NIM API key). This project provides a local proxy that translates Claude Code requests into NVIDIA NIM API calls.

<div align=center>
<image src="assets/working-fine.png" alt="claudecode-woring-image">
</div>
   
## Features

- **NVIDIA NIM Support**: Use any model available in the NVIDIA NIM API.
- **Auto-Config**: Installation script asks for your API key and sets everything up.
- **Model Selection**: Shows all NVIDIA NIM models directly in Claude Code via `/models`.
- **Default GLM**: Uses GLM 5.1 as the default model for a smooth experience.
- **Local Proxy**: Runs a lightweight server at `http://127.0.0.1:2424`.

## Installation

### Linux/MacOS
Run the following command in your terminal:
```bash
curl -fsSL https://raw.githubusercontent.com/Chintanpatel24/my-free-claudecode/main/install.sh | bash
```

### Windows (PowerShell)
Run the following command in PowerShell:
```powershell
irm https://raw.githubusercontent.com/Chintanpatel24/my-free-claudecode/main/install.ps1 | iex
```

### Python (pip)
Alternatively, you can install it as a Python package:
```bash
pip install git+https://github.com/Chintanpatel24/my-free-claudecode.git
```

## Update

To update to the latest version, run the following command:

### macOS / Linux
```bash
curl -fsSL https://raw.githubusercontent.com/Chintanpatel24/my-free-claudecode/main/update.sh | bash
```

### Windows (PowerShell)
```powershell
irm https://raw.githubusercontent.com/Chintanpatel24/my-free-claudecode/main/update.ps1 | iex
```

## How to Use

1. **Start the Proxy Server**:
   ```bash
   my-server-claudecode
   ```
2. **Launch Claude Code**:
   In a new terminal window, run:
   ```bash
   my-claudecode
   ```
3. **Select a Model**:
   Inside Claude Code, you can use the `/models` command to see and select from 100+ NVIDIA NIM models.

## Configuration

If you need to change your API key later, you can:
- Edit the `.env` file located at `~/.free-claude-code/app/.env` (Linux/Mac) or `%USERPROFILE%\.free-claude-code\app\.env` (Windows).
- Use the Admin UI at `http://127.0.0.1:2424/admin` while the server is running.
- Set it via command line:
  ```bash
  my-server-claudecode --set-key your-nvapi-key
  ```
