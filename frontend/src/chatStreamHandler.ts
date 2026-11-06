import { SSEParser } from './sseParser.ts';

export interface ChatStreamCallbacks {
  onStage: (stage: string, message: string) => void;
  onDocs: (docs: unknown[]) => void;
  onToken: (accumulated: string) => void;
  onFinal: (answer: string, docs: unknown[], visualizations: unknown, sessionKey?: string) => void;
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

const readText = (record: Record<string, unknown>, key: string): string => {
  const value = record[key];
  return typeof value === 'string' ? value : '';
};

const readList = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

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
  let accumulatedDocs: unknown[] = [];
  let isFinished = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      for (const event of parser.parseChunk(chunk)) {
        const { event: eventName, data } = event;

        if (eventName === 'stage') {
          callbacks.onStage(readText(data, 'stage'), readText(data, 'message'));
        } else if (eventName === 'docs') {
          accumulatedDocs = readList(data.docs);
          callbacks.onDocs(accumulatedDocs);
        } else if (eventName === 'token') {
          accumulated += readText(data, 'text');
          callbacks.onToken(accumulated);
        } else if (eventName === 'done') {
          const finalAnswer = readText(data, 'final_answer');
          const correctedAnswer = readText(data, 'corrected_answer');
          if (data.leak_blocked && (finalAnswer || correctedAnswer)) {
            accumulated = finalAnswer || correctedAnswer;
            callbacks.onToken(accumulated);
          } else if (correctedAnswer) {
            accumulated = correctedAnswer;
            callbacks.onToken(accumulated);
          } else if (finalAnswer) {
            accumulated = finalAnswer;
            callbacks.onToken(accumulated);
          }
        } else if (eventName === 'final') {
          const finalAnswer = readText(data, 'final_answer');
          const correctedAnswer = readText(data, 'corrected_answer');
          const answer = readText(data, 'answer');
          const resolvedAnswer =
            (data.leak_blocked ? (finalAnswer || correctedAnswer || answer) : '') ||
            correctedAnswer ||
            answer ||
            accumulated ||
            '분석이 완료되었습니다.';
          callbacks.onFinal(
            resolvedAnswer,
            accumulatedDocs,
            data.visualizations,
            readText(data, 'session_key') || undefined
          );
          isFinished = true;
          return;
        } else if (eventName === 'error') {
          callbacks.onError(readText(data, 'message'), readText(data, 'trace_id'));
          isFinished = true;
          return;
        }
      }
    }
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      callbacks.onAbort();
    } else {
      callbacks.onNetworkError(err instanceof Error ? err.message : '알 수 없는 오류');
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
