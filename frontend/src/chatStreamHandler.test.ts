import { test } from 'node:test';
import assert from 'node:assert/strict';
import { processChatStream, buildChatRequestBody } from './chatStreamHandler.ts';

// Mock stream reader
class MockReader implements ReadableStreamDefaultReader<Uint8Array> {
  private chunks: Uint8Array[];
  private errorToThrow?: Error;
  closed: Promise<undefined>;

  constructor(chunks: string[], errorToThrow?: Error) {
    this.chunks = chunks.map(c => new TextEncoder().encode(c));
    this.errorToThrow = errorToThrow;
    this.closed = Promise.resolve(undefined);
  }

  async read(): Promise<ReadableStreamReadResult<Uint8Array>> {
    if (this.errorToThrow) {
      const err = this.errorToThrow;
      this.errorToThrow = undefined; // throw once
      throw err;
    }
    if (this.chunks.length === 0) {
      return { done: true, value: undefined };
    }
    return { done: false, value: this.chunks.shift()! };
  }

  cancel(reason?: any): Promise<void> {
    return Promise.resolve();
  }
  releaseLock(): void {}
}

const createMockCallbacks = (): any & { calls: Record<string, any[]> } => {
  const calls: Record<string, any[]> = {
    onStage: [], onDocs: [], onToken: [], onFinal: [], onError: [],
    onAbort: [], onNetworkError: [], onUnexpectedEnd: [], onComplete: []
  };
  return {
    calls,
    onStage: (s, m) => calls.onStage.push({ s, m }),
    onDocs: (d) => calls.onDocs.push({ d }),
    onToken: (t) => calls.onToken.push({ t }),
    onFinal: (a, d, v, s) => calls.onFinal.push({ a, d, v, s }),
    onError: (m, t) => calls.onError.push({ m, t }),
    onAbort: () => calls.onAbort.push({}),
    onNetworkError: (m) => calls.onNetworkError.push({ m }),
    onUnexpectedEnd: (a) => calls.onUnexpectedEnd.push({ a }),
    onComplete: () => calls.onComplete.push({}),
  };
};

test('buildChatRequestBody - pure function constructs correct JSON body with session_key', () => {
  // sessionKey가 없을 때 session_key: null
  const body1 = buildChatRequestBody(' 입찰가 예측 문의드립니다. ');
  assert.deepEqual(body1, {
    message: '입찰가 예측 문의드립니다.',
    session_key: null,
  });

  // next session_key가 제공되었을 때 요청 바디에 세션 키 포함
  const body2 = buildChatRequestBody('다음 질문입니다', 'session_abc123');
  assert.deepEqual(body2, {
    message: '다음 질문입니다',
    session_key: 'session_abc123',
  });

  // sessionKey가 빈 문자열/공백일 때 session_key: null
  const body3 = buildChatRequestBody('질문', '   ');
  assert.deepEqual(body3, {
    message: '질문',
    session_key: null,
  });
});

test('processChatStream - successful flow with token accumulation and final answer replacement', async () => {
  const cb = createMockCallbacks();
  const reader = new MockReader([
    'event: stage\ndata: {"stage":"planning","message":"설계"}\n\n',
    'event: token\ndata: {"text":"hello"}\n\n',
    'event: token\ndata: {"text":" world"}\n\n',
    'event: final\ndata: {"answer":"final answer","session_key":"sk_123","visualizations":{"type":"bar"}}\n\n'
  ]);

  await processChatStream(reader, cb);

  assert.equal(cb.calls.onStage.length, 1);
  assert.equal(cb.calls.onToken.length, 2);
  assert.equal(cb.calls.onToken[1].t, 'hello world');
  assert.equal(cb.calls.onFinal.length, 1);
  assert.equal(cb.calls.onFinal[0].a, 'final answer'); // token is replaced
  assert.equal(cb.calls.onFinal[0].s, 'sk_123'); // session_key passed
  assert.deepEqual(cb.calls.onFinal[0].v, { type: 'bar' });
  assert.equal(cb.calls.onComplete.length, 1);
});

test('processChatStream - handles unexpected EOF with incomplete answer indicator', async () => {
  const cb = createMockCallbacks();
  const reader = new MockReader([
    'event: token\ndata: {"text":"partial answer"}\n\n'
  ]);

  await processChatStream(reader, cb);

  assert.equal(cb.calls.onFinal.length, 0);
  assert.equal(cb.calls.onUnexpectedEnd.length, 1);
  assert.equal(cb.calls.onUnexpectedEnd[0].a, 'partial answer (불완전한 응답)');
  assert.equal(cb.calls.onComplete.length, 1);
});

test('processChatStream - handles unexpected EOF when no tokens received', async () => {
  const cb = createMockCallbacks();
  const reader = new MockReader([]);

  await processChatStream(reader, cb);

  assert.equal(cb.calls.onFinal.length, 0);
  assert.equal(cb.calls.onUnexpectedEnd.length, 1);
  assert.equal(cb.calls.onUnexpectedEnd[0].a, '응답이 예기치 않게 종료되었습니다. (불완전한 응답)');
  assert.equal(cb.calls.onComplete.length, 1);
});

test('processChatStream - handles abort error', async () => {
  const cb = createMockCallbacks();
  const err = new Error('aborted');
  err.name = 'AbortError';
  const reader = new MockReader(['event: token\ndata: {"text":"1"}\n\n'], err);

  await processChatStream(reader, cb);

  assert.equal(cb.calls.onAbort.length, 1);
  assert.equal(cb.calls.onComplete.length, 1);
});

test('processChatStream - handles error event', async () => {
  const cb = createMockCallbacks();
  const reader = new MockReader([
    'event: error\ndata: {"message":"fail","trace_id":"trace1"}\n\n'
  ]);

  await processChatStream(reader, cb);

  assert.equal(cb.calls.onError.length, 1);
  assert.equal(cb.calls.onError[0].m, 'fail');
  assert.equal(cb.calls.onError[0].t, 'trace1');
  assert.equal(cb.calls.onComplete.length, 1);
});
