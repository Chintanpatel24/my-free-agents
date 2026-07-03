#!/usr/bin/env node

import { spawn, execSync } from 'child_process';
import readline from 'readline';
import fs from 'fs';
import path from 'path';
import dotenv from 'dotenv';

function checkClaudeInstalled() {
  try {
    execSync('claude --version', { stdio: 'ignore' });
    return true;
  } catch (e) {
    return false;
  }
}

async function askToInstall() {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
  });

  return new Promise((resolve) => {
    rl.question('Claude Code is not installed. Do you want to install it now? (y/n): ', (answer) => {
      rl.close();
      resolve(answer.toLowerCase() === 'y');
    });
  });
}

async function main() {
  if (!checkClaudeInstalled()) {
    const shouldInstall = await askToInstall();
    if (shouldInstall) {
      console.log('Installing @anthropic-ai/claude-code globally...');
      try {
        execSync('npm install -g @anthropic-ai/claude-code', { stdio: 'inherit' });
      } catch (e) {
        console.error('Failed to install Claude Code. Please install it manually with: npm install -g @anthropic-ai/claude-code');
        process.exit(1);
      }
    } else {
      console.log('Claude Code must be in the system to continue.');
      process.exit(1);
    }
  }

  // Load .env
  dotenv.config();
  const nvidiaApiKey = process.env.nvidiaapi;

  if (!nvidiaApiKey) {
    console.error('Error: nvidiaapi not found in .env or environment.');
    console.log('Please add nvidiaapi=your_nvapi_key to your .env file.');
    process.exit(1);
  }

  console.log('🚀 Launching Claude Code with NVIDIA NIM Proxy...');
  console.log('Using Proxy: http://localhost:2424/v1');

  const env = {
    ...process.env,
    ANTHROPIC_BASE_URL: 'http://localhost:2424/v1',
    ANTHROPIC_API_KEY: 'sk-ant-proxy-dummy-key-to-bypass-validation',
  };

  const claude = spawn('claude', process.argv.slice(2), {
    env,
    stdio: 'inherit',
    shell: true
  });

  claude.on('exit', (code) => {
    process.exit(code || 0);
  });
}

main();
