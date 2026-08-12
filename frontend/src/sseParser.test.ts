import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SSEParser } from './sseParser.ts';

test('parses full frame correctly', () => {
  const parser = new SSEParser();
  const chunk = 'event: stage\ndata: {"stage":"planning","message":"설계 중"}\n\n';
  const events = Array.from(parser.parseChunk(chunk));
  assert.equal(events.length, 1);
  assert.equal(events[0].event, 'stage');
  assert.equal(events[0].data.stage, 'planning');
});

test('handles chunk boundaries splitting a frame', () => {
  const parser = new SSEParser();
  const chunk1 = 'event: to';
  const chunk2 = 'ken\ndata: {"text":"hel';
  const chunk3 = 'lo"}\n\n';
  
  let events = Array.from(parser.parseChunk(chunk1));
  assert.equal(events.length, 0);
  
  events = Array.from(parser.parseChunk(chunk2));
  assert.equal(events.length, 0);
  
  events = Array.from(parser.parseChunk(chunk3));
  assert.equal(events.length, 1);
  assert.equal(events[0].event, 'token');
  assert.equal(events[0].data.text, 'hello');
});

test('handles chunk boundaries splitting across frames', () => {
  const parser = new SSEParser();
  const chunk = 'event: token\ndata: {"text":"1"}\n\nevent: token\ndata: {"text":"2"}\n\nevent: to';
  const events = Array.from(parser.parseChunk(chunk));
  assert.equal(events.length, 2);
  assert.equal(events[0].data.text, '1');
  assert.equal(events[1].data.text, '2');
  
  const chunk2 = 'ken\ndata: {"text":"3"}\n\n';
  const events2 = Array.from(parser.parseChunk(chunk2));
  assert.equal(events2.length, 1);
  assert.equal(events2[0].data.text, '3');
});
