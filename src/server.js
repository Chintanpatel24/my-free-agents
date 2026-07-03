#!/usr/bin/env node
const express = require('express');
const axios = require('axios');
const dotenv = require('dotenv');
const cors = require('cors');
const chalk = require('chalk');

dotenv.config();

const app = express();
const PORT = process.env.PORT || 8080;
const NVIDIA_API_KEY = process.env.nvidiaapi;

if (!NVIDIA_API_KEY) {
  console.error(chalk.red('Error: nvidiaapi is not defined in .env file.'));
  process.exit(1);
}

app.use(cors());
app.use(express.json());

// Log requests
app.use((req, res, next) => {
  console.log(chalk.blue(`[${new Date().toISOString()}] ${req.method} ${req.url}`));
  next();
});

// GET /v1/models - List models available in NVIDIA NIM and map them to Claude-like structure
app.get('/v1/models', async (req, res) => {
  try {
    const response = await axios.get('https://integrate.api.nvidia.com/v1/models', {
      headers: {
        'Authorization': `Bearer ${NVIDIA_API_KEY}`,
        'Accept': 'application/json'
      }
    });

    const models = response.data.data.map(model => ({
      id: model.id,
      object: 'model',
      created: model.created || Date.now(),
      owned_by: model.owned_by || 'nvidia'
    }));

    res.json({
      object: 'list',
      data: models
    });
  } catch (error) {
    console.error(chalk.red('Error fetching models from NVIDIA:'), error.message);
    res.status(error.response?.status || 500).json({ error: error.message });
  }
});

// POST /v1/messages - Proxy Anthropic Messages API to NVIDIA NIM (OpenAI compatible)
app.post('/v1/messages', async (req, res) => {
  const { model, messages, max_tokens, stream, system, temperature, top_p } = req.body;

  console.log(chalk.green(`Using model: ${model}`));

  const openaiMessages = [];
  if (system) {
    openaiMessages.push({ role: 'system', content: system });
  }
  messages.forEach(msg => {
    let content = msg.content;
    if (Array.isArray(content)) {
      content = content.map(block => {
        if (block.type === 'text') return block.text;
        return '';
      }).join('\n');
    }
    openaiMessages.push({ role: msg.role, content: content });
  });

  const payload = {
    model: model,
    messages: openaiMessages,
    max_tokens: max_tokens || 1024,
    temperature: temperature || 0.7,
    top_p: top_p || 1,
    stream: stream || false
  };

  try {
    const nvidiaRes = await axios({
      method: 'post',
      url: 'https://integrate.api.nvidia.com/v1/chat/completions',
      data: payload,
      headers: {
        'Authorization': `Bearer ${NVIDIA_API_KEY}`,
        'Content-Type': 'application/json',
        'Accept': stream ? 'text/event-stream' : 'application/json'
      },
      responseType: stream ? 'stream' : 'json'
    });

    if (stream) {
      res.setHeader('Content-Type', 'text/event-stream');
      res.setHeader('Cache-Control', 'no-cache');
      res.setHeader('Connection', 'keep-alive');

      let buffer = '';
      nvidiaRes.data.on('data', (chunk) => {
        buffer += chunk.toString();
        const lines = buffer.split('\n');
        buffer = lines.pop(); // Keep the last partial line in the buffer

        for (const line of lines) {
          const trimmedLine = line.trim();
          if (!trimmedLine) continue;

          if (trimmedLine.startsWith('data: ')) {
            const dataStr = trimmedLine.slice(6);
            if (dataStr === '[DONE]') {
              res.write('data: {"type": "message_stop"}\n\n');
              continue;
            }
            try {
              const data = JSON.parse(dataStr);
              const content = data.choices[0]?.delta?.content || '';
              if (content) {
                const anthropicChunk = {
                  type: 'content_block_delta',
                  index: 0,
                  delta: {
                    type: 'text_delta',
                    text: content
                  }
                };
                res.write(`data: ${JSON.stringify(anthropicChunk)}\n\n`);
              }
            } catch (e) {
              // If JSON parsing fails, it might still be a partial line
              // that didn't get caught by pop() if it didn't end with \n
              // but we are splitting by \n so it should be fine.
            }
          }
        }
      });

      nvidiaRes.data.on('end', () => {
        res.end();
      });
    } else {
      const anthropicResponse = {
        id: nvidiaRes.data.id,
        type: 'message',
        role: 'assistant',
        model: model,
        content: [
          {
            type: 'text',
            text: nvidiaRes.data.choices[0].message.content
          }
        ],
        stop_reason: nvidiaRes.data.choices[0].finish_reason === 'stop' ? 'end_turn' : nvidiaRes.data.choices[0].finish_reason,
        usage: {
          input_tokens: nvidiaRes.data.usage?.prompt_tokens || 0,
          output_tokens: nvidiaRes.data.usage?.completion_tokens || 0
        }
      };
      res.json(anthropicResponse);
    }
  } catch (error) {
    console.error(chalk.red('Error calling NVIDIA NIM:'), error.response?.data || error.message);
    res.status(error.response?.status || 500).json({ error: error.message });
  }
});

app.listen(PORT, () => {
  console.log(chalk.green(`
🚀 Proxy Server started!
📍 URL: http://localhost:${PORT}
  `));
});
