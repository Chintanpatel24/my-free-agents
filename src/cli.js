#!/usr/bin/env node
const { spawn, execSync } = require('child_process');
const chalk = require('chalk');
const path = require('path');
const fs = require('fs');

function isClaudeInstalled() {
  try {
    execSync('claude --version', { stdio: 'ignore' });
    return true;
  } catch (e) {
    return false;
  }
}

if (!isClaudeInstalled()) {
  console.log(chalk.yellow('Official Claude Code is not installed.'));
  console.log('Please install it first using:');
  console.log(chalk.cyan('curl -fsSL https://claude.ai/install.sh | bash'));
  console.log('Or visit https://code.claude.com for more instructions.');
  process.exit(1);
}

console.log(chalk.green('🚀 Launching Claude Code with NVIDIA NIM Proxy...'));

// Set the base URL and a dummy key to bypass local checks if any
const env = {
  ...process.env,
  ANTHROPIC_BASE_URL: 'http://localhost:8080/v1',
  ANTHROPIC_API_KEY: 'sk-ant-dummy-key-for-proxy-use'
};

const claude = spawn('claude', process.argv.slice(2), {
  stdio: 'inherit',
  env: env,
  shell: true
});

claude.on('exit', (code) => {
  process.exit(code);
});
