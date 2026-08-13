import { SSEParser } from './sseParser.ts';

export interface ChatStreamCallbacks {
  onStage: (stage: string, message: string) => void;
  onDocs: (docs: any[]) => void;
  onToken: (accumulated: string) => void;
  onFinal: (answer: string, docs: any[], visualizations: any, sessionKey?: string) => void;
  onError: (message: string, traceId: string) => void;
  onAbort: () => void;
  onNetworkError: (message: string) => void;
  onUnexpectedEnd: (accumulated: string) => void;
  onComplete: () => void;
}

export interface ChatRequestBody {
  message: string;
  session_key: string | null;
}

export function buildChatRequestBody(message: string, sessionKey?: string | null): ChatRequestBody {
  return {
    message: message.trim(),
    session_key: sessionKey && sessionKey.trim() !== '' ? sessionKey.trim() : null,
  };
}

export async function processChatStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  callbacks: ChatStreamCallbacks
) {
  const decoder = new TextDecoder('utf-8');
  const parser = new SSEParser();
  let accumulated = '';
  let accumulatedDocs: any[] = [];
  let isFinished = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      for (const event of parser.parseChunk(chunk)) {
        const { event: eventName, data } = event;

        if (eventName === 'stage') {
          callbacks.onStage(data.stage, data.message);
        } else if (eventName === 'docs') {
          accumulatedDocs = data.docs ?? [];
          callbacks.onDocs(accumulatedDocs);
        } else if (eventName === 'token') {
          accumulated += data.text;
          callbacks.onToken(accumulated);
        } else if (eventName === 'final') {
          callbacks.onFinal(
            data.answer || accumulated || '분석이 완료되었습니다.',
            accumulatedDocs,
            data.visualizations,
            data.session_key
          );
          isFinished = true;
          return;
        } else if (eventName === 'error') {
          callbacks.onError(data.message, data.trace_id);
          isFinished = true;
          return;
        }
      }
    }
  } catch (err: any) {
    if (err.name === 'AbortError') {
      callbacks.onAbort();
    } else {
      callbacks.onNetworkError(err.message || '알 수 없는 오류');
    }
    isFinished = true;
  } finally {
    if (!isFinished) {
      const unexpectedMessage = accumulated
        ? `${accumulated} (불완전한 응답)`
        : '응답이 예기치 않게 종료되었습니다. (불완전한 응답)';
      callbacks.onUnexpectedEnd(unexpectedMessage);
    }
    callbacks.onComplete();
  }
}
