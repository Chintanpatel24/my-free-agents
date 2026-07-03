# my-free-claudecode

Use Claude Code for free using NVIDIA NIM API! This project provides a proxy server that translates Anthropic API requests from Claude Code to NVIDIA NIM's OpenAI-compatible API.

## Features
- Use any model available in NVIDIA NIM (Llama, Mistral, etc.) inside Claude Code.
- Works with `/model` command in Claude Code to switch between NVIDIA models.
- Transparently handles streaming and non-streaming responses.
- Easy to set up and use.

## Prerequisites
1. **Claude Code**: Ensure you have the official Claude Code CLI installed.
   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   ```
2. **NVIDIA NIM API Key**: Get your free developer API key from [NVIDIA NIM](https://build.nvidia.com/).

## Installation
1. Clone this repository or download the source.
2. Install dependencies:
   ```bash
   npm install
   ```
3. Create a `.env` file in the project root:
   ```bash
   cp .env.example .env
   ```
4. Open `.env` and add your NVIDIA API key:
   ```text
   nvidiaapi=nvapi-A7A...
   ```
5. (Optional) Link the commands globally:
   ```bash
   npm link
   ```

## Usage

### 1. Start the Proxy Server
In one terminal, start the proxy server:
```bash
my-claudecode-server
```
*(If not linked globally, use `node src/server.js`)*

### 2. Launch Claude Code
In another terminal (or the same, if running in background), launch the modified Claude Code:
```bash
my-claudecode
```
*(If not linked globally, use `node src/cli.js`)*

### 3. Switch Models
Once inside Claude Code, you can see all available NVIDIA models by typing:
```text
/model
```
Select any model from the list to start using it!

## How it works
`my-claudecode` launches the official `claude` CLI but overrides the `ANTHROPIC_BASE_URL` to point to our local proxy. The proxy handles the authentication using your NVIDIA key and translates the request format on the fly.
