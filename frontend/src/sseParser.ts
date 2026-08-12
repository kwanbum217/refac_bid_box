export type SSEEvent = {
  event: string;
  data: any;
};

export class SSEParser {
  private buffer: string = '';

  *parseChunk(chunk: string): Generator<SSEEvent, void, unknown> {
    this.buffer += chunk;
    while (true) {
      const index = this.buffer.indexOf('\n\n');
      if (index === -1) {
        break; // Wait for more data
      }
      
      const frame = this.buffer.slice(0, index);
      this.buffer = this.buffer.slice(index + 2);
      
      const lines = frame.split('\n');
      let eventType = 'message';
      let dataStr = '';
      
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          dataStr += (dataStr ? '\n' : '') + line.slice(6);
        } else if (line.startsWith('event:')) {
          eventType = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          dataStr += (dataStr ? '\n' : '') + line.slice(5);
        }
      }
      
      if (dataStr) {
        try {
          const parsedData = JSON.parse(dataStr);
          yield { event: eventType, data: parsedData };
        } catch (e) {
          yield { event: eventType, data: dataStr };
        }
      }
    }
  }
}
