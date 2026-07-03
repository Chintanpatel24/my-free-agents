#!/usr/bin/env node

import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';

dotenv.config();

const app = express();
app.use(cors());
app.use(express.json({ limit: '50mb' }));

const PORT = process.env.PORT || 2424;
const NVIDIA_API_KEY = process.env.nvidiaapi;
const NVIDIA_BASE_URL = 'https://integrate.api.nvidia.com/v1';

if (!NVIDIA_API_KEY) {
  console.warn('Warning: nvidiaapi not found in environment');
}

// Map Anthropic messages to OpenAI format
function mapAnthropicToOpenAI(messages, system) {
  const result = [];
  if (system) {
    result.push({ role: 'system', content: system });
  }

  for (const msg of messages) {
    if (typeof msg.content === 'string') {
      result.push({ role: msg.role, content: msg.content });
    } else if (Array.isArray(msg.content)) {
      const contentBlocks = [];
      const toolCalls = [];

      for (const block of msg.content) {
        if (block.type === 'text') {
          contentBlocks.push(block.text);
        } else if (block.type === 'tool_use') {
          toolCalls.push({
            id: block.id,
            type: 'function',
            function: {
              name: block.name,
              arguments: JSON.stringify(block.input)
            }
          });
        } else if (block.type === 'tool_result') {
           result.push({
             role: 'tool',
             tool_call_id: block.tool_use_id,
             content: typeof block.content === 'string' ? block.content : JSON.stringify(block.content)
           });
        }
      }

      if (contentBlocks.length > 0 || toolCalls.length > 0) {
        const message = { role: msg.role, content: contentBlocks.join('\n') || null };
        if (toolCalls.length > 0) {
          message.tool_calls = toolCalls;
        }
        result.push(message);
      }
    }
  }
  return result;
}

app.post('/v1/messages', async (req, res) => {
  const { model, messages, system, stream, max_tokens, temperature, tools, stop_sequences } = req.body;

  const openaiMessages = mapAnthropicToOpenAI(messages, system);
  const payload = {
    model,
    messages: openaiMessages,
    max_tokens: max_tokens || 4096,
    temperature: temperature ?? 0.7,
    stream: stream || false,
  };

  if (tools) {
    payload.tools = tools.map(t => ({
      type: 'function',
      function: {
        name: t.name,
        description: t.description,
        parameters: t.input_schema
      }
    }));
  }

  if (stop_sequences) {
    payload.stop = stop_sequences;
  }

  try {
    const response = await fetch(`${NVIDIA_BASE_URL}/chat/completions`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${NVIDIA_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const err = await response.text();
      return res.status(response.status).send(err);
    }

    if (stream) {
      res.setHeader('Content-Type', 'text/event-stream');
      res.write('event: message_start\ndata: {"type": "message_start", "message": {"id": "msg_' + Date.now() + '", "role": "assistant", "content": [], "model": "' + model + '"}}\n\n');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let currentToolCallIndex = -1;
      let toolCallStarted = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6).trim();
            if (dataStr === '[DONE]') continue;

            try {
              const data = JSON.parse(dataStr);
              const delta = data.choices[0].delta;

              // Text content
              if (delta.content) {
                if (currentToolCallIndex === -1 && !toolCallStarted) {
                   // Ensure we have a content block for text
                }
                res.write(`event: content_block_delta\ndata: ${JSON.stringify({
                  type: 'content_block_delta',
                  index: 0,
                  delta: { type: 'text_delta', text: delta.content }
                })}\n\n`);
              }

              // Tool calls
              if (delta.tool_calls) {
                for (const tc of delta.tool_calls) {
                  const index = tc.index;
                  if (tc.function?.name) {
                    // New tool call starts
                    res.write(`event: content_block_start\ndata: ${JSON.stringify({
                      type: 'content_block_start',
                      index: index + 1, // Assume text is index 0
                      content_block: { type: 'tool_use', id: tc.id, name: tc.function.name, input: {} }
                    })}\n\n`);
                  }

                  if (tc.function?.arguments) {
                    res.write(`event: content_block_delta\ndata: ${JSON.stringify({
                      type: 'content_block_delta',
                      index: index + 1,
                      delta: { type: 'input_json_delta', partial_json: tc.function.arguments }
                    })}\n\n`);
                  }
                }
              }
            } catch (e) {}
          }
        }
      }
      res.write('event: message_stop\ndata: {"type": "message_stop"}\n\n');
      res.end();
    } else {
      const data = await response.json();
      const choice = data.choices[0];
      const content = [];

      if (choice.message.content) {
        content.push({ type: 'text', text: choice.message.content });
      }

      if (choice.message.tool_calls) {
        content.push(...choice.message.tool_calls.map(tc => ({
          type: 'tool_use',
          id: tc.id,
          name: tc.function.name,
          input: JSON.parse(tc.function.arguments || '{}')
        })));
      }

      res.json({
        id: data.id,
        type: 'message',
        role: 'assistant',
        content,
        model: model,
        stop_reason: choice.finish_reason === 'tool_calls' ? 'tool_use' : 'end_turn',
        usage: {
          input_tokens: data.usage?.prompt_tokens || 0,
          output_tokens: data.usage?.completion_tokens || 0
        }
      });
    }
  } catch (error) {
    console.error('Proxy Error:', error);
    res.status(500).json({ error: error.message });
  }
});

app.get('/v1/models', async (req, res) => {
  try {
    const response = await fetch(`${NVIDIA_BASE_URL}/models`, {
      headers: { 'Authorization': `Bearer ${NVIDIA_API_KEY}` }
    });
    const data = await response.json();
    // Return in Anthropic-like format
    res.json({
      data: data.data.map(m => ({
        id: m.id,
        type: 'model',
        display_name: m.id,
        created_at: m.created
      }))
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.listen(PORT, () => {
  console.log(`Proxy server running on http://localhost:${PORT}`);
});
